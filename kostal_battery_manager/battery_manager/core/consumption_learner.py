#!/usr/bin/env python3
"""
Consumption Learning System
Learns household consumption patterns over time
"""

import logging
import sqlite3
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ConsumptionLearner:
    """Learns and predicts household consumption patterns"""

    def __init__(self, db_path: str, learning_days: int = 28,
                 default_fallback: float = 1.0):
        """
        Initialize consumption learner

        Args:
            db_path: Path to SQLite database
            learning_days: Number of days to keep in history (default 28 = 4 weeks)
            default_fallback: Default hourly consumption if no data available (kWh)
        """
        self.db_path = db_path
        self.learning_days = learning_days
        self.default_fallback = default_fallback
        # Wann zuletzt fuer eine Stunde auf den Standardwert zurueckgefallen
        # wurde. Ohne Begrenzung schreibt eine leere Datenbank 72 Warnungen
        # pro Diagrammabruf - 24 Stunden mal heute, morgen und Profil - und
        # begraebt damit jede echte Meldung.
        self._fallback_gemeldet = {}
        self._init_database()
        logger.info(f"Consumption Learner initialized (learning period: {learning_days} days, "
                   f"fallback: {default_fallback} kWh/h)")

    def _init_database(self):
        """Initialize SQLite database with schema"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hourly_consumption (
                    timestamp TEXT PRIMARY KEY,
                    hour INTEGER NOT NULL,
                    consumption_kwh REAL NOT NULL,
                    is_manual BOOLEAN DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hour
                ON hourly_consumption(hour)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON hourly_consumption(timestamp DESC)
            """)

            conn.commit()
            logger.info("Database initialized successfully")

    def add_manual_profile(self, profile: Dict[str, float]):
        """
        Add manual load profile as baseline (initial 4 weeks)

        Args:
            profile: Dict with hour (0-23) as key and consumption in kW as value
                Example: {"0": 0.2, "1": 0.2, "7": 2.0, ...}
        """
        logger.info("Adding manual load profile as baseline...")

        with sqlite3.connect(self.db_path) as conn:
            # Generate 28 days of baseline data
            now = datetime.now()
            start_date = now - timedelta(days=self.learning_days)

            count = 0
            for day in range(self.learning_days):
                date = start_date + timedelta(days=day)

                for hour in range(24):
                    hour_str = str(hour)
                    if hour_str not in profile:
                        logger.warning(f"Hour {hour} missing in manual profile, using 0.2 kW")
                        consumption = 0.2
                    else:
                        consumption = float(profile[hour_str])

                    timestamp = date.replace(hour=hour, minute=0, second=0, microsecond=0)

                    conn.execute("""
                        INSERT OR REPLACE INTO hourly_consumption
                        (timestamp, hour, consumption_kwh, is_manual, created_at)
                        VALUES (?, ?, ?, 1, ?)
                    """, (
                        timestamp.isoformat(),
                        hour,
                        consumption,
                        datetime.now().isoformat()
                    ))
                    count += 1

            conn.commit()
            logger.info(f"Added {count} hours of manual baseline data")

    def import_detailed_history(self, daily_data: List[Dict]):
        """
        Import detailed historical data with individual daily profiles

        Args:
            daily_data: List of daily profiles, each containing:
                {
                    'date': 'YYYY-MM-DD' or datetime object,
                    'weekday': 'Montag'|'Dienstag'|...|'Sonntag' (optional),
                    'hours': [h0, h1, h2, ..., h23]  # 24 hourly consumption values in kWh
                }

        Example:
            [
                {
                    'date': '2024-10-07',
                    'weekday': 'Montag',
                    'hours': [0.2, 0.2, 0.15, ..., 0.3]  # 24 values
                },
                ...
            ]
        """
        logger.info(f"Importing detailed historical data for {len(daily_data)} days...")

        if len(daily_data) > self.learning_days:
            logger.warning(f"Provided {len(daily_data)} days but learning period is {self.learning_days} days. "
                          f"Only the most recent {self.learning_days} days will be kept.")

        imported_count = 0
        skipped_count = 0

        with sqlite3.connect(self.db_path) as conn:
            for day_entry in daily_data:
                try:
                    # Parse date
                    if isinstance(day_entry['date'], str):
                        date = datetime.fromisoformat(day_entry['date'])
                    else:
                        date = day_entry['date']

                    hours = day_entry['hours']

                    # Validate: must have exactly 24 values
                    if len(hours) != 24:
                        logger.error(f"Invalid data for {date.strftime('%Y-%m-%d')}: "
                                    f"Expected 24 hourly values, got {len(hours)}. Skipping.")
                        skipped_count += 1
                        continue

                    # Import each hour
                    for hour in range(24):
                        consumption = float(hours[hour])

                        # Validate value
                        if consumption < 0:
                            logger.warning(f"Negative value {consumption} kWh at {date.strftime('%Y-%m-%d')} hour {hour}, using 0")
                            consumption = 0
                        elif consumption > 50:
                            logger.warning(f"Unrealistic value {consumption} kWh at {date.strftime('%Y-%m-%d')} hour {hour}, capping at 50")
                            consumption = 50

                        timestamp = date.replace(hour=hour, minute=0, second=0, microsecond=0)

                        conn.execute("""
                            INSERT OR REPLACE INTO hourly_consumption
                            (timestamp, hour, consumption_kwh, is_manual, created_at)
                            VALUES (?, ?, ?, 1, ?)
                        """, (
                            timestamp.isoformat(),
                            hour,
                            consumption,
                            datetime.now().isoformat()
                        ))
                        imported_count += 1

                except Exception as e:
                    logger.error(f"Error importing day {day_entry.get('date', 'unknown')}: {e}")
                    skipped_count += 1
                    continue

            conn.commit()

        logger.info(f"Import complete: {imported_count} hourly records imported, {skipped_count} days skipped")

        # Clean up old data
        self._cleanup_old_data()

        return {
            'imported_hours': imported_count,
            'skipped_days': skipped_count,
            'success': skipped_count == 0
        }

    def import_from_csv(self, csv_content: str) -> Dict:
        """
        Import consumption data from CSV string

        CSV Format:
            datum,wochentag,h0,h1,h2,h3,...,h23
            2024-10-07,Montag,0.2,0.2,0.15,0.15,...,0.3
            2024-10-08,Dienstag,0.18,0.19,0.14,0.13,...,0.35

        Args:
            csv_content: CSV content as string

        Returns:
            Dict with import results
        """
        try:
            logger.info("Parsing CSV data...")

            # Parse CSV
            csv_file = io.StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            daily_data = []

            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is 1)
                try:
                    # Extract date and weekday
                    date_str = row.get('datum', '').strip()
                    weekday = row.get('wochentag', '').strip()

                    if not date_str:
                        logger.warning(f"Row {row_num}: Missing date, skipping")
                        continue

                    # Parse date
                    try:
                        date = datetime.strptime(date_str, '%Y-%m-%d')
                    except ValueError:
                        try:
                            # Try alternative format
                            date = datetime.strptime(date_str, '%d.%m.%Y')
                        except ValueError:
                            logger.error(f"Row {row_num}: Invalid date format '{date_str}', expected YYYY-MM-DD or DD.MM.YYYY")
                            continue

                    # Extract hourly values (h0 to h23)
                    hours = []
                    for h in range(24):
                        col_name = f'h{h}'
                        if col_name not in row:
                            logger.error(f"Row {row_num}: Missing column '{col_name}'")
                            break

                        try:
                            value = row[col_name].strip()
                            # Replace comma with dot for German number format
                            value = value.replace(',', '.')
                            hours.append(float(value))
                        except ValueError:
                            logger.error(f"Row {row_num}: Invalid number in column '{col_name}': '{row[col_name]}'")
                            break

                    # Check if we have all 24 hours
                    if len(hours) != 24:
                        logger.error(f"Row {row_num}: Incomplete hourly data (got {len(hours)} values)")
                        continue

                    daily_data.append({
                        'date': date,
                        'weekday': weekday,
                        'hours': hours
                    })

                except Exception as e:
                    logger.error(f"Row {row_num}: Error parsing row: {e}")
                    continue

            if not daily_data:
                return {
                    'success': False,
                    'error': 'No valid data found in CSV',
                    'imported_hours': 0,
                    'imported_days': 0,
                    'skipped_days': 0
                }

            logger.info(f"Successfully parsed {len(daily_data)} days from CSV")

            # Import the parsed data
            result = self.import_detailed_history(daily_data)
            result['imported_days'] = len(daily_data)
            return result

        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            return {
                'success': False,
                'error': str(e),
                'imported_hours': 0,
                'imported_days': 0,
                'skipped_days': 0
            }

    def import_from_home_assistant(self, ha_client, entity_id: str, days: int = 28) -> Dict:
        """
        Import consumption data from Home Assistant history (v0.6.0)

        Args:
            ha_client: HomeAssistantClient instance
            entity_id: Entity ID to import (e.g., 'sensor.ksem_home_consumption')
            days: Number of days to import (default 28)

        Returns:
            Dict with import results
        """
        try:
            logger.info(f"Starting HA history import for entity '{entity_id}', last {days} days...")

            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            logger.info(f"Time range: {start_time.isoformat()} to {end_time.isoformat()}")

            # Get history data from HA
            history = ha_client.get_history(entity_id, start_time, end_time)

            if not history:
                logger.error(f"No history data received from HA for entity '{entity_id}'")
                return {
                    'success': False,
                    'error': f'No history data received from Home Assistant for entity {entity_id}',
                    'imported_hours': 0,
                    'imported_days': 0,
                    'skipped_days': 0,
                    'history_entries': 0
                }

            logger.info(f"Received {len(history)} history entries from HA")

            # Group data by date and hour
            hourly_data = {}  # Key: (date, hour), Value: list of values

            # Counters for debugging
            skipped_no_timestamp = 0
            skipped_unavailable = 0
            skipped_not_numeric = 0
            skipped_negative = 0
            skipped_too_high = 0
            valid_entries = 0

            for entry in history:
                try:
                    # Parse timestamp
                    timestamp_str = entry.get('last_changed') or entry.get('last_updated')
                    if not timestamp_str:
                        skipped_no_timestamp += 1
                        continue

                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    # Convert to local timezone to get correct date/hour
                    local_timestamp = timestamp.astimezone()

                    # Parse state value
                    state = entry.get('state')
                    if state in ['unknown', 'unavailable', None]:
                        skipped_unavailable += 1
                        continue

                    try:
                        value = float(state)
                    except (ValueError, TypeError):
                        skipped_not_numeric += 1
                        continue

                    # Skip negative values
                    if value < 0:
                        skipped_negative += 1
                        continue

                    # Skip unrealistic values (> 50000 W = 50 kW)
                    if value > 50000:
                        skipped_too_high += 1
                        continue

                    # Convert Watt to kWh if needed (values > 50 are likely Watt)
                    # Typical home consumption: 0.1-10 kWh/h, or 100-10000 W
                    if value > 50:
                        value = value / 1000  # Convert W to kW

                    # Group by date and hour (using local timezone)
                    date_key = local_timestamp.date()
                    hour_key = local_timestamp.hour
                    key = (date_key, hour_key)

                    if key not in hourly_data:
                        hourly_data[key] = []

                    hourly_data[key].append(value)
                    valid_entries += 1

                except Exception as e:
                    logger.debug(f"Skipping invalid history entry: {e}")
                    continue

            logger.info(f"Processing summary: {valid_entries} valid, "
                       f"{skipped_unavailable} unavailable, {skipped_not_numeric} non-numeric, "
                       f"{skipped_negative} negative, {skipped_too_high} too high, "
                       f"{skipped_no_timestamp} no timestamp")

            if not hourly_data:
                logger.error("No valid hourly data after filtering")
                return {
                    'success': False,
                    'error': 'No valid data points found in history after filtering',
                    'imported_hours': 0,
                    'imported_days': 0,
                    'skipped_days': 0,
                    'history_entries': len(history)
                }

            logger.info(f"Grouped into {len(hourly_data)} hour buckets from {len(history)} entries")

            # Calculate average for each hour and group by day
            daily_data_dict = {}  # Key: date, Value: dict with hours

            for (date_key, hour_key), values in hourly_data.items():
                # Calculate average consumption for this hour
                avg_consumption = sum(values) / len(values)

                if date_key not in daily_data_dict:
                    daily_data_dict[date_key] = {}

                daily_data_dict[date_key][hour_key] = avg_consumption

            logger.info(f"Found data for {len(daily_data_dict)} unique days")

            # Log hours per day for debugging
            for date_key in sorted(daily_data_dict.keys()):
                hours_dict = daily_data_dict[date_key]
                logger.info(f"  {date_key}: {len(hours_dict)} hours (hours: {sorted(hours_dict.keys())})")

            # Convert to format for import_detailed_history
            daily_data = []
            skipped_days = 0
            weekdays_de = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

            for date_key in sorted(daily_data_dict.keys()):
                hours_dict = daily_data_dict[date_key]

                # Build 24-hour array (fill missing hours with average or skip incomplete days)
                # Lowered threshold to 3 hours minimum (was 12) to handle sparse history data
                if len(hours_dict) < 3:  # Skip days with too little data
                    logger.warning(f"Skipping {date_key}: only {len(hours_dict)} hours of data (need >= 3)")
                    skipped_days += 1
                    continue

                hours = []
                for h in range(24):
                    if h in hours_dict:
                        hours.append(hours_dict[h])
                    else:
                        # Use average of available data for missing hours
                        if hours_dict:
                            hours.append(sum(hours_dict.values()) / len(hours_dict))
                        else:
                            hours.append(0)

                # Get weekday
                weekday_idx = date_key.weekday()
                weekday = weekdays_de[weekday_idx]

                daily_data.append({
                    'date': date_key.isoformat(),
                    'weekday': weekday,
                    'hours': hours
                })

            if not daily_data:
                logger.error(f"No complete days found. Checked {len(daily_data_dict)} days, all had < 3 hours of data")
                return {
                    'success': False,
                    'error': f'No complete days found in history data. Checked {len(daily_data_dict)} days, all had less than 3 hours of data. Check if sensor {entity_id} is logging data correctly.',
                    'imported_hours': 0,
                    'imported_days': 0,
                    'skipped_days': len(daily_data_dict),
                    'history_entries': len(history)
                }

            logger.info(f"Prepared {len(daily_data)} days for import (skipped {skipped_days} incomplete days)")

            # Import the data
            result = self.import_detailed_history(daily_data)
            # Add additional info
            result['history_entries'] = len(history)
            result['imported_days'] = len(daily_data)
            return result

        except Exception as e:
            logger.error(f"Error importing from Home Assistant: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'imported_hours': 0,
                'imported_days': 0,
                'skipped_days': 0
            }

    def record_consumption(self, timestamp: datetime, consumption_kwh: float):
        """
        Record actual consumption for learning

        Args:
            timestamp: Timestamp of consumption
            consumption_kwh: Consumption in kWh for that hour
        """
        # Validate: negative values indicate sensor/metering errors
        if consumption_kwh < 0:
            logger.warning(f"Negative consumption value detected: {consumption_kwh} kWh at {timestamp.strftime('%Y-%m-%d %H:%M')} - "
                          f"Skipping (likely Kostal Smart Meter bug)")
            return

        # Validate: unrealistic high values (> 100 kWh/h suggests wrong sensor type)
        if consumption_kwh > 100:
            logger.error(f"⚠️ CONFIGURATION ERROR: Sensor value {consumption_kwh} kWh is too high! "
                        f"You likely configured a cumulative TOTAL energy sensor (Gesamtverbrauch) "
                        f"instead of a POWER or hourly ENERGY sensor. "
                        f"Please use a sensor that measures instantaneous power (W) or energy per time period (kWh/h), "
                        f"NOT a cumulative total counter.")
            return

        # Validate: high but possible values (50-100 kWh/h)
        if consumption_kwh > 50:
            logger.warning(f"Very high consumption value: {consumption_kwh} kWh at {timestamp.strftime('%Y-%m-%d %H:%M')} - "
                          f"Recording but please verify your sensor configuration is correct")
            # Continue recording despite warning

        hour = timestamp.hour

        # Round timestamp to full hour to match imported data format
        # This ensures automatic learning overwrites averaged values from imports
        rounded_timestamp = timestamp.replace(minute=0, second=0, microsecond=0)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hourly_consumption
                (timestamp, hour, consumption_kwh, is_manual, created_at)
                VALUES (?, ?, ?, 0, ?)
            """, (
                rounded_timestamp.isoformat(),
                hour,
                consumption_kwh,
                datetime.now().isoformat()
            ))
            conn.commit()

        logger.debug(f"Recorded consumption: {consumption_kwh:.2f} kWh at hour {hour}")

        # Clean up old data
        self._cleanup_old_data()

    def _cleanup_old_data(self):
        """Remove data older than learning period"""
        cutoff = datetime.now() - timedelta(days=self.learning_days)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM hourly_consumption
                WHERE timestamp < ?
            """, (cutoff.isoformat(),))
            conn.commit()

    def cleanup_duplicates(self):
        """
        Remove duplicate entries for the same date+hour combination.
        Keeps the best entry: prefer learned (is_manual=0) over imported (is_manual=1),
        and latest created_at as tiebreaker.
        """
        with sqlite3.connect(self.db_path) as conn:
            # Find and delete duplicates, keeping only the best entry per date+hour
            cursor = conn.execute("""
                DELETE FROM hourly_consumption
                WHERE rowid NOT IN (
                    SELECT rowid
                    FROM (
                        SELECT rowid,
                               ROW_NUMBER() OVER (
                                   PARTITION BY DATE(timestamp), hour
                                   ORDER BY is_manual ASC, created_at DESC, timestamp DESC
                               ) as rn
                        FROM hourly_consumption
                    )
                    WHERE rn = 1
                )
            """)
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} duplicate entries")

            return deleted

    def clear_all_manual_data(self):
        """Clear all manually imported data (keeps automatically learned data)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM hourly_consumption WHERE is_manual = 1")
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleared {deleted} manually imported records")
            return deleted

    def clear_all_data(self):
        """Clear ALL consumption data (manual AND learned)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM hourly_consumption")
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleared ALL {deleted} consumption records")
            return deleted

    def _stundenmittel(self, conn, hour: int, weekday=None,
                       nur_gemessen: bool = False) -> Optional[float]:
        """
        Mittelwert einer Stunde, wahlweise auf Wochentag und Quelle
        eingeschraenkt.

        ROW_NUMBER entfernt Doubletten innerhalb derselben Stunde desselben
        Tages; bei gleichem Zeitpunkt gewinnt der gelernte vor dem
        importierten Wert.
        """
        bedingungen = ['hour = ?']
        params = [hour]
        if weekday is not None:
            bedingungen.append("strftime('%w', timestamp) = ?")
            params.append(weekday)
        if nur_gemessen:
            bedingungen.append('is_manual = 0')

        sql = f"""
            SELECT AVG(consumption_kwh) FROM (
                SELECT consumption_kwh,
                       ROW_NUMBER() OVER (
                           PARTITION BY DATE(timestamp), hour
                           ORDER BY is_manual ASC, created_at DESC
                       ) AS rn
                FROM hourly_consumption
                WHERE {' AND '.join(bedingungen)}
            ) WHERE rn = 1
        """
        row = conn.execute(sql, params).fetchone()
        return float(row[0]) if row and row[0] else None

    def get_average_consumption(self, hour: int, target_date=None) -> float:
        """
        Durchschnittsverbrauch einer Stunde in kWh.

        Die Quellen werden in dieser Reihenfolge probiert:

          1. gemessen, gleicher Wochentag
          2. gemessen, irgendein Tag
          3. importiert, gleicher Wochentag
          4. importiert, irgendein Tag
          5. Standardwert

        Entscheidend ist, dass die QUELLE vor dem WOCHENTAG kommt. Wer
        gerade erst anfaengt zu lernen, hat Messwerte fuer ein oder zwei
        Tage - also fuer ein oder zwei Wochentage. Filtert man zuerst nach
        Wochentag, bleiben fuer fast jede Stunde nur importierte Werte
        uebrig, und die Kurve bleibt brettflach beim Importwert, obwohl
        laengst echte Messungen vorliegen.

        Args:
            hour: Stunde 0-23
            target_date: Datum, dessen Wochentag bevorzugt wird.
                         None = ohne Wochentagsbevorzugung.
        """
        from datetime import datetime as _dt

        weekday = None
        if target_date is not None:
            if isinstance(target_date, _dt):
                target_date = target_date.date()
            weekday = target_date.strftime('%w')

        with sqlite3.connect(self.db_path) as conn:
            versuche = [
                (weekday, True),    # gemessen, gleicher Wochentag
                (None, True),       # gemessen, irgendein Tag
                (weekday, False),   # beliebige Quelle, gleicher Wochentag
                (None, False),      # beliebige Quelle, irgendein Tag
            ]
            for wd, nur_gemessen in versuche:
                wert = self._stundenmittel(conn, hour, wd, nur_gemessen)
                if wert is not None:
                    return wert

        self._melde_fallback(hour)
        return self.default_fallback

    def _melde_fallback(self, hour: int):
        """Meldet den Rueckfall auf den Standardwert, hoechstens alle 10 Minuten je Stunde."""
        import time as _time
        jetzt = _time.monotonic()
        zuletzt = self._fallback_gemeldet.get(hour)
        if zuletzt is not None and jetzt - zuletzt < 600:
            return
        self._fallback_gemeldet[hour] = jetzt
        logger.warning(f"Keine Verbrauchsdaten fuer Stunde {hour} - "
                       f"nutze Standardwert {self.default_fallback:.2f} kWh")

    def get_sample_count(self, hour: int) -> int:
        """Anzahl vorhandener Messwerte fuer eine Stunde (ueber alle Tage)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(DISTINCT DATE(timestamp)) FROM hourly_consumption WHERE hour = ?",
                    (hour,))
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] else 0
        except Exception as e:
            logger.debug(f"Konnte Stichprobenanzahl fuer Stunde {hour} nicht ermitteln: {e}")
            return 0

    def get_hourly_profile(self, target_date=None) -> Dict[int, float]:
        """
        Vollstaendiges 24-Stunden-Profil in kWh.

        Bewusst Stunde fuer Stunde ueber get_average_consumption, statt mit
        einer eigenen Abfrage: Sonst haben Profil und Einzelwert
        unterschiedliche Regeln, und genau das war schon einmal die
        Ursache eines Fehlers - der Einzelwert bekam die Rueckfallkette,
        das Profil fuellte Luecken weiter mit einem flachen Tagesmittel.

        Args:
            target_date: Datum, dessen Wochentag bevorzugt wird.
        """
        return {hour: self.get_average_consumption(hour, target_date)
                for hour in range(24)}

    def predict_consumption_until(self, target_hour: int, start_datetime=None) -> float:
        """
        Predict total consumption from now (or start_datetime) until target hour

        Args:
            target_hour: Target hour (0-23)
            start_datetime: Optional start datetime. If None, uses now()

        Returns:
            Predicted total consumption in kWh
        """
        from datetime import datetime, timedelta

        if start_datetime is None:
            start_datetime = datetime.now().astimezone()

        current_hour = start_datetime.hour
        current_minute = start_datetime.minute
        current_date = start_datetime.date()

        total = 0.0

        # Partial current hour (remaining minutes)
        remaining_fraction = (60 - current_minute) / 60
        total += self.get_average_consumption(current_hour, target_date=current_date) * remaining_fraction

        # Full hours until target
        # Track current position with datetime to handle day transitions
        position = start_datetime + timedelta(hours=1)
        position = position.replace(minute=0, second=0, microsecond=0)

        while position.hour != target_hour:
            hour = position.hour
            date = position.date()
            total += self.get_average_consumption(hour, target_date=date)
            position += timedelta(hours=1)

        return total

    def get_statistics(self) -> Dict:
        """Get statistics about learned data"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_records,
                    SUM(CASE WHEN is_manual = 1 THEN 1 ELSE 0 END) as manual_records,
                    SUM(CASE WHEN is_manual = 0 THEN 1 ELSE 0 END) as learned_records,
                    MIN(timestamp) as oldest_record,
                    MAX(timestamp) as newest_record
                FROM hourly_consumption
            """)

            row = cursor.fetchone()

            # Abdeckung: fuer wie viele der 24 Stunden liegen ueberhaupt
            # Daten vor, und ueber wie viele Tage?
            cov = conn.execute("""
                SELECT COUNT(DISTINCT hour), COUNT(DISTINCT DATE(timestamp))
                FROM hourly_consumption
            """).fetchone()
            hours_covered = int(cov[0]) if cov and cov[0] else 0
            days_covered = int(cov[1]) if cov and cov[1] else 0

            if row:
                # Der Lernfortschritt misst die ABDECKUNG des Lernzeitraums,
                # nicht den Anteil live erfasster Datensaetze. Frueher stand
                # hier learned/total - das zeigte bei frisch importierter
                # Historie 2%, obwohl alle 24 Stunden belegt waren, und war
                # damit schlicht irrefuehrend.
                progress = round(min(100.0, days_covered / self.learning_days * 100), 1) \
                    if self.learning_days else 0.0
                return {
                    'total_records': row[0],
                    'manual_records': row[1],
                    'learned_records': row[2],
                    'oldest_record': row[3],
                    'newest_record': row[4],
                    'hours_covered': hours_covered,
                    'days_covered': days_covered,
                    'learning_days': self.learning_days,
                    'learning_progress': progress,
                }

        return {
            'total_records': 0,
            'manual_records': 0,
            'learned_records': 0,
            'oldest_record': None,
            'newest_record': None,
            'hours_covered': 0,
            'days_covered': 0,
            'learning_days': self.learning_days,
            'learning_progress': 0.0
        }

    def get_today_consumption(self, date=None) -> Dict[int, float]:
        """
        Get actual recorded consumption values for a specific date (default: today)

        Args:
            date: Date to get consumption for (datetime.date object), defaults to today

        Returns:
            Dict with hour (0-23) as key and actual consumption in kWh as value
            Only includes hours that have been recorded
        """
        from datetime import date as date_type, datetime

        if date is None:
            date = datetime.now().date()
        elif isinstance(date, datetime):
            date = date.date()

        date_str = date.isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT hour, consumption_kwh
                FROM hourly_consumption
                WHERE DATE(timestamp) = ?
                ORDER BY created_at DESC
            """, (date_str,))

            # Build dict with most recent value per hour
            hourly_consumption = {}
            for row in cursor.fetchall():
                hour = row[0]
                consumption = row[1]
                # Only store if we haven't seen this hour yet (ORDER BY DESC means first is newest)
                if hour not in hourly_consumption:
                    hourly_consumption[hour] = consumption

            return hourly_consumption

