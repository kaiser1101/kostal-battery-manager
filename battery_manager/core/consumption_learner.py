#!/usr/bin/env python3
"""
Consumption Learning System
Learns household consumption patterns over time
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ConsumptionLearner:
    """Learns and predicts household consumption patterns"""

    def __init__(self, db_path: str, learning_days: int = 28):
        """
        Initialize consumption learner

        Args:
            db_path: Path to SQLite database
            learning_days: Number of days to keep in history (default 28 = 4 weeks)
        """
        self.db_path = db_path
        self.learning_days = learning_days
        self._init_database()
        logger.info(f"Consumption Learner initialized (learning period: {learning_days} days)")

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

    def record_consumption(self, timestamp: datetime, consumption_kwh: float):
        """
        Record actual consumption for learning

        Args:
            timestamp: Timestamp of consumption
            consumption_kwh: Consumption in kWh for that hour
        """
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

            logger.warning(f"No data for hour {hour}, using default 0.5 kWh")
            return 0.5  # Default fallback

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
