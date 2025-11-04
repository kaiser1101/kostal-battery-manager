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
                    'skipped_days': 0
                }

            logger.info(f"Successfully parsed {len(daily_data)} days from CSV")

            # Import the parsed data
            return self.import_detailed_history(daily_data)

        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            return {
                'success': False,
                'error': str(e),
                'imported_hours': 0,
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
            logger.info(f"Starting HA history import for {entity_id}, last {days} days...")

            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)

            # Get history data from HA
            history = ha_client.get_history(entity_id, start_time, end_time)

            if not history:
                return {
                    'success': False,
                    'error': 'No history data received from Home Assistant',
                    'imported_hours': 0,
                    'skipped_days': 0
                }

            logger.info(f"Received {len(history)} data points from HA")

            # Group data by date and hour
            hourly_data = {}  # Key: (date, hour), Value: list of values

            for entry in history:
                try:
                    # Parse timestamp
                    timestamp_str = entry.get('last_changed') or entry.get('last_updated')
                    if not timestamp_str:
                        continue

                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                    # Parse state value
                    state = entry.get('state')
                    if state in ['unknown', 'unavailable', None]:
                        continue

                    try:
                        value = float(state)
                    except (ValueError, TypeError):
                        continue

                    # Skip negative and unrealistic values
                    if value < 0 or value > 50:
                        continue

                    # Group by date and hour
                    date_key = timestamp.date()
                    hour_key = timestamp.hour
                    key = (date_key, hour_key)

                    if key not in hourly_data:
                        hourly_data[key] = []

                    hourly_data[key].append(value)

                except Exception as e:
                    logger.debug(f"Skipping invalid history entry: {e}")
                    continue

            if not hourly_data:
                return {
                    'success': False,
                    'error': 'No valid data points found in history',
                    'imported_hours': 0,
                    'skipped_days': 0
                }

            logger.info(f"Grouped into {len(hourly_data)} hour buckets")

            # Calculate average for each hour and group by day
            daily_data_dict = {}  # Key: date, Value: dict with hours

            for (date_key, hour_key), values in hourly_data.items():
                # Calculate average consumption for this hour
                avg_consumption = sum(values) / len(values)

                if date_key not in daily_data_dict:
                    daily_data_dict[date_key] = {}

                daily_data_dict[date_key][hour_key] = avg_consumption

            # Convert to format for import_detailed_history
            daily_data = []
            weekdays_de = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

            for date_key in sorted(daily_data_dict.keys()):
                hours_dict = daily_data_dict[date_key]

                # Build 24-hour array (fill missing hours with 0 or skip incomplete days)
                if len(hours_dict) < 12:  # Skip days with too little data
                    logger.warning(f"Skipping {date_key}: only {len(hours_dict)} hours of data")
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
                return {
                    'success': False,
                    'error': 'No complete days found in history data',
                    'imported_hours': 0,
                    'skipped_days': 0
                }

            logger.info(f"Prepared {len(daily_data)} days for import")

            # Import the data
            return self.import_detailed_history(daily_data)

        except Exception as e:
            logger.error(f"Error importing from Home Assistant: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'imported_hours': 0,
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

        # Validate: unrealistic high values (> 50 kWh/h suggests error)
        if consumption_kwh > 50:
            logger.warning(f"Unrealistically high consumption value: {consumption_kwh} kWh at {timestamp.strftime('%Y-%m-%d %H:%M')} - "
                          f"Skipping (likely sensor error)")
            return

        hour = timestamp.hour

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hourly_consumption
                (timestamp, hour, consumption_kwh, is_manual, created_at)
                VALUES (?, ?, ?, 0, ?)
            """, (
                timestamp.isoformat(),
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

    def get_average_consumption(self, hour: int) -> float:
        """
        Get average consumption for a specific hour

        Args:
            hour: Hour of day (0-23)

        Returns:
            Average consumption in kWh for that hour
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT AVG(consumption_kwh) as avg_consumption
                FROM hourly_consumption
                WHERE hour = ?
            """, (hour,))

            result = cursor.fetchone()
            if result and result[0]:
                return float(result[0])

            logger.warning(f"No data for hour {hour}, using default {self.default_fallback} kWh")
            return self.default_fallback

    def get_hourly_profile(self) -> Dict[int, float]:
        """
        Get complete 24-hour average consumption profile

        Returns:
            Dict with hour (0-23) as key and average consumption in kWh as value
        """
        profile = {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT hour, AVG(consumption_kwh) as avg_consumption
                FROM hourly_consumption
                GROUP BY hour
                ORDER BY hour
            """)

            for row in cursor:
                profile[row[0]] = float(row[1])

        # Fill missing hours with default
        for hour in range(24):
            if hour not in profile:
                profile[hour] = 0.5

        return profile

    def predict_consumption_until(self, target_hour: int) -> float:
        """
        Predict total consumption from now until target hour

        Args:
            target_hour: Target hour (0-23)

        Returns:
            Predicted total consumption in kWh
        """
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        total = 0.0

        # Partial current hour (remaining minutes)
        remaining_fraction = (60 - current_minute) / 60
        total += self.get_average_consumption(current_hour) * remaining_fraction

        # Full hours until target
        hour = (current_hour + 1) % 24
        while hour != target_hour:
            total += self.get_average_consumption(hour)
            hour = (hour + 1) % 24

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

            if row:
                return {
                    'total_records': row[0],
                    'manual_records': row[1],
                    'learned_records': row[2],
                    'oldest_record': row[3],
                    'newest_record': row[4],
                    'learning_progress': round((row[2] / row[0] * 100) if row[0] > 0 else 0, 1)
                }

        return {
            'total_records': 0,
            'manual_records': 0,
            'learned_records': 0,
            'oldest_record': None,
            'newest_record': None,
            'learning_progress': 0.0
        }
