#!/usr/bin/env python3
"""
!!! VERALTET - NICHT MEHR VERDRAHTET (Stand v0.10.0) !!!

Dieses Modul plant eine abendliche Nachladung auf einen Ziel-SOC. Der
Aufrufer setzte dafuer Register 1034 (Ladesetpoint) - und weil der
Trigger der PV-Abfall am Abend ist, kam diese Energie zwangsweise aus
dem NETZ. Fuer eine PV-only-Anlage ist das genau falsch.

Ersetzt durch core/pv_shaping_planner.py, das ausschliesslich Grenzen
(Register 1038/1040/1042/1044) setzt und damit nie Netzstrom zieht.

Datei bleibt vorerst als Referenz erhalten, wird aber von app.py nicht
mehr importiert. Nicht ohne Umbau reaktivieren.

---

Forecast-basierte Lade-Optimierung ("Evening Top-up")

Ersetzt die preisbasierte Tibber-Logik durch einen rein prognosebasierten Ansatz:
- Kein Laden anhand von Strompreisen
- Ein einziger, kompakter Ladevorgang pro Tag (statt mehrerer verteilter Fenster)
- Dynamischer Trigger-Zeitpunkt anhand des PV-Abfalls am Abend
- Ziel-SOC bleibt in einem schonenden Korridor (z.B. 30-80%), nicht bei 95-100%
- Sicherheitsmarge auf die PV-Prognose (Wetterrisiko)
- Eskalation nach mehreren aufeinanderfolgenden Tagen mit Korridor-Unterschreitung
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ForecastOptimizer:
    """Smart charging optimization based purely on PV-forecast + learned consumption"""

    def __init__(self, config: Dict):
        self.soc_corridor_min = config.get('soc_corridor_min', 30)
        self.soc_corridor_max = config.get('soc_corridor_max', 80)
        self.soc_hard_safety_min = config.get('soc_hard_safety_min', 15)
        self.pv_forecast_safety_margin = config.get('pv_forecast_safety_margin', 0.8)
        self.pv_dropoff_threshold = config.get('pv_dropoff_threshold', 0.05)
        self.escalation_days = config.get('escalation_days', 2)
        self.escalation_soc_boost = config.get('escalation_soc_boost', 15)

        self.consumption_learner = None
        self.forecast_solar_api = None

        # State for the "once per evening" trigger and escalation tracking
        self._last_topup_check_date = None
        self._corridor_breach_streak = 0
        self._last_breach_check_date = None

    def set_consumption_learner(self, learner):
        self.consumption_learner = learner
        logger.info("Consumption learner integrated into forecast optimizer")

    def set_forecast_solar_api(self, api):
        self.forecast_solar_api = api
        logger.info("Forecast.Solar API integrated into forecast optimizer")

    # ------------------------------------------------------------------
    # PV forecast helper (reuses the same hourly-forecast source as
    # TibberOptimizer, but kept local so this module has no dependency
    # on tibber_optimizer.py)
    # ------------------------------------------------------------------
    def get_hourly_pv_forecast(self, ha_client, config, for_date=None) -> Dict[int, float]:
        """Returns {hour: kwh} forecast for today (for_date=None) or a given date."""
        if self.forecast_solar_api and config.get('enable_forecast_solar_api', False):
            planes = config.get('forecast_solar_planes', [])
            if planes:
                try:
                    hourly_forecast = self.forecast_solar_api.get_hourly_forecast(planes)
                    if hourly_forecast:
                        return hourly_forecast
                except Exception as e:
                    logger.error(f"Forecast.Solar API error: {e}, falling back to sensors")

        # Fallback: HA sensors with wh_hours attribute (roof1/roof2)
        hourly_forecast = {}
        target_date = for_date or datetime.now().astimezone().date()
        for sensor_key in ('pv_production_today_roof1', 'pv_production_today_roof2'):
            sensor = config.get(sensor_key)
            if not sensor:
                continue
            attrs = ha_client.get_attributes(sensor) if ha_client else None
            if not attrs or 'wh_hours' not in attrs:
                continue
            for ts_str, wh_value in attrs['wh_hours'].items():
                try:
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    if dt.date() != target_date:
                        continue
                    hourly_forecast[dt.hour] = hourly_forecast.get(dt.hour, 0.0) + float(wh_value) / 1000.0
                except (ValueError, TypeError):
                    continue
        return hourly_forecast

    # ------------------------------------------------------------------
    # 1. Trigger: dynamic PV drop-off detection
    # ------------------------------------------------------------------
    def is_evening_trigger_hour(self, ha_client, config, current_hour: int) -> bool:
        """
        True once PV production has dropped below `pv_dropoff_threshold`
        (fraction of today's peak hourly forecast) for the current hour.
        """
        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        if not pv_today:
            logger.warning("No PV forecast available for trigger check")
            return False

        peak = max(pv_today.values()) if pv_today else 0.0
        if peak <= 0:
            return False

        current_pv = pv_today.get(current_hour, 0.0)
        is_dropoff = current_pv < (peak * self.pv_dropoff_threshold)

        # Only trigger during the evening half of the day (after the peak hour),
        # to avoid false positives from a cloudy dip at midday.
        peak_hour = max(pv_today, key=pv_today.get)
        return is_dropoff and current_hour >= peak_hour

    # ------------------------------------------------------------------
    # 2. Overnight demand forecast (from learned consumption)
    # ------------------------------------------------------------------
    def calculate_overnight_need_kwh(self, ha_client, config, trigger_hour: int) -> float:
        """
        Sums learned consumption from trigger_hour until PV is expected
        to meaningfully resume the next day.
        """
        if not self.consumption_learner:
            logger.warning("No consumption learner available, cannot forecast overnight need")
            return 0.0

        now = datetime.now().astimezone()
        pv_tomorrow = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )
        peak_tomorrow = max(pv_tomorrow.values()) if pv_tomorrow else 0.0
        resume_threshold = peak_tomorrow * self.pv_dropoff_threshold if peak_tomorrow > 0 else None

        total_consumption = 0.0
        hour = trigger_hour
        date = now.date()
        steps = 0
        max_steps = 30  # hard safety cap (~30h) in case of bad data

        while steps < max_steps:
            steps += 1
            hour = (hour + 1) % 24
            if hour == 0:
                date = date + timedelta(days=1)

            # Stop once tomorrow's PV is meaningfully producing again
            if date > now.date() and resume_threshold is not None:
                pv_this_hour = pv_tomorrow.get(hour, 0.0)
                if pv_this_hour >= resume_threshold:
                    break

            total_consumption += self.consumption_learner.get_average_consumption(hour, target_date=date)

        logger.info(f"Overnight need forecast: {total_consumption:.2f} kWh "
                    f"(from {trigger_hour}:00 over {steps}h)")
        return total_consumption

    # ------------------------------------------------------------------
    # 3. Escalation tracking (consecutive corridor breaches)
    # ------------------------------------------------------------------
    def record_corridor_breach_check(self, current_soc: float) -> int:
        """Call once per day (e.g. at the trigger hour) to track breach streaks."""
        today = datetime.now().astimezone().date()
        if self._last_breach_check_date == today:
            return self._corridor_breach_streak  # already recorded today

        if current_soc < self.soc_corridor_min:
            self._corridor_breach_streak += 1
        else:
            self._corridor_breach_streak = 0
        self._last_breach_check_date = today

        if self._corridor_breach_streak >= self.escalation_days:
            logger.warning(f"Corridor breached {self._corridor_breach_streak} days in a row - "
                            f"escalating target SOC by {self.escalation_soc_boost}%")
        return self._corridor_breach_streak

    # ------------------------------------------------------------------
    # 4. Main decision: single evening top-up check
    # ------------------------------------------------------------------
    def evaluate_evening_topup(self,
                                ha_client,
                                config,
                                current_soc: float,
                                battery_capacity: float) -> Dict:
        """
        Runs the once-per-evening decision. Safe to call repeatedly (e.g. every
        control_interval) - internally guards so the real evaluation only
        happens once per calendar day, once the PV drop-off trigger fires.

        Returns:
            dict: {
                'should_charge': bool,
                'target_soc': float,
                'reason': str,
                'checked': bool  # whether a real evaluation ran this call
            }
        """
        now = datetime.now().astimezone()
        current_hour = now.hour
        today = now.date()

        result = {'should_charge': False, 'target_soc': current_soc,
                  'reason': 'No check due', 'checked': False}

        # Hard safety net always applies, independent of the daily check
        if current_soc < self.soc_hard_safety_min:
            return {'should_charge': True, 'target_soc': self.soc_corridor_min,
                    'reason': f'SAFETY: SOC below hard minimum ({current_soc:.1f}% < {self.soc_hard_safety_min}%)',
                    'checked': True}

        # Only run the full evaluation once per day, at/after the PV drop-off trigger
        if self._last_topup_check_date == today:
            return result

        if not self.is_evening_trigger_hour(ha_client, config, current_hour):
            return result

        # From here: real evening evaluation, marks the day as done
        self._last_topup_check_date = today
        result['checked'] = True

        breach_streak = self.record_corridor_breach_check(current_soc)
        target_max = self.soc_corridor_max
        if breach_streak >= self.escalation_days:
            target_max = min(95, self.soc_corridor_max + self.escalation_soc_boost)

        needed_kwh = self.calculate_overnight_need_kwh(ha_client, config, current_hour)
        # Apply safety margin: we only "trust" a fraction of PV that could still land
        # tonight/tomorrow-morning before the resume threshold - so we don't discount
        # consumption itself, but we do discount how much we rely on late PV to save us.
        needed_kwh = needed_kwh  # (kept explicit for readability / future tuning)

        current_kwh = (current_soc / 100) * battery_capacity
        min_kwh = (self.soc_corridor_min / 100) * battery_capacity
        available_kwh = current_kwh - min_kwh

        deficit_kwh = needed_kwh - available_kwh

        if deficit_kwh <= 0:
            result.update({
                'should_charge': False,
                'target_soc': current_soc,
                'reason': (f'Evening check OK: {current_soc:.1f}% covers forecasted '
                           f'overnight need ({needed_kwh:.2f} kWh), no grid charge needed')
            })
            return result

        target_kwh = min(current_kwh + deficit_kwh, (target_max / 100) * battery_capacity)
        target_soc = (target_kwh / battery_capacity) * 100

        result.update({
            'should_charge': True,
            'target_soc': round(target_soc, 1),
            'reason': (f'Evening top-up: forecast deficit {deficit_kwh:.2f} kWh '
                       f'-> charging {current_soc:.1f}% -> {target_soc:.1f}%'
                       + (f' (escalated corridor, {breach_streak} breach days)' if breach_streak >= self.escalation_days else ''))
        })
        return result