#!/usr/bin/env python3
"""
Forecast.Solar Professional API Client

Fetches hourly solar production forecasts from forecast.solar API
Supports multiple planes (roof orientations) and caching
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ForecastSolarAPI:
    """Client for forecast.solar Professional API"""

    def __init__(self, api_key: str, latitude: float, longitude: float):
        """
        Initialize forecast.solar API client

        Args:
            api_key: forecast.solar Professional API key
            latitude: Location latitude
            longitude: Location longitude
        """
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.base_url = "https://api.forecast.solar"

        # Cache for API responses (15 min cache)
        self._cache = {}
        self._cache_timestamp = None
        self._cache_duration = timedelta(minutes=15)

        logger.info(f"Forecast.Solar API initialized (lat={latitude}, lon={longitude})")

    def _build_url(self, endpoint: str, declination: int, azimuth: int, kwp: float) -> str:
        """
        Build API URL for a single plane

        Args:
            endpoint: API endpoint (e.g., 'estimate')
            declination: Roof tilt angle (0-90°)
            azimuth: Roof orientation (-180 to 180°, 0=South, 90=West, -90=East)
            kwp: Peak power in kWp

        Returns:
            Complete API URL
        """
        # Convert float to URL-safe format
        lat = str(self.latitude).replace('.', ',')
        lon = str(self.longitude).replace('.', ',')
        kwp_str = str(kwp).replace('.', ',')

        # Ohne Key laeuft die oeffentliche Schnittstelle (das Key-Segment
        # entfaellt dann komplett). Sie ist auf wenige Abfragen pro Stunde
        # begrenzt, was durch den 15-Minuten-Cache eingehalten wird.
        prefix = f"/{self.api_key}" if self.api_key else ""

        url = (f"{self.base_url}{prefix}/{endpoint}/"
               f"{lat}/{lon}/{declination}/{azimuth}/{kwp_str}")

        return url

    def get_hourly_forecast(self,
                           planes: list,
                           days: int = 1,
                           for_date=None) -> Dict[int, float]:
        """
        Get hourly solar production forecast.

        Args:
            planes: List of dicts with 'declination', 'azimuth', 'kwp'
                   e.g., [{'declination': 22, 'azimuth': 45, 'kwp': 8.96}]
            days: unbenutzt, aus Kompatibilitaetsgruenden erhalten
            for_date: Zieldatum. None = heute. Die API liefert heute UND
                      morgen, deshalb ist die Prognose fuer morgen ohne
                      zusaetzlichen Abruf verfuegbar.

        Returns:
            dict: {hour: kwh_forecast} for each hour (0-23)
        """
        target_date = for_date or datetime.now().astimezone().date()

        # Cache haelt die Rohdaten je Datum - so kostet die Abfrage fuer
        # morgen keinen zusaetzlichen API-Call (Ratelimit ohne Key!)
        if self._is_cache_valid():
            cached = self._cache.get('by_date', {}).get(str(target_date))
            if cached is not None:
                logger.debug(f"Using cached forecast.solar data for {target_date}")
                return cached

        try:
            by_date = {}

            # Fetch forecast for each plane and combine
            for i, plane in enumerate(planes):
                logger.debug(f"Fetching forecast for plane {i+1}: "
                           f"azimuth={plane['azimuth']}°, "
                           f"tilt={plane['declination']}°, "
                           f"kWp={plane['kwp']}")

                # 'watthours/period' liefert Werte PRO STUNDE.
                # 'watthours' waere der ueber den Tag kumulierte Wert -
                # damit rechnete diese Klasse frueher falsch.
                url = self._build_url(
                    endpoint='estimate/watthours/period',
                    declination=plane['declination'],
                    azimuth=plane['azimuth'],
                    kwp=plane['kwp']
                )

                logger.debug(f"API URL: {url}")

                response = requests.get(url, timeout=10)

                if response.status_code != 200:
                    logger.error(f"Forecast.Solar API error: HTTP {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    continue

                data = response.json()

                # Die API liefert result als flaches {Zeitstempel: Wh}.
                result = data.get('result')
                if isinstance(result, dict) and result:
                    logger.debug(f"Plane {i+1}: received {len(result)} hourly values")

                    for timestamp_str, wh_value in result.items():
                        try:
                            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                        except (ValueError, TypeError):
                            logger.warning(f"Error parsing timestamp {timestamp_str}")
                            continue

                        day = by_date.setdefault(str(dt.date()), {})
                        day[dt.hour] = day.get(dt.hour, 0.0) + float(wh_value) / 1000.0
                else:
                    logger.warning(f"Plane {i+1}: unerwartete API-Antwort, "
                                   f"'result' fehlt oder ist leer")

            self._cache['by_date'] = by_date
            hourly_forecast = by_date.get(str(target_date), {})

            if by_date:
                # Zeitstempel setzen, NICHT self._cache ersetzen - sonst
                # ginge die Tagesaufteilung verloren und die Prognose fuer
                # morgen wuerde bei jedem Aufruf neu abgerufen.
                self._cache_timestamp = datetime.now()
                logger.info(f"✓ Forecast.Solar: {sum(len(v) for v in by_date.values())} Stundenwerte "
                            f"fuer {len(by_date)} Tage abgerufen")
                logger.debug(f"Hourly forecast for {target_date} (kWh): {hourly_forecast}")

            if not hourly_forecast:
                logger.warning(f"Keine Stundenprognose fuer {target_date} verfuegbar")

            return hourly_forecast

        except requests.RequestException as e:
            logger.error(f"Network error calling Forecast.Solar API: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error getting hourly forecast from Forecast.Solar: {e}", exc_info=True)
            return {}

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self._cache or not self._cache_timestamp:
            return False

        age = datetime.now() - self._cache_timestamp
        return age < self._cache_duration

    def clear_cache(self):
        """Clear cached forecast data"""
        self._cache = {}
        self._cache_timestamp = None
        logger.debug("Forecast.Solar cache cleared")
