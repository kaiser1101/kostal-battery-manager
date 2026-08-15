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

        # Cache fuer API-Antworten. Ein Abruf deckt alle Ebenen und beide
        # Tage ab; danach wird 30 Minuten lang nichts mehr angefragt.
        # Ohne Key erlaubt forecast.solar nur 12 Abrufe pro Stunde und IP.
        self._cache = {}
        self._cache_timestamp = None
        self._cache_duration = timedelta(minutes=30)

        # Sperre nach einem Fehlschlag, damit ein 429 keine Abruf-Lawine
        # ausloest. Wird bei HTTP 429 aus der Antwort ("retry-at") gesetzt.
        self._retry_not_before = None

        logger.info(f"Forecast.Solar API initialized (lat={latitude}, lon={longitude})")

    @staticmethod
    def merge_planes(planes: list) -> list:
        """
        Fasst Ebenen mit identischer Neigung UND Ausrichtung zusammen.

        Zwei Ebenen gleicher Geometrie liefern dieselbe Tageskurve, nur
        anders skaliert - die Summe ihrer kWp ergibt exakt dasselbe
        Ergebnis mit der Haelfte der Abrufe. Bei unterschiedlicher
        Geometrie bleiben sie getrennt.
        """
        merged = {}
        for plane in planes:
            key = (plane['declination'], plane['azimuth'])
            if key in merged:
                merged[key]['kwp'] += plane['kwp']
            else:
                merged[key] = dict(plane)
        result = list(merged.values())
        if len(result) < len(planes):
            logger.info(f"{len(planes)} Ebenen mit gleicher Geometrie zu {len(result)} "
                        f"zusammengefasst - spart API-Abrufe")
        return result

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

        # Der Cache haelt die Rohdaten ALLER Tage aus einem Abruf.
        # Wichtig: auch ein fehlendes Datum wird aus dem gueltigen Cache
        # beantwortet (mit {}), sonst loeste jede Abfrage fuer einen Tag
        # ohne Daten einen neuen Abruf aus.
        if self._is_cache_valid():
            by_date = self._cache.get('by_date', {})
            logger.debug(f"Using cached forecast.solar data for {target_date}")
            return by_date.get(str(target_date), {})

        # Nach einem Fehlschlag (v.a. HTTP 429) erst wieder anfragen, wenn
        # die Sperrzeit abgelaufen ist.
        if self._retry_not_before and datetime.now() < self._retry_not_before:
            wait = int((self._retry_not_before - datetime.now()).total_seconds())
            logger.debug(f"Forecast.Solar gesperrt, naechster Versuch in {wait}s")
            return {}

        # Gleiche Geometrie zusammenfassen - halbiert hier die Abrufe
        planes = self.merge_planes(planes)

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
                    if response.status_code == 429:
                        self._apply_rate_limit_backoff(response)
                        # Weitere Ebenen wuerden ebenfalls abgelehnt
                        return {}
                    logger.error(f"Forecast.Solar API error: HTTP {response.status_code}")
                    logger.error(f"Response: {response.text[:300]}")
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

            if by_date:
                # Zeitstempel setzen, NICHT self._cache ersetzen - sonst
                # ginge die Tagesaufteilung verloren und die Prognose fuer
                # morgen wuerde bei jedem Aufruf neu abgerufen.
                self._cache['by_date'] = by_date
                self._cache_timestamp = datetime.now()
                self._retry_not_before = None
                logger.info(f"✓ Forecast.Solar: {sum(len(v) for v in by_date.values())} Stundenwerte "
                            f"fuer {len(by_date)} Tage abgerufen "
                            f"({len(planes)} Abruf(e))")
            else:
                # Erfolgreich angefragt, aber nichts Brauchbares erhalten.
                # Kurze Sperre, damit der 30s-Regeltakt nicht hammert.
                self._retry_not_before = datetime.now() + timedelta(minutes=10)
                logger.warning("Forecast.Solar lieferte keine verwertbaren Daten - "
                               "naechster Versuch in 10 Minuten")

            hourly_forecast = by_date.get(str(target_date), {})
            if not hourly_forecast:
                logger.warning(f"Keine Stundenprognose fuer {target_date} verfuegbar")

            return hourly_forecast

        except requests.RequestException as e:
            # Netzwerkfehler ebenfalls sperren, sonst laeuft der Regeltakt
            # bei getrennter Verbindung in eine Abruf-Schleife.
            self._retry_not_before = datetime.now() + timedelta(minutes=10)
            logger.error(f"Netzwerkfehler bei Forecast.Solar: {e} - "
                         f"naechster Versuch in 10 Minuten")
            return {}
        except Exception as e:
            logger.error(f"Error getting hourly forecast from Forecast.Solar: {e}", exc_info=True)
            return {}

    def _apply_rate_limit_backoff(self, response):
        """
        Wertet ein HTTP 429 aus und setzt die Sperrzeit.

        forecast.solar nennt in der Antwort ein "retry-at" - danach richten
        wir uns, sonst 30 Minuten pauschal.
        """
        retry_at = None
        try:
            info = response.json().get('message', {}).get('ratelimit', {})
            limit = info.get('limit')
            period = info.get('period')
            if info.get('retry-at'):
                retry_at = datetime.fromisoformat(info['retry-at']).replace(tzinfo=None)
            logger.error(f"Forecast.Solar Ratelimit erreicht "
                         f"({limit} Abrufe pro {period}s). Naechster Versuch: "
                         f"{retry_at or 'in 30 Minuten'}")
        except Exception:
            logger.error("Forecast.Solar Ratelimit erreicht (HTTP 429)")

        self._retry_not_before = retry_at or (datetime.now() + timedelta(minutes=30))

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self._cache_timestamp or 'by_date' not in self._cache:
            return False

        age = datetime.now() - self._cache_timestamp
        return age < self._cache_duration

    def clear_cache(self):
        """Clear cached forecast data"""
        self._cache = {}
        self._cache_timestamp = None
        logger.debug("Forecast.Solar cache cleared")
