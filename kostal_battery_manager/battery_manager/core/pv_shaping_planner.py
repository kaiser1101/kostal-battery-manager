#!/usr/bin/env python3
"""
PV-Shaping-Planer (v0.10.0)

Ersetzt die "Evening Top-up"-Logik, die noch davon ausging, dass abends
Netzstrom zugekauft wird. Hier wird NIE aus dem Netz geladen.

Stattdessen werden dem Wechselrichter nur GRENZEN vorgegeben
(Modbus 1038/1040/1042/1044). Seine interne Eigenverbrauchs-Optimierung
laeuft unveraendert weiter - eben nur innerhalb dieses Rahmens.

Ziel ist Batterielebensdauer:
  - Max-SOC dynamisch deckeln, wenn morgen viel PV kommt
    -> weniger Kalendarische Alterung durch Verweilen bei hohem SOC
  - Ladeleistung drosseln, damit die Ladung ueber den Nachmittag
    verteilt wird statt vormittags mit voller Leistung
    -> niedrigere C-Rate UND spaeteres Erreichen des Ziel-SOC
  - Entladegrenze schuetzen, damit keine Tiefentladung entsteht
  - Periodische Kalibrierladung auf 100%, damit die SOC-Anzeige
    des BMS nicht wegdriftet
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PVShapingPlanner:
    """Berechnet Batterie-Grenzwerte aus PV-Prognose und gelerntem Verbrauch."""

    def __init__(self, config: Dict, state_path: str = '/data/pv_shaping_state.json'):
        self.soc_corridor_min = config.get('soc_corridor_min', 30)
        self.soc_corridor_max = config.get('soc_corridor_max', 80)
        self.soc_hard_safety_min = config.get('soc_hard_safety_min', 15)
        self.pv_forecast_safety_margin = config.get('pv_forecast_safety_margin', 0.8)
        self.pv_dropoff_threshold = config.get('pv_dropoff_threshold', 0.05)

        self.min_charge_power = config.get('min_charge_power', 500)
        self.enable_charge_throttling = config.get('enable_charge_throttling', True)
        self.calibration_interval_days = config.get('calibration_interval_days', 28)
        self.calibration_min_pv_kwh = config.get('calibration_min_pv_kwh', 15.0)

        self.consumption_learner = None
        self.forecast_solar_api = None

        self.state_path = state_path
        self._state = self._load_state()

        # Bei Erstinstallation gibt es noch kein Kalibrierdatum. Ohne
        # Startwert waere die Kalibrierung sofort faellig und die Batterie
        # wuerde ab Tag 1 taeglich auf 100% laden - genau das Gegenteil
        # des Ziels. Deshalb: Intervall ab heute rechnen.
        if 'last_calibration_date' not in self._state:
            self._state['last_calibration_date'] = datetime.now().astimezone().date().isoformat()
            self._save_state()
            logger.info(f"Kalibrier-Intervall initialisiert - erste Kalibrierladung in "
                        f"{self.calibration_interval_days} Tagen")

    # ------------------------------------------------------------------
    # Abhaengigkeiten
    # ------------------------------------------------------------------
    def set_consumption_learner(self, learner):
        self.consumption_learner = learner
        logger.info("Consumption learner integrated into PV shaping planner")

    def set_forecast_solar_api(self, api):
        self.forecast_solar_api = api
        logger.info("Forecast.Solar API integrated into PV shaping planner")

    # ------------------------------------------------------------------
    # Persistenter Zustand (nur fuer die Kalibrierladung)
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load planner state: {e}")
        return {}

    def _save_state(self):
        try:
            with open(self.state_path, 'w') as f:
                json.dump(self._state, f)
        except Exception as e:
            logger.warning(f"Could not save planner state: {e}")

    # ------------------------------------------------------------------
    # PV-Prognose
    # ------------------------------------------------------------------
    def get_hourly_pv_forecast(self, ha_client, config, for_date=None) -> Dict[int, float]:
        """Liefert {Stunde: kWh} fuer heute (for_date=None) oder ein Datum."""
        target_date = for_date or datetime.now().astimezone().date()

        if self.forecast_solar_api and config.get('enable_forecast_solar_api', False):
            planes = config.get('forecast_solar_planes', [])
            if planes:
                try:
                    # for_date durchreichen - sonst kaeme fuer "morgen" die
                    # Kurve von heute zurueck und der SOC-Deckel waere falsch.
                    hourly = self.forecast_solar_api.get_hourly_forecast(
                        planes, for_date=target_date
                    )
                    if hourly:
                        return hourly
                except Exception as e:
                    logger.error(f"Forecast.Solar API error: {e}, falling back to sensors")

        hourly_forecast = {}
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

    def _sunset_hour(self, pv_forecast: Dict[int, float]) -> Optional[int]:
        """Letzte Stunde, in der nennenswert PV erwartet wird."""
        if not pv_forecast:
            return None
        peak = max(pv_forecast.values())
        if peak <= 0:
            return None
        threshold = peak * self.pv_dropoff_threshold
        producing = [h for h, kwh in pv_forecast.items() if kwh >= threshold]
        return max(producing) if producing else None

    def _sunrise_hour(self, pv_forecast: Dict[int, float]) -> Optional[int]:
        """Erste Stunde, in der nennenswert PV erwartet wird."""
        if not pv_forecast:
            return None
        peak = max(pv_forecast.values())
        if peak <= 0:
            return None
        threshold = peak * self.pv_dropoff_threshold
        producing = [h for h, kwh in pv_forecast.items() if kwh >= threshold]
        return min(producing) if producing else None

    # ------------------------------------------------------------------
    # Verbrauchsprognose
    # ------------------------------------------------------------------
    def _consumption_between(self, start_dt: datetime, hours: int) -> float:
        """Summiert den gelernten Verbrauch ueber die naechsten `hours` Stunden."""
        if not self.consumption_learner or hours <= 0:
            return 0.0

        total = 0.0
        cursor = start_dt
        for _ in range(int(hours)):
            cursor = cursor + timedelta(hours=1)
            total += self.consumption_learner.get_average_consumption(
                cursor.hour, target_date=cursor.date()
            )
        return total

    def calculate_overnight_need_kwh(self, ha_client, config, now: datetime) -> float:
        """
        Verbrauch vom heutigen Sonnenuntergang bis zum morgigen
        Sonnenaufgang - das ist die Energie, die die Batterie ueber
        die Nacht tragen muss.
        """
        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        pv_tomorrow = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )

        sunset = self._sunset_hour(pv_today)
        sunrise_tomorrow = self._sunrise_hour(pv_tomorrow)

        # Fallbacks, wenn keine Prognose vorliegt
        if sunset is None:
            sunset = 20
        if sunrise_tomorrow is None:
            sunrise_tomorrow = 8

        # Stunden von Sonnenuntergang bis Sonnenaufgang am Folgetag
        night_hours = (24 - sunset) + sunrise_tomorrow
        start = now.replace(hour=sunset, minute=0, second=0, microsecond=0)

        need = self._consumption_between(start, night_hours)
        logger.debug(f"Overnight need: {need:.2f} kWh ({sunset}:00 -> {sunrise_tomorrow}:00, {night_hours}h)")
        return need

    def calculate_tomorrow_shortfall_kwh(self, ha_client, config, now: datetime) -> float:
        """
        Erwarteter Fehlbetrag am Folgetag: Wenn die Prognose fuer morgen
        den Tagesverbrauch nicht deckt, muss die Batterie heute mehr
        Reserve mitnehmen.
        """
        pv_tomorrow = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )
        if not pv_tomorrow:
            # Keine Prognose = kein Vertrauen. Konservativ: kein Deckel-Rabatt.
            return None

        pv_kwh = sum(pv_tomorrow.values()) * self.pv_forecast_safety_margin

        tomorrow_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        consumption_kwh = self._consumption_between(tomorrow_start - timedelta(hours=1), 24)

        shortfall = max(0.0, consumption_kwh - pv_kwh)
        logger.debug(f"Tomorrow: PV {pv_kwh:.1f} kWh (nach Marge) vs Verbrauch "
                     f"{consumption_kwh:.1f} kWh -> Fehlbetrag {shortfall:.1f} kWh")
        return shortfall

    # ------------------------------------------------------------------
    # Kalibrierladung
    # ------------------------------------------------------------------
    def is_calibration_due(self, ha_client, config, now: datetime) -> bool:
        """
        LFP-Zellen brauchen periodisch eine Vollladung, damit das BMS
        seine SOC-Schaetzung neu kalibrieren kann. Wir tun das nur an
        Tagen mit viel PV - dann kostet es keinen Netzstrom.
        """
        if self.calibration_interval_days <= 0:
            return False

        last = self._state.get('last_calibration_date')
        if last:
            try:
                last_date = datetime.fromisoformat(last).date()
                days_since = (now.date() - last_date).days
                if days_since < self.calibration_interval_days:
                    return False
            except ValueError:
                pass

        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        pv_kwh = sum(pv_today.values()) if pv_today else 0.0
        if pv_kwh < self.calibration_min_pv_kwh:
            logger.debug(f"Kalibrierung faellig, aber PV-Prognose zu niedrig "
                         f"({pv_kwh:.1f} < {self.calibration_min_pv_kwh} kWh) - warte auf besseren Tag")
            return False

        return True

    def mark_calibration_done(self, now: datetime):
        self._state['last_calibration_date'] = now.date().isoformat()
        self._save_state()
        logger.info("Kalibrierladung abgeschlossen und vermerkt")

    # ------------------------------------------------------------------
    # Hauptberechnung
    # ------------------------------------------------------------------
    def plan(self, ha_client, config, current_soc: float, battery_capacity: float,
             now: Optional[datetime] = None) -> Dict:
        """
        Berechnet die Grenzwerte fuer den aktuellen Zeitpunkt.

        Args:
            now: Zeitpunkt der Planung. Default = jetzt. Injizierbar,
                 damit Szenarien testbar sind.

        Returns:
            dict mit max_soc, min_soc, max_charge_power, max_discharge_power,
            reason und diagnostischen Zwischenwerten.
        """
        now = now or datetime.now().astimezone()
        configured_max_power = float(config.get('max_charge_power', 3900))

        plan = {
            'timestamp': now.isoformat(),
            'current_soc': current_soc,
            'max_soc': float(self.soc_corridor_max),
            'min_soc': float(self.soc_corridor_min),
            'max_charge_power': configured_max_power,
            'max_discharge_power': configured_max_power,
            'mode': 'normal',
            'reason': '',
            'diagnostics': {},
        }

        # --- 1. Harte Notbremse ---------------------------------------
        # Ohne Netzladung koennen wir bei tiefem SOC nicht nachladen.
        # Die einzig sinnvolle Reaktion ist: Entladen stoppen und auf
        # PV warten.
        if current_soc < self.soc_hard_safety_min:
            plan.update({
                'mode': 'safety',
                'max_soc': 100.0,
                'min_soc': float(self.soc_hard_safety_min),
                'max_charge_power': configured_max_power,
                'max_discharge_power': 0.0,
                'reason': (f'SICHERHEIT: SOC {current_soc:.1f}% unter Hartgrenze '
                           f'{self.soc_hard_safety_min}% - Entladen gesperrt, '
                           f'Laden aus PV mit voller Leistung freigegeben'),
            })
            return plan

        # --- 2. Kalibrierladung ---------------------------------------
        if self.is_calibration_due(ha_client, config, now):
            plan.update({
                'mode': 'calibration',
                'max_soc': 100.0,
                'min_soc': float(self.soc_corridor_min),
                'max_charge_power': configured_max_power,
                'reason': (f'Kalibrierladung faellig (alle {self.calibration_interval_days} Tage) '
                           f'und PV-Prognose ausreichend - Ladung auf 100% freigegeben'),
            })
            if current_soc >= 99.0:
                self.mark_calibration_done(now)
                plan['reason'] += ' | 100% erreicht, Kalibrierung vermerkt'
            return plan

        # --- 3. Dynamischer SOC-Deckel --------------------------------
        overnight_kwh = self.calculate_overnight_need_kwh(ha_client, config, now)
        shortfall_kwh = self.calculate_tomorrow_shortfall_kwh(ha_client, config, now)

        if shortfall_kwh is None:
            # Ohne Prognose fuer morgen bleiben wir beim Korridor-Maximum.
            reserve_kwh = overnight_kwh
            target_soc = self.soc_corridor_max
            cap_reason = 'keine Prognose fuer morgen - Korridor-Maximum'
        else:
            reserve_kwh = overnight_kwh + shortfall_kwh
            # SOC, der diese Reserve zusaetzlich zur Entladegrenze traegt
            target_soc = self.soc_corridor_min + (reserve_kwh / battery_capacity) * 100
            if shortfall_kwh <= 0:
                cap_reason = (f'morgen deckt PV den Verbrauch - nur Nachtbedarf '
                              f'{overnight_kwh:.1f} kWh noetig')
            else:
                cap_reason = (f'morgen fehlen {shortfall_kwh:.1f} kWh - Reserve '
                              f'{reserve_kwh:.1f} kWh noetig')

        max_soc = max(self.soc_corridor_min + 5.0, min(self.soc_corridor_max, target_soc))

        # --- 4. Entladegrenze -----------------------------------------
        min_soc = float(self.soc_corridor_min)

        # --- 5. Ladeleistung drosseln ---------------------------------
        # Die noch fehlende Energie ueber die verbleibenden PV-Stunden
        # verteilen. Das senkt die C-Rate UND verschiebt das Erreichen
        # des Ziel-SOC nach hinten, statt vormittags voll durchzuladen.
        max_charge_power = configured_max_power
        throttle_reason = 'volle Ladeleistung'

        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        sunset = self._sunset_hour(pv_today)
        sunrise = self._sunrise_hour(pv_today)

        if sunset is None or sunrise is None:
            throttle_reason = 'keine PV-Prognose - volle Ladeleistung'

        elif now.hour < sunrise or now.hour > sunset:
            # Ausserhalb der PV-Stunden koennte Ladung nur aus dem Netz
            # kommen. Das Limit auf 0 zu setzen sperrt das hart auf
            # Registerebene - unabhaengig davon, was die interne Logik
            # oder eine andere Integration versucht.
            max_charge_power = 0.0
            throttle_reason = ('ausserhalb der PV-Stunden - Laden gesperrt '
                               '(verhindert Netzladung)')

        elif self.enable_charge_throttling:
            # Aktuelle Stunde zaehlt mit, deshalb +1
            hours_left = max(1, sunset - now.hour + 1)
            deficit_kwh = max(0.0, (max_soc - current_soc) / 100 * battery_capacity)

            if deficit_kwh <= 0:
                max_charge_power = 0.0
                throttle_reason = f'Ziel-SOC {max_soc:.1f}% bereits erreicht - Laden pausiert'
            else:
                spread_w = (deficit_kwh * 1000) / hours_left
                max_charge_power = min(configured_max_power,
                                       max(self.min_charge_power, spread_w))
                throttle_reason = (f'{deficit_kwh:.1f} kWh auf {hours_left}h bis '
                                   f'Sonnenuntergang verteilt')

        plan.update({
            'max_soc': round(max_soc, 1),
            'min_soc': round(min_soc, 1),
            'max_charge_power': round(max_charge_power, 0),
            'max_discharge_power': configured_max_power,
            'reason': f'Deckel {max_soc:.1f}% ({cap_reason}); {throttle_reason}',
            'diagnostics': {
                'overnight_need_kwh': round(overnight_kwh, 2),
                'tomorrow_shortfall_kwh': round(shortfall_kwh, 2) if shortfall_kwh is not None else None,
                'sunset_hour': sunset,
                'pv_today_kwh': round(sum(pv_today.values()), 2) if pv_today else 0.0,
            },
        })
        return plan
