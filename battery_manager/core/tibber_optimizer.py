#!/usr/bin/env python3
"""
Tibber-basierte Lade-Optimierung
Portiert von Home Assistant Automationen
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class TibberOptimizer:
    """Smart charging optimization based on Tibber prices"""

    def __init__(self, config: Dict):
        self.threshold_1h = config.get('tibber_price_threshold_1h', 8) / 100
        self.threshold_3h = config.get('tibber_price_threshold_3h', 8) / 100
        self.charge_duration_per_10 = config.get('charge_duration_per_10_percent', 18)

    def find_optimal_charge_end_time(self, prices: List[Dict]) -> Optional[datetime]:
        """
        Findet den optimalen Zeitpunkt zum Beenden der Ladung.
        Das ist der Moment, an dem der Preis nach einer günstigen Phase wieder steigt.

        Args:
            prices: Liste von Preis-Dicts mit 'total', 'startsAt', 'level'

        Returns:
            datetime des optimalen Ladeendes oder None
        """
        # v0.3.3 - Use timezone-aware datetime for comparison
        now = datetime.now().astimezone()

        # Brauchen mindestens 6 Datenpunkte (3 zurück, aktuell, 2 voraus)
        if len(prices) < 6:
            logger.warning("Not enough price data for optimization")
            return None

        # Durchlaufe Preise ab Index 3 (brauchen 2h Historie)
        for i in range(3, len(prices) - 2):
            try:
                # Parse startsAt Zeit
                starts_at_str = prices[i]['startsAt']
                starts_at = datetime.fromisoformat(starts_at_str.replace('Z', '+00:00'))

                # Überspringe vergangene Zeiten
                if starts_at <= now:
                    continue

                # Hole Preise
                current_price = float(prices[i]['total'])
                price_1h_ago = float(prices[i-1]['total'])
                price_2h_ago = float(prices[i-2]['total'])
                price_1h_future = float(prices[i+1]['total'])
                price_2h_future = float(prices[i+2]['total'])

                # Berechne 3h Summen
                sum_3h_past = current_price + price_1h_ago + price_2h_ago
                sum_3h_future = current_price + price_1h_future + price_2h_future

                # Bedingung 1: Preis steigt um mehr als Schwelle zur vorherigen Stunde
                condition_1 = current_price > price_1h_ago * (1 + self.threshold_1h)

                # Bedingung 2: Nächste 3h Block teurer als vergangener 3h Block
                condition_2 = sum_3h_past < sum_3h_future * (1 + self.threshold_3h)

                if condition_1 and condition_2:
                    logger.info(f"Found optimal charge end time: {starts_at}")
                    logger.info(f"  Current price: {current_price:.4f}, 1h ago: {price_1h_ago:.4f}")
                    logger.info(f"  3h past sum: {sum_3h_past:.4f}, 3h future sum: {sum_3h_future:.4f}")
                    return starts_at

            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Error processing price data at index {i}: {e}")
                continue

        logger.info("No optimal charge end time found (prices stay low)")
        return None

    def calculate_charge_start_time(self,
                                     charge_end: datetime,
                                     current_soc: float,
                                     target_soc: float = 95) -> datetime:
        """
        Berechnet den Ladebeginn basierend auf SOC-Differenz.

        Args:
            charge_end: Gewünschter Ladezeitpunkt Ende
            current_soc: Aktueller SOC in %
            target_soc: Ziel-SOC in %

        Returns:
            datetime des Ladebeginns
        """
        # Berechne benötigte Ladung
        soc_diff = target_soc - current_soc

        if soc_diff <= 0:
            # Bereits voll genug
            return charge_end

        # Berechne Ladedauer in Minuten
        charge_duration_minutes = (soc_diff / 10) * self.charge_duration_per_10

        # Berechne Startzeit
        charge_start = charge_end - timedelta(minutes=charge_duration_minutes)

        logger.info(f"Calculated charge start: {charge_start}")
        logger.info(f"  SOC: {current_soc}% → {target_soc}% ({soc_diff}%)")
        logger.info(f"  Duration: {charge_duration_minutes:.0f} minutes")

        return charge_start

    def should_charge_now(self,
                         planned_start: Optional[datetime],
                         current_soc: float,
                         min_soc: float,
                         max_soc: float,
                         pv_remaining: float) -> tuple[bool, str]:
        """
        Entscheidet ob jetzt geladen werden soll.

        Returns:
            (should_charge: bool, reason: str)
        """
        # v0.3.3 - Use timezone-aware datetime for comparison
        now = datetime.now().astimezone()

        # Sicherheit: SOC zu niedrig
        if current_soc < min_soc:
            return True, f"SOC below minimum ({current_soc}% < {min_soc}%)"

        # Bereits voll genug
        if current_soc >= max_soc:
            return False, f"Battery full ({current_soc}% >= {max_soc}%)"

        # Genug PV erwartet - nicht aus Netz laden
        if pv_remaining > 5:  # mehr als 5 kWh PV erwartet
            return False, f"Sufficient PV expected ({pv_remaining:.1f} kWh)"

        # Geplanter Ladezeitpunkt erreicht?
        if planned_start and now >= planned_start:
            return True, f"Planned charging time reached"

        return False, "Waiting for optimal charging window"
