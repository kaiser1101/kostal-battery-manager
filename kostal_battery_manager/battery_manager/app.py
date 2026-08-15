#!/usr/bin/env python3
"""
Kostal Battery Manager - Main Flask Application - FIXED VERSION
"""

import os
import json
import logging
import threading
import time
import atexit
import signal
from datetime import datetime
from flask import Flask, render_template, jsonify, request, redirect, url_for, make_response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Setup logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app with correct paths
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')

# Configure for Home Assistant Ingress support
# This ensures url_for() generates correct URLs with the Ingress prefix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Enable CORS for Ingress
CORS(app)

# Context processor to inject base_path into all templates
# IMPORTANT: This runs BEFORE template rendering, so we detect Ingress here
@app.context_processor
def inject_base_path():
    """Detect Ingress prefix and inject base_path into all templates"""
    # Home Assistant Ingress sends the prefix in X-Ingress-Path header
    # Example: X-Ingress-Path: /api/hassio_ingress/1ytBWj2lv6Xc0Uy7veOWxrVwNgRR09z7NsoXmLVe9tM
    base_path = request.environ.get('SCRIPT_NAME', '')

    if not base_path or base_path == '':
        # Check for Home Assistant Ingress header
        ingress_path = request.headers.get('X-Ingress-Path', '')
        if ingress_path:
            # Use the Ingress path as base_path
            base_path = ingress_path
            # Set SCRIPT_NAME so url_for() generates correct URLs
            request.environ['SCRIPT_NAME'] = base_path
            logger.debug(f"Ingress detected: {base_path}")

    return dict(base_path=base_path)

app.config['SECRET_KEY'] = os.urandom(24)
# Disable template caching to ensure changes are reflected immediately
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configuration
CONFIG_PATH = os.getenv('CONFIG_PATH', '/data/options.json')

class _SkipCycle(Exception):
    """Bricht den Planungsschritt ab, ohne als Fehler zu gelten."""


class _SkipTibber(Exception):
    """Signalisiert, dass Tibber-Abfragen in dieser Strategie entfallen."""


def load_config():
    """Load configuration from Home Assistant options"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                logger.info(f"Configuration loaded from {CONFIG_PATH}")
                return config
        else:
            logger.warning(f"Config file not found: {CONFIG_PATH}, using defaults")
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    
    # Default configuration
    return {
        'inverter_ip': '192.168.80.76',
        'inverter_port': 1502,
        'installer_password': '',
        'master_password': '',
        'max_charge_power': 3900,
        'battery_capacity': 10.6,
        'log_level': 'info',
        'control_interval': 30,
        'enable_tibber_optimization': True,
        'price_threshold': 0.85,
        'battery_soc_sensor': 'sensor.zwh8_8500_battery_soc',
        # v0.2.0 - Battery sensor options
        'battery_power_sensor': 'sensor.zwh8_8500_battery_power',
        'battery_voltage_sensor': '',
        'tibber_price_sensor': 'sensor.tibber_prices',
        'tibber_price_level_sensor': 'sensor.tibber_price_level_deutsch',
        'auto_optimization_enabled': True,
        # v0.2.5 - Automation Parameters
        'auto_pv_threshold': 5.0,
        'auto_charge_below_soc': 95,
        'auto_safety_soc': 20,
        # v0.2.1 - PV Production Sensors (Dual Roof)
        'pv_power_now_roof1': 'sensor.power_production_now_roof1',
        'pv_power_now_roof2': 'sensor.power_production_now_roof2',
        'pv_remaining_today_roof1': 'sensor.energy_production_today_remaining_roof1',
        'pv_remaining_today_roof2': 'sensor.energy_production_today_remaining_roof2',
        'pv_production_today_roof1': 'sensor.energy_production_today_roof1',
        'pv_production_today_roof2': 'sensor.energy_production_today_roof2',
        'pv_production_tomorrow_roof1': 'sensor.energy_production_tomorrow_roof1',
        'pv_production_tomorrow_roof2': 'sensor.energy_production_tomorrow_roof2',
        'pv_next_hour_roof1': 'sensor.energy_next_hour_roof1',
        'pv_next_hour_roof2': 'sensor.energy_next_hour_roof2',
        # v0.3.0 - Tibber Smart Charging
        'tibber_price_threshold_1h': 8,
        'tibber_price_threshold_3h': 8,
        'charge_duration_per_10_percent': 18,
        'input_datetime_planned_charge_end': 'input_datetime.tibber_geplantes_ladeende',
        'input_datetime_planned_charge_start': 'input_datetime.tibber_geplanter_ladebeginn',
        # v0.10.0 - Forecast-only "Evening Top-up" strategy (no price logic)
        'charging_strategy': 'forecast',    # 'price' (legacy/Tibber) or 'forecast' (PV-Shaping)
        'dry_run': True,                    # Sicherer Default: nichts schreiben
        'enable_charge_throttling': True,
        'min_charge_power': 500,
        'calibration_interval_days': 28,
        'calibration_min_pv_kwh': 15.0,
        'soc_corridor_min': 30,             # weiche Untergrenze, schonender Korridor
        'soc_corridor_max': 80,             # weiche Obergrenze, kein Vollladen
        'soc_hard_safety_min': 15,          # harte Notbremse, unabhängig vom Abend-Check
        'pv_forecast_safety_margin': 0.8,   # Sicherheitsmarge auf PV-Prognose
        'pv_dropoff_threshold': 0.05,       # Trigger: PV < 5% des Tagesmaximums
        'escalation_days': 2,               # nach X Tagen Korridor-Unterschreitung eskalieren
        'escalation_soc_boost': 15          # Ziel-SOC-Anhebung bei Eskalation
    }

# Load configuration
config = load_config()


_previous_sigterm_handler = None


def _shutdown_handler(signum, frame):
    """
    SIGTERM: Grenzen freigeben, dann an gunicorn weiterreichen.

    Wichtig: NICHT selbst SystemExit werfen. Gunicorn hat einen eigenen
    SIGTERM-Handler fuer das geordnete Beenden der Worker; wuerden wir ihn
    ersetzen, braeche das laufende Anfragen ab und produzierte einen
    Traceback im Log.
    """
    logger.info(f"Signal {signum} empfangen, gebe Grenzwerte frei...")
    try:
        release_limits_on_shutdown()
    except Exception as e:
        logger.error(f"Freigabe beim Beenden fehlgeschlagen: {e}")

    if callable(_previous_sigterm_handler):
        _previous_sigterm_handler(signum, frame)
    elif _previous_sigterm_handler == signal.SIG_DFL:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

# Global state
app_state = {
    'controller_running': True,  # v0.2.5 - Automation ON by default
    'last_update': None,
    'battery': {
        'soc': 0,
        'power': 0,
        'voltage': 0
    },
    'inverter': {
        'connected': False,
        'mode': 'automatic',
        'control_mode': 'internal'
    },
    'price': {
        'current': 0.0,
        'average': 0.0,
        'level': 'unknown'
    },
    'forecast': {
        'today': 0.0,
        'tomorrow': 0.0
    },
    'charging_plan': {
        'planned_start': None,
        'planned_end': None,
        'last_calculated': None
    },
    'daily_battery_schedule': None,  # v0.9.0 - Full-day predictive plan (price strategy)
    'shaping_plan': None,            # v0.10.0 - Aktueller PV-Shaping-Plan (Grenzwerte)
    'limits_readback': None,
    'hold_test': None,             # v0.11.0 - Haltetest der Leistungsregister         # v0.10.0 - Zurueckgelesene Limit-Register
    'logs': []
}

def add_log(level, message):
    """Add log entry to state"""
    timestamp = datetime.now().isoformat()
    app_state['logs'].append({
        'timestamp': timestamp,
        'level': level,
        'message': message
    })
    # Keep only last 100 logs
    if len(app_state['logs']) > 100:
        app_state['logs'] = app_state['logs'][-100:]
    
    # Also log to logger
    if level == 'ERROR':
        logger.error(message)
    elif level == 'WARNING':
        logger.warning(message)
    else:
        logger.info(message)

# Import components
try:
    # Try relative import first
    try:
        from .core.kostal_api import KostalAPI
        from .core.modbus_client import ModbusClient
        from .core.ha_client import HomeAssistantClient
        from .core.tibber_optimizer import TibberOptimizer
        from .core.pv_shaping_planner import PVShapingPlanner  # v0.10.0
        from .core.consumption_learner import ConsumptionLearner
        from .core.forecast_solar_api import ForecastSolarAPI  # v0.9.2
    except ImportError:
        # Fall back to absolute import
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from core.kostal_api import KostalAPI
        from core.modbus_client import ModbusClient
        from core.ha_client import HomeAssistantClient
        from core.tibber_optimizer import TibberOptimizer
        from core.pv_shaping_planner import PVShapingPlanner  # v0.10.0
        from core.consumption_learner import ConsumptionLearner
        from core.forecast_solar_api import ForecastSolarAPI  # v0.9.2
    
    # Initialize components
    kostal_api = KostalAPI(
        config['inverter_ip'],
        config.get('installer_password', ''),
        config.get('master_password', '')
    )
    modbus_client = ModbusClient(
        config['inverter_ip'],
        config['inverter_port'],
        dry_run=config.get('dry_run', False)
    )
    ha_client = HomeAssistantClient()
    tibber_optimizer = TibberOptimizer(config)
    # v0.10.0 - PV-Shaping-Planer (limit-basiert, keine Netzladung)
    pv_shaping_planner = PVShapingPlanner(config)

    # Byte Order des Wechselrichters pruefen, BEVOR Float-Register
    # geschrieben werden. Bei falscher Annahme waeren alle Float-Werte
    # (inkl. SOC-Limits) unsinnig - siehe Kostal-Doku Kap. 2.1.2.
    try:
        modbus_client.verify_byte_order()
    except Exception as e:
        logger.warning(f"Byte-Order-Pruefung fehlgeschlagen: {e}")

    # Einmalige Registerdiagnose beim Start. Rein lesend, laeuft daher auch
    # im Dry-Run. Zeigt, ob die Limit-Register am Geraet ansprechbar sind,
    # bevor ueberhaupt geschrieben wird.
    try:
        logger.info("--- Registerdiagnose ---")

        capacity_wh = modbus_client.read_work_capacity()
        if capacity_wh:
            configured = config.get('battery_capacity', 0)
            logger.info(f"  1068 Batteriekapazitaet : {capacity_wh:.0f} Wh "
                        f"({capacity_wh/1000:.1f} kWh) | konfiguriert: {configured} kWh")
            if configured and abs(capacity_wh / 1000 - configured) > 1.0:
                logger.warning(f"  battery_capacity weicht deutlich ab - alle "
                               f"Energieberechnungen beruhen darauf!")
        else:
            logger.warning("  1068 Batteriekapazitaet : nicht lesbar")

        raw, mode = modbus_client.read_battery_management_mode()
        logger.info(f"  1080 Management-Modus    : {mode} (Rohwert {raw})")

        limits = modbus_client.read_battery_limits()
        if limits:
            logger.info(f"  1038 Max. Ladeleistung   : {limits.get('max_charge_power')} W")
            logger.info(f"  1040 Max. Entladeleistung: {limits.get('max_discharge_power')} W")
            logger.info(f"  1042 Minimum SOC         : {limits.get('min_soc')} %")
            logger.info(f"  1044 Maximum SOC         : {limits.get('max_soc')} %")
            # Entladegrenze des Geraets merken, damit der Planer sie nicht
            # unnoetig auf max_charge_power herunterzieht.
            if limits.get('max_discharge_power'):
                config['_hardware_max_discharge_power'] = limits['max_discharge_power']
            # Ausgangszustand merken - dorthin wird beim Beenden zurueckgesetzt
            modbus_client.initial_limits = dict(limits)
            logger.info("  -> Limit-Register lesbar, Steuerung sollte funktionieren")
        else:
            logger.error("  1038/1040/1042/1044 NICHT lesbar - die Limit-Steuerung "
                         "wird an diesem Wechselrichter vermutlich nicht funktionieren")
        logger.info("------------------------")
    except Exception as e:
        logger.warning(f"Registerdiagnose fehlgeschlagen: {e}")

    # v0.4.0 - Initialize consumption learner
    consumption_learner = None
    if config.get('enable_consumption_learning', True):
        db_path = '/data/consumption_learning.db'
        learning_days = config.get('learning_period_days', 28)

        # Calculate fallback value
        # Priority: 1) default_hourly_consumption_fallback, 2) average_daily_consumption / 24, 3) 1.0
        default_fallback = config.get('default_hourly_consumption_fallback')
        if not default_fallback:
            avg_daily = config.get('average_daily_consumption')
            if avg_daily:
                default_fallback = float(avg_daily) / 24.0
                logger.info(f"Using average_daily_consumption {avg_daily} kWh/day → {default_fallback:.2f} kWh/h fallback")
            else:
                default_fallback = 1.0
                logger.info("No consumption baseline configured, using default 1.0 kWh/h fallback")

        consumption_learner = ConsumptionLearner(db_path, learning_days, default_fallback)

        # DISABLED: Cleanup duplicates - has critical bug that deletes all data
        # The duplicate handling is now done in queries instead (see get_hourly_profile, etc.)
        # TODO: Fix cleanup function and re-enable after thorough testing
        # try:
        #     deleted = consumption_learner.cleanup_duplicates()
        #     if deleted > 0:
        #         logger.info(f"Cleaned up {deleted} duplicate entries on startup")
        # except Exception as e:
        #     logger.error(f"Error cleaning up duplicates: {e}")

        # v0.10.0 - Kein manuelles Lastprofil mehr. Der Learner baut das
        # Profil aus echten Messwerten auf; ein handgeschriebenes Profil
        # haette dagegen konkurriert. Bis genug Daten da sind, greift
        # default_hourly_consumption_fallback.
        add_log('INFO', f'Consumption learner initialized (learning period: {learning_days} days, '
                        f'fallback: {default_fallback:.2f} kWh/h)')

        # Connect consumption learner to optimizer(s)
        if tibber_optimizer:
            tibber_optimizer.set_consumption_learner(consumption_learner)
        if pv_shaping_planner:
            pv_shaping_planner.set_consumption_learner(consumption_learner)

    # v0.9.2 - Initialize Forecast.Solar Professional API if enabled
    forecast_solar_api = None
    if config.get('enable_forecast_solar_api', False):
        try:
            api_key = config.get('forecast_solar_api_key')
            latitude = config.get('forecast_solar_latitude')
            longitude = config.get('forecast_solar_longitude')

            # v0.10.2 - Key ist optional: ohne Key wird die oeffentliche
            # Schnittstelle genutzt. Nur Koordinaten sind zwingend.
            if latitude and longitude:
                forecast_solar_api = ForecastSolarAPI(api_key, latitude, longitude)

                # Build planes list from individual roof configurations
                planes = []

                # Roof 1
                roof1_dec = config.get('forecast_solar_roof1_declination')
                roof1_azi = config.get('forecast_solar_roof1_azimuth')
                roof1_kwp = config.get('forecast_solar_roof1_kwp')
                if roof1_dec is not None and roof1_azi is not None and roof1_kwp:
                    planes.append({
                        'declination': roof1_dec,
                        'azimuth': roof1_azi,
                        'kwp': roof1_kwp
                    })
                    logger.info(f"Forecast.Solar Roof 1: {roof1_kwp} kWp, azimuth={roof1_azi}°, tilt={roof1_dec}°")

                # Roof 2
                roof2_dec = config.get('forecast_solar_roof2_declination')
                roof2_azi = config.get('forecast_solar_roof2_azimuth')
                roof2_kwp = config.get('forecast_solar_roof2_kwp')
                if roof2_dec is not None and roof2_azi is not None and roof2_kwp:
                    planes.append({
                        'declination': roof2_dec,
                        'azimuth': roof2_azi,
                        'kwp': roof2_kwp
                    })
                    logger.info(f"Forecast.Solar Roof 2: {roof2_kwp} kWp, azimuth={roof2_azi}°, tilt={roof2_dec}°")

                # Store planes in config for later use
                config['forecast_solar_planes'] = planes

                # Connect to optimizer(s)
                if tibber_optimizer:
                    tibber_optimizer.set_forecast_solar_api(forecast_solar_api)
                if pv_shaping_planner:
                    pv_shaping_planner.set_forecast_solar_api(forecast_solar_api)

                add_log('INFO', f'Forecast.Solar Professional API enabled (lat={latitude}, lon={longitude}, {len(planes)} roofs)')
            else:
                logger.warning("Forecast.Solar API aktiviert, aber Koordinaten fehlen "
                               "(forecast_solar_latitude / forecast_solar_longitude)")
                add_log('WARNING', 'Forecast.Solar API: Koordinaten fehlen')

        except Exception as e:
            logger.error(f"Error initializing Forecast.Solar API: {e}")
            add_log('ERROR', f'Failed to initialize Forecast.Solar API: {str(e)}')

    add_log('INFO', 'Components initialized successfully')
    add_log('INFO', 'Tibber Optimizer initialized')

    # Automatic connection test on startup
    if kostal_api:
        logger.info("Testing Kostal connection on startup...")
        result = kostal_api.test_connection()
        if result:
            app_state['inverter']['connected'] = True
            add_log('INFO', 'Connection test successful - Inverter connected')
        else:
            app_state['inverter']['connected'] = False
            add_log('WARNING', 'Connection test failed - Check inverter IP and network')
except ImportError as e:
    logger.warning(f"Could not import components: {e}")
    kostal_api = None
    modbus_client = None
    ha_client = None
    tibber_optimizer = None
    pv_shaping_planner = None
    consumption_learner = None
    add_log('WARNING', 'Running in development mode - components not available')
except Exception as e:
    logger.error(f"Error initializing components: {e}")
    kostal_api = None
    modbus_client = None
    ha_client = None
    tibber_optimizer = None
    pv_shaping_planner = None
    consumption_learner = None
    add_log('ERROR', f'Failed to initialize components: {str(e)}')

# ==============================================================================
# Web Routes
# ==============================================================================

@app.route('/')
def index():
    """Main dashboard"""
    # base_path is injected by context processor
    return render_template('dashboard.html', config=config, state=app_state)

@app.route('/config')
def config_page():
    """Configuration page"""
    # base_path is injected by context processor
    return render_template('config.html', config=config)

@app.route('/logs')
def logs_page():
    """Logs page"""
    # base_path is injected by context processor
    return render_template('logs.html', logs=app_state['logs'])

@app.route('/consumption_import')
def consumption_import_page():
    """Consumption data import page (v0.5.0)"""
    # base_path is injected by context processor
    return render_template('consumption_import.html')

@app.route('/debug_ingress')
def debug_ingress():
    """Debug route to show what Flask sees from Ingress"""
    from flask import url_for
    debug_info = {
        'request.url': request.url,
        'request.base_url': request.base_url,
        'request.url_root': request.url_root,
        'request.path': request.path,
        'request.script_root': request.script_root,
        'request.environ.SCRIPT_NAME': request.environ.get('SCRIPT_NAME', 'NOT SET'),
        'request.environ.PATH_INFO': request.environ.get('PATH_INFO', 'NOT SET'),
        'url_for("static", filename="css/style.css")': url_for('static', filename='css/style.css'),
        'url_for("index")': url_for('index'),
        'headers': dict(request.headers)
    }
    html = '<html><head><title>Debug Ingress</title></head><body>'
    html += '<h1>Flask Ingress Debug Info</h1>'
    html += '<table border="1" cellpadding="5">'
    for key, value in debug_info.items():
        html += f'<tr><td><b>{key}</b></td><td>{value}</td></tr>'
    html += '</table>'
    html += '</body></html>'
    return html

@app.route('/debug_consumption')
def debug_consumption_html():
    """Debug: Show all consumption data as HTML table"""
    try:
        import sqlite3
        with sqlite3.connect(consumption_learner.db_path) as conn:
            cursor = conn.execute("""
                SELECT DATE(timestamp) as date, COUNT(*) as hour_count,
                       MIN(hour) as first_hour, MAX(hour) as last_hour,
                       SUM(CASE WHEN is_manual = 1 THEN 1 ELSE 0 END) as manual_count
                FROM hourly_consumption
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            """)

            rows = cursor.fetchall()

            # Total count
            cursor = conn.execute("SELECT COUNT(*), SUM(CASE WHEN is_manual = 1 THEN 1 ELSE 0 END) FROM hourly_consumption")
            total, manual_total = cursor.fetchone()

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Consumption Data Debug</title>
                <style>
                    body {{ font-family: Arial; background: #1a1a2e; color: #eee; padding: 2rem; }}
                    h1 {{ color: #4CAF50; }}
                    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
                    th, td {{ border: 1px solid #444; padding: 0.5rem; text-align: left; }}
                    th {{ background: #333; }}
                    .total {{ background: #2a2a3e; font-weight: bold; }}
                </style>
            </head>
            <body>
                <h1>🔍 Consumption Data Debug</h1>
                <p><strong>Total:</strong> {total} Stunden ({manual_total} manuell, {total - manual_total} gelernt)</p>
                <table>
                    <tr>
                        <th>Datum</th>
                        <th>Stunden</th>
                        <th>Erste Stunde</th>
                        <th>Letzte Stunde</th>
                        <th>Manuell</th>
                    </tr>
            """

            for row in rows:
                html += f"""
                    <tr>
                        <td>{row[0]}</td>
                        <td>{row[1]}/24</td>
                        <td>{row[2]}</td>
                        <td>{row[3]}</td>
                        <td>{row[4]}</td>
                    </tr>
                """

            html += """
                </table>
                <p style="margin-top: 2rem;"><a href="./" style="color: #4CAF50;">← Zurück zum Dashboard</a></p>
            </body>
            </html>
            """

            return html
    except Exception as e:
        return f"<h1>Error</h1><p>{str(e)}</p>", 500

@app.route('/api/debug_consumption_all')
def debug_consumption_all():
    """Debug: Show all consumption data from DB (JSON)"""
    try:
        import sqlite3
        with sqlite3.connect(consumption_learner.db_path) as conn:
            cursor = conn.execute("""
                SELECT DATE(timestamp) as date, COUNT(*) as hour_count,
                       MIN(timestamp) as first_hour, MAX(timestamp) as last_hour
                FROM hourly_consumption
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            """)

            dates = []
            for row in cursor.fetchall():
                dates.append({
                    'date': row[0],
                    'hour_count': row[1],
                    'first_hour': row[2],
                    'last_hour': row[3]
                })

            # Total count
            cursor = conn.execute("SELECT COUNT(*) FROM hourly_consumption")
            total = cursor.fetchone()[0]

            return jsonify({
                'total_hours': total,
                'dates': dates
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug_consumption/<date>')
def debug_consumption(date):
    """Debug: Show raw DB data for a specific date"""
    try:
        import sqlite3
        with sqlite3.connect(consumption_learner.db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, hour, consumption_kwh, is_manual, created_at
                FROM hourly_consumption
                WHERE DATE(timestamp) = ?
                ORDER BY hour
            """, (date,))

            rows = cursor.fetchall()
            result = {
                'date': date,
                'count': len(rows),
                'hours': []
            }

            for row in rows:
                result['hours'].append({
                    'timestamp': row[0],
                    'hour': row[1],
                    'consumption_kwh': row[2],
                    'is_manual': row[3],
                    'created_at': row[4]
                })

            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/test')
def test_page():
    """Test route to verify new routes work"""
    return "<h1>Test Route funktioniert!</h1><p>Wenn du das siehst, funktionieren neue Routen.</p><p><a href='/'>Zurück zum Dashboard</a></p>"

# ==============================================================================
# API Endpoints
# ==============================================================================

@app.route('/api/status')
def api_status():
    """Get current status"""
    app_state['last_update'] = datetime.now().isoformat()

    # Try to read battery SOC from Home Assistant
    if ha_client:
        try:
            soc = ha_client.get_state(config.get('battery_soc_sensor', 'sensor.zwh8_8500_battery_soc'))
            if soc and soc not in ['unknown', 'unavailable']:
                app_state['battery']['soc'] = float(soc)
        except Exception as e:
            logger.debug(f"Could not read battery SOC: {e}")

        # Read battery power (v0.2.0)
        try:
            battery_power_sensor = config.get('battery_power_sensor')
            if battery_power_sensor:
                power = ha_client.get_state(battery_power_sensor)
                if power and power not in ['unknown', 'unavailable']:
                    app_state['battery']['power'] = float(power)
        except Exception as e:
            logger.debug(f"Could not read battery power: {e}")

        # Read battery voltage (v0.2.0)
        try:
            battery_voltage_sensor = config.get('battery_voltage_sensor')
            if battery_voltage_sensor:
                voltage = ha_client.get_state(battery_voltage_sensor)
                if voltage and voltage not in ['unknown', 'unavailable']:
                    app_state['battery']['voltage'] = float(voltage)
        except Exception as e:
            logger.debug(f"Could not read battery voltage: {e}")

        # Read current Tibber price (v0.2.1 - simplified)
        # v0.10.0 - In der forecast-Strategie spielen Preise keine Rolle.
        # Ohne diese Bremse werden bei fehlenden Tibber-Sensoren drei
        # 404-Requests pro Statusabruf erzeugt (alle 2s) und das Log geflutet.
        try:
            if config.get('charging_strategy', 'forecast') != 'price':
                raise _SkipTibber()
            # Current price from main Tibber sensor
            tibber_sensor = config.get('tibber_price_sensor', 'sensor.tibber_prices')
            current_price = ha_client.get_state(tibber_sensor)
            if current_price and current_price not in ['unknown', 'unavailable']:
                app_state['price']['current'] = float(current_price)

            # Price level from separate German sensor
            tibber_level_sensor = config.get('tibber_price_level_sensor', 'sensor.tibber_price_level_deutsch')
            if tibber_level_sensor:
                price_level = ha_client.get_state(tibber_level_sensor)
                if price_level and price_level not in ['unknown', 'unavailable']:
                    app_state['price']['level'] = price_level

            # Calculate average price from attributes
            prices_data = ha_client.get_state_with_attributes(tibber_sensor)
            if prices_data and 'attributes' in prices_data:
                today_prices = prices_data['attributes'].get('today', [])
                if today_prices and isinstance(today_prices, list):
                    avg = sum(p.get('total', 0) for p in today_prices) / len(today_prices)
                    app_state['price']['average'] = float(avg)
        except _SkipTibber:
            pass
        except Exception as e:
            logger.debug(f"Could not read Tibber price: {e}")

        # Read PV forecast data (v0.2.1)
        try:
            # Current production (sum of both roofs)
            pv_power_now = 0
            for roof in ['roof1', 'roof2']:
                sensor = config.get(f'pv_power_now_{roof}')
                if sensor:
                    power = ha_client.get_state(sensor)
                    if power and power not in ['unknown', 'unavailable']:
                        pv_power_now += float(power)

            # Remaining production today (sum of both roofs)
            pv_remaining_today = 0
            for roof in ['roof1', 'roof2']:
                sensor = config.get(f'pv_remaining_today_{roof}')
                if sensor:
                    remaining = ha_client.get_state(sensor)
                    if remaining and remaining not in ['unknown', 'unavailable']:
                        pv_remaining_today += float(remaining)

            # Production forecast tomorrow (sum of both roofs)
            pv_tomorrow = 0
            for roof in ['roof1', 'roof2']:
                sensor = config.get(f'pv_production_tomorrow_{roof}')
                if sensor:
                    tomorrow = ha_client.get_state(sensor)
                    if tomorrow and tomorrow not in ['unknown', 'unavailable']:
                        pv_tomorrow += float(tomorrow)

            # Update app state
            app_state['forecast']['today'] = pv_remaining_today
            app_state['forecast']['tomorrow'] = pv_tomorrow
            app_state['pv'] = {
                'power_now': pv_power_now,
                'remaining_today': pv_remaining_today
            }
        except Exception as e:
            logger.debug(f"Could not read PV data: {e}")

    return jsonify({
        'status': 'ok',
        'timestamp': app_state['last_update'],
        'controller_running': app_state['controller_running'],
        'inverter': app_state['inverter'],
        'battery': app_state['battery'],
        'price': app_state['price'],
        'forecast': app_state['forecast'],
        'pv': app_state.get('pv', {'power_now': 0, 'remaining_today': 0}),
        'charging_plan': app_state.get('charging_plan', {}),
        # v0.10.0 - PV-Shaping
        'charging_strategy': config.get('charging_strategy', 'forecast'),
        'dry_run': config.get('dry_run', False),
        'shaping_plan': app_state.get('shaping_plan'),
        'limits_readback': app_state.get('limits_readback')
    })

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Get or update configuration"""
    global config
    
    if request.method == 'POST':
        try:
            new_config = request.json
            
            # Update configuration
            config.update(new_config)
            
            # Save to file
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
            
            add_log('INFO', 'Configuration updated and saved')
            return jsonify({
                'status': 'ok',
                'message': 'Configuration saved successfully'
            })
        except Exception as e:
            add_log('ERROR', f'Failed to save configuration: {str(e)}')
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    return jsonify(config)

def read_soc(ha_client, config, fallback=None):
    """
    Liest den Batterie-SOC aus Home Assistant.

    HA liefert bei Neustarts oder Stoerungen 'unavailable'/'unknown' -
    Text, an dem float() scheitert. Ein blosses `or 0` faengt das NICHT ab,
    weil nicht-leerer Text wahr ist. Genau daran ist der Regelzyklus
    abgestuerzt; im externen Modus bedeutet ein ausgefallener Zyklus einen
    ausbleibenden Schreibzugriff und damit die Timeout-Blockade.
    """
    raw = ha_client.get_state(config.get('battery_soc_sensor', ''))
    if raw is None or str(raw).strip().lower() in ('', 'unavailable', 'unknown', 'none'):
        logger.warning(f"Battery-SOC-Sensor liefert '{raw}' - kein verwertbarer Wert")
        return fallback
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(f"Battery-SOC-Sensor liefert unerwarteten Wert '{raw}'")
        return fallback


@app.route('/api/hold_test', methods=['POST'])
def api_hold_test():
    """
    Haltetest der Leistungsregister (v0.11.0).

    Der Registertest beantwortet nur, ob ein Wert die naechste Sekunde
    ueberlebt. Entscheidend ist aber, ob er ueber MINUTEN haelt - sonst
    ist er als Steuerung wertlos.

    Deshalb: einen deutlich abweichenden Wert schreiben (Default 2000 W,
    weit weg von allem, was die Firmware selbst setzt), dann nur noch
    beobachten. Am Ende Originalwert wiederherstellen.

    Ein Ladelimit begrenzt nur, es erzwingt nichts - der Test kann die
    Batterie also nicht zu etwas zwingen, hoechstens kurzzeitig bremsen.
    """
    if not modbus_client:
        return jsonify({'success': False, 'error': 'Modbus-Client nicht verfuegbar'}), 500
    # get(key, {}) greift NICHT, wenn der Schluessel mit Wert None existiert
    if (app_state.get('hold_test') or {}).get('running'):
        return jsonify({'success': False, 'error': 'Haltetest laeuft bereits'}), 409

    body = request.get_json(silent=True) or {}
    test_value = float(body.get('value', 2000))
    duration = int(body.get('duration', 180))
    interval = int(body.get('interval', 10))

    before = modbus_client.read_battery_limits()
    if 'max_charge_power' not in before:
        return jsonify({'success': False, 'error': 'Register 1038 nicht lesbar'}), 200

    original = before['max_charge_power']
    app_state['hold_test'] = {
        'running': True, 'original': original, 'test_value': test_value,
        'samples': [], 'verdict': None,
    }

    def run():
        was_dry_run = modbus_client.dry_run
        modbus_client.dry_run = False
        started = time.monotonic()
        try:
            modbus_client.set_max_charge_power(test_value)
            add_log('INFO', f'Haltetest gestartet: Register 1038 auf {test_value} W '
                            f'(Ausgangswert {original} W), Beobachtung {duration}s')
            held = True
            while time.monotonic() - started < duration:
                time.sleep(interval)
                value = modbus_client.read_battery_limits().get('max_charge_power')
                elapsed = round(time.monotonic() - started)
                app_state['hold_test']['samples'].append({'t': elapsed, 'value': value})
                if value is None:
                    continue
                if abs(value - test_value) > 1.0:
                    held = False
                    app_state['hold_test']['verdict'] = (
                        f'Nach {elapsed}s von der Firmware ueberschrieben '
                        f'({test_value} -> {value} W). Ein Sollwert haelt hier nicht; '
                        f'zum Halten muesste haeufiger als alle {elapsed}s geschrieben werden.')
                    add_log('WARNING', f'Haltetest: Wert nach {elapsed}s ueberschrieben '
                                       f'({test_value} -> {value} W)')
                    break
            if held:
                app_state['hold_test']['verdict'] = (
                    f'Wert hielt ueber die volle Beobachtungsdauer von {duration}s. '
                    f'Die Leistungsregister sind als Steuerung nutzbar.')
                add_log('INFO', f'Haltetest: {test_value} W hielt {duration}s - '
                                f'Leistungsregister nutzbar')
        except Exception as e:
            app_state['hold_test']['verdict'] = f'Fehler: {e}'
            logger.error(f"Haltetest fehlgeschlagen: {e}", exc_info=True)
        finally:
            try:
                modbus_client.set_max_charge_power(original)
                add_log('INFO', f'Haltetest beendet, Register 1038 auf {original} W zurueckgesetzt')
            except Exception as e:
                logger.error(f"Konnte Originalwert nicht wiederherstellen: {e}")
            modbus_client.dry_run = was_dry_run
            modbus_client.last_limits = {}
            app_state['hold_test']['running'] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'success': True, 'message': f'Haltetest laeuft {duration}s',
                    'original': original, 'test_value': test_value})


@app.route('/api/hold_test', methods=['GET'])
def api_hold_test_status():
    """Zwischenstand des laufenden oder letzten Haltetests."""
    return jsonify(app_state.get('hold_test') or {'running': False, 'samples': []})


@app.route('/api/register_test', methods=['POST'])
def api_register_test():
    """
    Begrenzter Schreibtest der Limit-Register (v0.10.8).

    Beantwortet die Frage, ob der Wechselrichter die Register 1038/1040/
    1042/1044 tatsaechlich ANNIMMT - Lesbarkeit allein beweist das nicht.

    Ablauf je Register: Ist-Wert lesen, minimal veraenderten Testwert
    schreiben, zuruecklesen, Originalwert wiederherstellen.

    Schreibt bewusst auch im Dry-Run, weil genau das die Frage ist. Die
    Aenderungen sind winzig und werden sofort zurueckgenommen; ausgeloest
    wird der Test ausschliesslich manuell.
    """
    if not modbus_client:
        return jsonify({'success': False, 'error': 'Modbus-Client nicht verfuegbar'}), 500

    before = modbus_client.read_battery_limits()
    if not before:
        return jsonify({'success': False,
                        'error': 'Limit-Register nicht lesbar - Test nicht moeglich'}), 200

    # Vorabpruefung auf Fluechtigkeit: manche Register (v.a. 1038/1040)
    # werden von der Firmware laufend mit der momentanen Leistungsfaehigkeit
    # der Batterie ueberschrieben. Aendern sie sich OHNE unser Zutun, ist ein
    # Schreibtest sinnlos - der Wert waere ohnehin sofort wieder weg.
    time.sleep(2)
    drift_check = modbus_client.read_battery_limits()
    volatile = {}
    for name, value in before.items():
        second = drift_check.get(name)
        if second is not None and abs(second - value) > 0.5:
            volatile[name] = (value, second)

    # Testwerte: minimale, ungefaehrliche Abweichung vom Ist-Zustand
    setters = {
        'min_soc':             (modbus_client.set_min_soc,             lambda v: min(30.0, v + 2)),
        'max_soc':             (modbus_client.set_max_soc,             lambda v: max(50.0, v - 2)),
        'max_charge_power':    (modbus_client.set_max_charge_power,    lambda v: max(100.0, v - 100)),
        'max_discharge_power': (modbus_client.set_max_discharge_power, lambda v: max(100.0, v - 100)),
    }

    results = {}
    was_dry_run = modbus_client.dry_run
    modbus_client.dry_run = False          # bewusster, begrenzter Eingriff
    try:
        for name, (setter, make_test_value) in setters.items():
            original = before.get(name)
            if original is None:
                results[name] = {'status': 'uebersprungen', 'grund': 'nicht lesbar'}
                continue

            test_value = round(make_test_value(original), 1)
            if abs(test_value - original) < 0.5:
                results[name] = {'status': 'uebersprungen',
                                 'grund': 'kein sinnvoller Testwert moeglich'}
                continue

            setter(test_value)
            actual = modbus_client.read_battery_limits().get(name)
            setter(original)               # sofort zurueck
            restored = modbus_client.read_battery_limits().get(name)

            accepted = actual is not None and abs(actual - test_value) < 1.0
            results[name] = {
                'status': 'angenommen' if accepted else 'ABGELEHNT',
                'original': original,
                'testwert': test_value,
                'gelesen': actual,
                'wiederhergestellt': restored,
            }
    finally:
        modbus_client.dry_run = was_dry_run
        modbus_client.last_limits = {}     # Cache leeren, Plan neu schreiben lassen

    raw, mode = modbus_client.read_battery_management_mode()
    accepted = [k for k, v in results.items() if v.get('status') == 'angenommen']
    rejected = [k for k, v in results.items() if v.get('status') == 'ABGELEHNT']

    add_log('INFO', f'Registertest im Modus "{mode}": {len(accepted)} angenommen, '
                    f'{len(rejected)} abgelehnt'
                    + (f' ({", ".join(rejected)})' if rejected else ''))

    return jsonify({
        'success': True,
        'battery_management_mode': mode,
        'battery_management_mode_raw': raw,
        'dry_run_war_aktiv': was_dry_run,
        'results': results,
        'fazit': ('Alle Limit-Register werden angenommen - die Steuerung funktioniert'
                  if not rejected and accepted else
                  f'Abgelehnt: {", ".join(rejected)}' if rejected else
                  'Kein Register konnte getestet werden'),
    })


@app.route('/api/control', methods=['POST'])
def api_control():
    """Manual control endpoint"""
    data = request.json
    action = data.get('action')
    
    add_log('INFO', f'Control action received: {action}')
    
    try:
        if action == 'start_charging':
            # Start manual charging
            if kostal_api and modbus_client:
                # Set external control mode
                kostal_api.set_external_control(True)
                # Get charge power from request or use max_charge_power as fallback
                requested_power = data.get('power', config['max_charge_power'])
                charge_power = -abs(int(requested_power))
                modbus_client.write_battery_power(charge_power)

                app_state['inverter']['mode'] = 'manual_charging'
                app_state['inverter']['control_mode'] = 'external'
                add_log('INFO', f'Manual charging started: {charge_power}W')
            else:
                add_log('WARNING', 'Components not available - cannot start charging')
                
        elif action == 'stop_charging':
            # Stop charging, back to internal control
            if kostal_api and modbus_client:
                modbus_client.write_battery_power(0)
                kostal_api.set_external_control(False)
                
                app_state['inverter']['mode'] = 'automatic'
                app_state['inverter']['control_mode'] = 'internal'
                add_log('INFO', 'Charging stopped, back to internal control')
            else:
                add_log('WARNING', 'Components not available - cannot stop charging')
                
        elif action == 'auto_mode':
            # Enable automatic optimization
            app_state['controller_running'] = True
            app_state['inverter']['mode'] = 'automatic'
            add_log('INFO', 'Automatic optimization mode enabled')

        elif action == 'toggle_automation':
            # v0.2.5 - Toggle automation on/off
            enabled = data.get('enabled', True)
            app_state['controller_running'] = enabled
            if enabled:
                add_log('INFO', 'Automatik aktiviert')
            else:
                add_log('INFO', 'Automatik deaktiviert')

        elif action == 'test_connection':
            # Test connection to inverter
            if kostal_api:
                logger.info("Testing Kostal connection...")
                result = kostal_api.test_connection()
                if result:
                    app_state['inverter']['connected'] = True
                    add_log('INFO', '✅ Connection test successful')
                else:
                    app_state['inverter']['connected'] = False
                    add_log('ERROR', '❌ Connection test failed')
            else:
                add_log('WARNING', 'Components not available - cannot test connection')
        
        else:
            add_log('WARNING', f'Unknown action: {action}')
            return jsonify({
                'status': 'error',
                'message': f'Unknown action: {action}'
            }), 400
        
        return jsonify({
            'status': 'ok',
            'action': action,
            'message': 'Action executed successfully'
        })
        
    except Exception as e:
        add_log('ERROR', f'Error executing action {action}: {str(e)}')
        logger.exception(e)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/logs')
def api_logs():
    """Get logs"""
    return jsonify({
        'logs': app_state['logs']
    })

@app.route('/api/charging_plan')
def api_charging_plan():
    """Get current charging plan (v0.3.0)"""
    plan = app_state.get('charging_plan', {})

    # Format für Frontend
    response = {
        'has_plan': plan.get('planned_start') is not None,
        'planned_start': plan.get('planned_start'),
        'planned_end': plan.get('planned_end'),
        'last_calculated': plan.get('last_calculated')
    }

    return jsonify(response)

@app.route('/api/recalculate_plan', methods=['POST'])
def api_recalculate_plan():
    """Manually trigger charging plan recalculation (v0.3.2)"""
    try:
        add_log('INFO', 'Manual charging plan recalculation triggered')
        update_charging_plan()
        return jsonify({
            'status': 'ok',
            'message': 'Charging plan recalculated'
        })
    except Exception as e:
        logger.error(f"Error in manual recalculation: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/charging_status')
def api_charging_status():
    """Get detailed charging status explanation (v0.3.6)"""
    try:
        status = get_charging_status_explanation()
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error getting charging status: {e}")
        return jsonify({
            'explanation': 'Fehler beim Abrufen des Status',
            'will_charge': False,
            'conditions': {},
            'current_soc': 0,
            'target_soc': 0,
            'pv_remaining': 0,
            'planned_start': None,
            'planned_end': None
        }), 500

@app.route('/api/battery_schedule')
def api_battery_schedule():
    """Get daily battery schedule with SOC forecast and charging plan (v0.9.0)"""
    # v0.10.0 - Preisbasierter Tagesplan. In der forecast-Strategie
    # bedeutungslos; der Endpunkt wuerde sonst Tibber-Abfragen und
    # "Ladefenster" berechnen, die nie ausgefuehrt werden.
    if config.get('charging_strategy', 'forecast') != 'price':
        return jsonify({'success': False, 'reason': 'not_applicable_in_forecast_strategy'}), 200
    try:
        # Get current SOC
        current_soc = app_state['battery']['soc']

        # Get Tibber prices
        prices = []
        if ha_client:
            tibber_sensor = config.get('tibber_price_sensor', 'sensor.tibber_prices')
            attrs = ha_client.get_attributes(tibber_sensor)
            if attrs and 'today' in attrs:
                prices = attrs['today']

        # Generate plan
        plan = tibber_optimizer.plan_daily_battery_schedule(
            ha_client=ha_client,
            config=config,
            current_soc=current_soc,
            prices=prices
        )

        if plan:
            return jsonify(plan)
        else:
            return jsonify({
                'error': 'Could not generate battery schedule',
                'hourly_soc': [current_soc] * 24,
                'hourly_charging': [0] * 24,
                'hourly_pv': [0] * 24,
                'hourly_consumption': [0] * 24,
                'hourly_prices': [0] * 24,
                'charging_windows': [],
                'last_planned': None
            }), 500

    except Exception as e:
        logger.error(f"Error getting battery schedule: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'hourly_soc': [0] * 24,
            'hourly_charging': [0] * 24,
            'hourly_pv': [0] * 24,
            'hourly_consumption': [0] * 24,
            'hourly_prices': [0] * 24,
            'charging_windows': [],
            'last_planned': None
        }), 500

@app.route('/api/adjust_power', methods=['POST'])
def api_adjust_power():
    """Adjust charging power during active charging (v0.2.0)"""
    try:
        data = request.json
        power = data.get('power', config.get('max_charge_power', 3900))

        # Only execute if currently charging
        if app_state['inverter']['mode'] in ['manual_charging', 'auto_charging']:
            if not modbus_client:
                add_log('ERROR', 'Modbus client not available')
                return jsonify({
                    'status': 'error',
                    'message': 'Modbus client not available'
                }), 500

            charge_power = -abs(int(power))
            success = modbus_client.write_battery_power(charge_power)

            if success:
                add_log('INFO', f'Charging power adjusted to {power}W')
                return jsonify({
                    'status': 'ok',
                    'power': power
                })
            else:
                add_log('ERROR', 'Failed to adjust charging power')
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to adjust charging power'
                }), 500
        else:
            return jsonify({
                'status': 'error',
                'message': 'Not currently charging'
            }), 400

    except Exception as e:
        add_log('ERROR', f'Error adjusting power: {str(e)}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/tibber_price_chart')
def api_tibber_price_chart():
    """Get Tibber price data for today (v0.6.3) for chart display"""
    if config.get('charging_strategy', 'forecast') != 'price':
        return jsonify({'success': False, 'reason': 'not_applicable_in_forecast_strategy'}), 200
    try:
        if not ha_client:
            return jsonify({
                'success': False,
                'error': 'HA client not available'
            }), 500

        tibber_sensor = config.get('tibber_price_sensor', 'sensor.tibber_prices')
        prices_data = ha_client.get_state_with_attributes(tibber_sensor)

        if not prices_data or 'attributes' not in prices_data:
            return jsonify({
                'success': False,
                'error': 'No Tibber price data available'
            }), 500

        today_prices = prices_data['attributes'].get('today', [])

        if not today_prices:
            return jsonify({
                'success': False,
                'error': 'No price data for today'
            }), 500

        # Format for chart: labels (hours) and data (prices in Cent)
        hours = []
        prices = []

        for entry in today_prices:
            # Parse hour from timestamp
            start_time = entry.get('startsAt', '')
            if start_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    # Convert to local timezone
                    local_dt = dt.astimezone()
                    hours.append(f"{local_dt.hour:02d}:00")
                    # Convert EUR to Cent
                    prices.append(round(entry.get('total', 0) * 100, 2))
                except:
                    continue

        return jsonify({
            'success': True,
            'labels': hours,
            'prices': prices,
            'current_hour': datetime.now().astimezone().hour
        })

    except Exception as e:
        logger.error(f"Error getting Tibber price chart data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_forecast_chart')
def api_consumption_forecast_chart():
    """Get consumption forecast for today (v0.6.3) based on learned data"""
    try:
        if not consumption_learner:
            return jsonify({
                'success': False,
                'error': 'Consumption learner not available'
            }), 500

        # Get hourly profile (forecast) for today's weekday
        from datetime import datetime
        today = datetime.now().date()
        profile = consumption_learner.get_hourly_profile(target_date=today)

        if not profile:
            return jsonify({
                'success': False,
                'error': 'No consumption data available'
            }), 500

        # Get actual consumption for today (v0.7.17: use DB values for consistency)
        actual_consumption = []
        from datetime import datetime

        # Get recorded values from database for today
        today_db_consumption = consumption_learner.get_today_consumption()

        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        # For current hour only: calculate live value with blending
        current_hour_live_value = None
        if ha_client and current_minute < 59:
            try:
                entity_id = config.get('home_consumption_sensor')
                if entity_id:
                    # Get history for current hour only
                    hour_start = now.replace(minute=0, second=0, microsecond=0)
                    history = ha_client.get_history(entity_id, hour_start, now)

                    # Calculate average for current hour
                    values = []
                    for entry in history:
                        try:
                            state = entry.get('state')
                            if state in ['unknown', 'unavailable', None]:
                                continue

                            value = float(state)
                            if value < 0 or value > 50000:
                                continue

                            # Convert W to kW
                            if value > 50:
                                value = value / 1000

                            values.append(value)
                        except:
                            continue

                    if values:
                        avg = sum(values) / len(values)

                        # Blend actual data with forecast for smoother display
                        elapsed_fraction = current_minute / 60.0
                        remaining_fraction = (60 - current_minute) / 60.0
                        forecast_value = profile.get(current_hour, avg)

                        current_hour_live_value = (avg * elapsed_fraction) + (forecast_value * remaining_fraction)
            except Exception as e:
                logger.error(f"Error calculating current hour consumption: {e}")

        # Build actual consumption array
        for hour in range(24):
            if hour < current_hour:
                # Past hours: use DB value if available
                if hour in today_db_consumption:
                    actual_consumption.append(round(today_db_consumption[hour], 2))
                else:
                    actual_consumption.append(None)
            elif hour == current_hour:
                # Current hour: use live blended value or DB value
                if current_hour_live_value is not None:
                    actual_consumption.append(round(current_hour_live_value, 2))
                elif hour in today_db_consumption:
                    actual_consumption.append(round(today_db_consumption[hour], 2))
                else:
                    actual_consumption.append(None)
            else:
                # Future hours: no actual data
                actual_consumption.append(None)

        # Format for chart: labels (hours) and data (consumption in kW)
        hours = []
        forecast_consumption = []

        for hour in range(24):
            hours.append(f"{hour:02d}:00")
            forecast_consumption.append(round(profile.get(hour, 0), 2))

        # Calculate forecast accuracy for completed hours
        accuracy = None
        accuracy_hours = 0

        if actual_consumption and forecast_consumption:
            errors = []
            now = datetime.now()
            current_hour = now.hour

            for hour in range(current_hour):  # Only completed hours
                actual = actual_consumption[hour] if hour < len(actual_consumption) else None
                forecast = forecast_consumption[hour] if hour < len(forecast_consumption) else None

                # Skip if either value is missing or forecast is too small (division by zero)
                if actual is not None and forecast is not None and forecast > 0.01:
                    # Calculate percentage error
                    percentage_error = abs(actual - forecast) / forecast * 100
                    errors.append(percentage_error)

            if errors:
                # Mean Absolute Percentage Error (MAPE)
                mape = sum(errors) / len(errors)
                # Convert to accuracy (100% = perfect, 0% = completely wrong)
                accuracy = max(0, 100 - mape)
                accuracy_hours = len(errors)
                logger.debug(f"Forecast accuracy: {accuracy:.1f}% based on {accuracy_hours} hours (MAPE: {mape:.1f}%)")

        return jsonify({
            'success': True,
            'labels': hours,
            'forecast': forecast_consumption,
            'actual': actual_consumption,
            'current_hour': datetime.now().astimezone().hour,
            'accuracy': round(accuracy, 1) if accuracy is not None else None,
            'accuracy_hours': accuracy_hours
        })

    except Exception as e:
        logger.error(f"Error getting consumption forecast chart data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_learning')
def api_consumption_learning():
    """Get consumption learning statistics and hourly profile (v0.4.0)"""
    try:
        if not consumption_learner:
            return jsonify({
                'enabled': False,
                'message': 'Consumption learning not enabled'
            })

        # Get statistics
        stats = consumption_learner.get_statistics()

        # Get hourly profile for today's weekday
        from datetime import datetime
        today = datetime.now().date()
        profile = consumption_learner.get_hourly_profile(target_date=today)

        return jsonify({
            'enabled': True,
            'statistics': stats,
            'hourly_profile': profile
        })

    except Exception as e:
        logger.error(f"Error getting consumption learning data: {e}")
        return jsonify({
            'enabled': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_import_csv', methods=['POST'])
def api_consumption_import_csv():
    """Import consumption data from CSV file (v0.4.0)"""
    try:
        if not consumption_learner:
            return jsonify({
                'success': False,
                'error': 'Consumption learning not enabled'
            }), 400

        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        if not file.filename.endswith('.csv'):
            return jsonify({
                'success': False,
                'error': 'File must be CSV format'
            }), 400

        # Read CSV content
        csv_content = file.read().decode('utf-8')

        # Clear all manually imported data before importing new data
        # This prevents old manual data from lingering
        deleted = consumption_learner.clear_all_manual_data()
        add_log('INFO', f'🗑️ Gelöscht: {deleted} alte manuelle Datensätze vor Import')

        # Import data
        result = consumption_learner.import_from_csv(csv_content)

        if result['success']:
            add_log('INFO', f'✅ CSV Import: {result["imported_hours"]} Stundenwerte importiert')
            return jsonify(result)
        else:
            add_log('ERROR', f'❌ CSV Import fehlgeschlagen: {result.get("error", "Unknown error")}')
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error importing CSV: {e}", exc_info=True)
        add_log('ERROR', f'CSV Import Fehler: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_import_ha', methods=['POST'])
def api_consumption_import_ha():
    """Import consumption data from Home Assistant history (v0.6.0)"""
    try:
        if not consumption_learner:
            return jsonify({
                'success': False,
                'error': 'Consumption learning not enabled'
            }), 400

        if not ha_client:
            return jsonify({
                'success': False,
                'error': 'Home Assistant client not available'
            }), 400

        # Get entity_id and days from config
        entity_id = config.get('home_consumption_sensor')
        if not entity_id:
            return jsonify({
                'success': False,
                'error': 'home_consumption_sensor not configured'
            }), 400

        days = request.json.get('days', 28) if request.json else 28

        add_log('INFO', f'Starting Home Assistant history import for {entity_id} (last {days} days)...')

        # Clear all manually imported data before importing new data
        deleted = consumption_learner.clear_all_manual_data()
        add_log('INFO', f'🗑️ Gelöscht: {deleted} alte manuelle Datensätze vor Import')

        # Import from Home Assistant
        result = consumption_learner.import_from_home_assistant(ha_client, entity_id, days)

        if result['success']:
            add_log('INFO', f'✅ HA Import: {result["imported_hours"]} Stundenwerte aus Home Assistant importiert')
            return jsonify(result)
        else:
            add_log('ERROR', f'❌ HA Import fehlgeschlagen: {result.get("error", "Unknown error")}')
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error importing from Home Assistant: {e}", exc_info=True)
        add_log('ERROR', f'HA Import Fehler: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_data', methods=['GET'])
def api_consumption_data_get():
    """Get all consumption data for editing (v0.4.0)"""
    try:
        if not consumption_learner:
            return jsonify({
                'success': False,
                'error': 'Consumption learning not enabled'
            }), 400

        # Get all data from database
        import sqlite3
        daily_data = []

        with sqlite3.connect(consumption_learner.db_path) as conn:
            # Get unique dates
            cursor = conn.execute("""
                SELECT DISTINCT DATE(timestamp) as date
                FROM hourly_consumption
                ORDER BY date DESC
                LIMIT 28
            """)

            dates = [row[0] for row in cursor.fetchall()]

            # For each date, get all 24 hours
            for date_str in dates:
                # Get all entries for this date (may have duplicates due to non-rounded timestamps)
                cursor = conn.execute("""
                    SELECT hour, consumption_kwh, is_manual, created_at
                    FROM hourly_consumption
                    WHERE DATE(timestamp) = ?
                    ORDER BY hour, is_manual ASC, created_at DESC
                """, (date_str,))

                # Filter duplicates: prefer learned (is_manual=0) over imported (is_manual=1)
                # and latest created_at as tiebreaker
                hours_data = {}
                for hour, consumption, is_manual, created_at in cursor.fetchall():
                    if hour not in hours_data:
                        hours_data[hour] = consumption
                    elif hour in hours_data:
                        # Already have an entry - only replace if current is learned (is_manual=0)
                        # The ORDER BY ensures learned entries come first
                        pass  # Keep first entry (already optimal due to ORDER BY)

                # Build 24-hour array
                hours = [hours_data.get(h, 0) for h in range(24)]

                # Get weekday (0=Monday, 6=Sunday)
                from datetime import datetime
                date_obj = datetime.fromisoformat(date_str)
                weekdays = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
                weekday = weekdays[date_obj.weekday()]

                daily_data.append({
                    'date': date_str,
                    'weekday': weekday,
                    'hours': hours
                })

        return jsonify({
            'success': True,
            'data': daily_data
        })

    except Exception as e:
        logger.error(f"Error getting consumption data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/consumption_data', methods=['POST'])
def api_consumption_data_post():
    """Save consumption data from web editor (v0.4.0)"""
    try:
        if not consumption_learner:
            return jsonify({
                'success': False,
                'error': 'Consumption learning not enabled'
            }), 400

        data = request.json.get('data', [])

        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        # Import the data
        result = consumption_learner.import_detailed_history(data)

        if result['success']:
            add_log('INFO', f'✅ Daten gespeichert: {result["imported_hours"]} Stundenwerte')
            return jsonify(result)
        else:
            add_log('ERROR', f'❌ Fehler beim Speichern der Daten')
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error saving consumption data: {e}")
        add_log('ERROR', f'Fehler beim Speichern: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ==============================================================================
# Error Handlers
# ==============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ==============================================================================
# Background Controller Thread
# ==============================================================================

def update_charging_plan():
    """Calculate optimal charging schedule based on Tibber prices (v0.3.0)"""
    # v0.10.5 - Reine Preislogik. In der forecast-Strategie wuerde sie nur
    # erfolglos Tibber-Sensoren abfragen und das Log zumuellen; der daraus
    # gefuellte "Geplante Ladung"-Bereich ist dort ohnehin ausgeblendet.
    if config.get('charging_strategy', 'forecast') != 'price':
        return
    try:
        logger.info("Starting charging plan calculation...")
        add_log('INFO', 'Calculating charging plan...')

        # Check prerequisites
        if not ha_client:
            logger.warning("HA client not available - cannot calculate charging plan")
            add_log('WARNING', 'Charging plan calculation skipped: HA client not available')
            return

        if not tibber_optimizer:
            logger.warning("Tibber optimizer not available - cannot calculate charging plan")
            add_log('WARNING', 'Charging plan calculation skipped: Tibber optimizer not available')
            return

        # Hole Tibber-Preise
        tibber_sensor = config.get('tibber_price_sensor', 'sensor.tibber_prices')
        logger.info(f"Fetching price data from sensor: {tibber_sensor}")
        prices_data = ha_client.get_state_with_attributes(tibber_sensor)

        if not prices_data:
            logger.warning(f"Could not get data from {tibber_sensor}")
            add_log('WARNING', f'No data from Tibber sensor: {tibber_sensor}')
            return

        if 'attributes' not in prices_data:
            logger.warning(f"Sensor {tibber_sensor} has no attributes")
            add_log('WARNING', f'Tibber sensor {tibber_sensor} missing attributes')
            return

        # Kombiniere heute + morgen Preise
        today = prices_data['attributes'].get('today', [])
        tomorrow = prices_data['attributes'].get('tomorrow', [])
        all_prices = today + tomorrow

        logger.info(f"Price data: {len(today)} today, {len(tomorrow)} tomorrow = {len(all_prices)} total")

        if not all_prices:
            logger.warning("No price data in today/tomorrow attributes")
            add_log('WARNING', 'No Tibber price data available (today/tomorrow empty)')
            return

        # Finde optimales Ladeende
        logger.info("Analyzing prices to find optimal charge end time...")
        charge_end = tibber_optimizer.find_optimal_charge_end_time(all_prices)

        if charge_end:
            # Hole aktuellen SOC
            current_soc = app_state['battery']['soc']
            max_soc = config.get('auto_charge_below_soc', 95)

            logger.info(f"Found optimal charge end time: {charge_end}, current SOC: {current_soc}%, target: {max_soc}%")

            # Berechne Ladebeginn
            charge_start = tibber_optimizer.calculate_charge_start_time(
                charge_end, current_soc, max_soc
            )

            # Speichere im State
            app_state['charging_plan']['planned_start'] = charge_start.isoformat()
            app_state['charging_plan']['planned_end'] = charge_end.isoformat()
            app_state['charging_plan']['last_calculated'] = datetime.now().isoformat()
            app_state['charging_plan']['target_soc'] = max_soc

            add_log('INFO', f'✓ Ladeplan berechnet: Start {charge_start.strftime("%d.%m. %H:%M")} - Ende {charge_end.strftime("%d.%m. %H:%M")}')

            # Optional: Setze auch Home Assistant Input Datetime
            try:
                input_end = config.get('input_datetime_planned_charge_end')
                input_start = config.get('input_datetime_planned_charge_start')

                if input_end:
                    ha_client.set_datetime(input_end, charge_end)
                    logger.debug(f"Updated {input_end}")
                if input_start:
                    ha_client.set_datetime(input_start, charge_start)
                    logger.debug(f"Updated {input_start}")
            except Exception as e:
                logger.warning(f"Could not set input_datetime: {e}")
        else:
            logger.info("No optimal charge end time found - prices remain low or insufficient data")
            add_log('INFO', 'Kein optimaler Ladezeitpunkt gefunden (Preise bleiben günstig)')
            # Mark calculation as done even if no plan was created
            app_state['charging_plan']['last_calculated'] = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Error updating charging plan: {e}", exc_info=True)
        add_log('ERROR', f'Fehler bei Ladeplan-Berechnung: {str(e)}')


def get_charging_status_explanation():
    """Generate human-readable explanation of charging status (v0.3.6)"""
    try:
        # Get current values
        current_soc = app_state['battery']['soc']
        min_soc = config.get('auto_safety_soc', 20)
        max_soc = config.get('auto_charge_below_soc', 95)
        pv_threshold = config.get('auto_pv_threshold', 5.0)

        # Get PV forecast
        pv_remaining = 0
        if ha_client:
            for roof in ['roof1', 'roof2']:
                sensor = config.get(f'pv_remaining_today_{roof}')
                if sensor:
                    remaining = ha_client.get_state(sensor)
                    if remaining and remaining not in ['unknown', 'unavailable']:
                        pv_remaining += float(remaining)

        # Get planned times
        planned_start = None
        planned_end = None
        target_soc = max_soc
        if app_state['charging_plan'].get('planned_start'):
            planned_start = datetime.fromisoformat(app_state['charging_plan']['planned_start'])
            planned_end = datetime.fromisoformat(app_state['charging_plan']['planned_end'])
            target_soc = app_state['charging_plan'].get('target_soc', max_soc)

        now = datetime.now().astimezone()

        # Check conditions (v0.3.7 - improved labels)
        # ✅ = Normal/OK, ❌ = Problem/Action needed
        conditions = {
            'soc_safe': {
                'fulfilled': current_soc >= min_soc,
                'label': f'Sicherheits-SOC nicht unterschritten ({current_soc:.0f}% ≥ {min_soc}%)' if current_soc >= min_soc else f'Sicherheits-SOC unterschritten ({current_soc:.0f}% < {min_soc}%)',
                'priority': 1
            },
            'below_charge_limit': {
                'fulfilled': current_soc < max_soc,
                'label': f'Lade-Limit nicht erreicht ({current_soc:.0f}% < {max_soc}%)' if current_soc < max_soc else f'Lade-Limit erreicht ({current_soc:.0f}% ≥ {max_soc}%)',
                'priority': 2
            },
            'pv_sufficient': {
                'fulfilled': pv_remaining > pv_threshold,
                'label': f'PV-Ertrag ausreichend ({pv_remaining:.1f} kWh > {pv_threshold:.1f} kWh)' if pv_remaining > pv_threshold else f'PV-Ertrag unzureichend ({pv_remaining:.1f} kWh ≤ {pv_threshold:.1f} kWh)',
                'priority': 3
            },
            'has_plan': {
                'fulfilled': planned_start is not None,
                'label': 'Ladeplan vorhanden' if planned_start else 'Kein Ladeplan berechnet',
                'priority': 4
            }
        }

        # Determine main explanation
        explanation = ""
        will_charge = False

        if current_soc < min_soc:
            # Safety charging
            explanation = f"⚡ Der Speicher wird SOFORT geladen, weil der SOC ({current_soc:.0f}%) unter dem Sicherheitsminimum von {min_soc}% liegt."
            will_charge = True

        elif current_soc >= max_soc:
            # Already full
            explanation = f"✅ Der Speicher wird nicht geladen, weil er bereits bei {current_soc:.0f}% liegt (Ziel: {max_soc}%)."
            will_charge = False

        elif pv_remaining > pv_threshold:
            # Sufficient PV
            explanation = f"☀️ Der Speicher wird nicht aus dem Netz geladen, weil der prognostizierte Solarertrag mit {pv_remaining:.1f} kWh über dem Schwellwert von {pv_threshold:.1f} kWh liegt."
            will_charge = False

        elif planned_start and now >= planned_start:
            # Planned time reached
            if planned_end:
                explanation = f"🔋 Der Speicher wird geladen, sodass er bis {planned_end.strftime('%H:%M')} Uhr bei {target_soc}% ist."
            else:
                explanation = f"🔋 Der Speicher wird jetzt geladen bis {target_soc}% erreicht sind."
            will_charge = True

        elif planned_start and now < planned_start:
            # Waiting for planned time
            explanation = f"⏳ Der Speicher wird ab {planned_start.strftime('%H:%M')} Uhr geladen, sodass er bis {planned_end.strftime('%H:%M')} Uhr bei {target_soc}% ist."
            will_charge = False

        else:
            # No plan
            explanation = f"⏸️ Der Speicher wird nicht geladen. Es wurde kein optimaler Ladezeitpunkt gefunden (Preise bleiben günstig)."
            will_charge = False

        return {
            'explanation': explanation,
            'will_charge': will_charge,
            'conditions': conditions,
            'current_soc': current_soc,
            'target_soc': max_soc,
            'pv_remaining': pv_remaining,
            'planned_start': planned_start.strftime('%H:%M') if planned_start else None,
            'planned_end': planned_end.strftime('%H:%M') if planned_end else None
        }

    except Exception as e:
        logger.error(f"Error generating charging status explanation: {e}")
        return {
            'explanation': '❌ Fehler beim Ermitteln des Ladestatus',
            'will_charge': False,
            'conditions': {},
            'current_soc': 0,
            'target_soc': 0,
            'pv_remaining': 0,
            'planned_start': None,
            'planned_end': None
        }


def get_consumption_kwh(ha_client, consumption_sensor, timestamp):
    """
    Get consumption in kWh for recording, handling both power (W/kW) and energy (kWh) sensors.

    For power sensors (W/kW): Fetches last hour's history, calculates average, converts to kWh
    For energy sensors (kWh): Returns current value directly

    Args:
        ha_client: Home Assistant API client
        consumption_sensor: Sensor entity ID
        timestamp: Current timestamp

    Returns:
        float: Consumption in kWh, or None if error/unavailable
    """
    try:
        # Get sensor info with attributes to determine unit
        sensor_data = ha_client.get_state_with_attributes(consumption_sensor)
        if not sensor_data:
            logger.warning(f"Could not get sensor data for {consumption_sensor}")
            return None

        state = sensor_data.get('state')
        if state in ['unknown', 'unavailable', None]:
            logger.debug(f"Sensor {consumption_sensor} unavailable")
            return None

        # Get unit of measurement
        attributes = sensor_data.get('attributes', {})
        unit = attributes.get('unit_of_measurement', '').upper()

        logger.debug(f"Sensor {consumption_sensor}: state={state}, unit={unit}")

        # Handle different units
        if unit in ['KWH', 'KILOWATTHOUR']:
            # Energy sensor - use value directly
            try:
                consumption_kwh = float(state)
                logger.debug(f"Energy sensor (kWh): {consumption_kwh} kWh")
                return consumption_kwh
            except (ValueError, TypeError):
                logger.warning(f"Could not convert {state} to float")
                return None

        elif unit in ['W', 'WATT', 'KW', 'KILOWATT']:
            # Power sensor - need to calculate average over last hour
            logger.info(f"Power sensor detected ({unit}) - fetching hourly history for accurate consumption")

            # Calculate time range: from 1 hour ago to now
            from datetime import timedelta
            end_time = timestamp
            start_time = timestamp - timedelta(hours=1)

            # Fetch history
            history = ha_client.get_history(consumption_sensor, start_time, end_time)
            if not history or len(history) == 0:
                logger.warning(f"No history data available for {consumption_sensor}")
                # Fallback: use current value as snapshot
                try:
                    current_value = float(state)
                    if unit in ['W', 'WATT']:
                        consumption_kwh = current_value / 1000  # W to kWh (assuming 1 hour)
                    else:  # kW
                        consumption_kwh = current_value  # kW * 1h = kWh
                    logger.warning(f"Using snapshot value: {consumption_kwh:.3f} kWh")
                    return consumption_kwh
                except (ValueError, TypeError):
                    return None

            # Calculate average power from all readings
            valid_values = []
            for entry in history:
                try:
                    value_state = entry.get('state')
                    if value_state not in ['unknown', 'unavailable', None, '']:
                        value = float(value_state)

                        # Skip negative or unrealistically high values
                        if value < 0:
                            continue
                        if value > 1000000:  # > 1 MW seems like an error
                            continue

                        valid_values.append(value)
                except (ValueError, TypeError):
                    continue

            if not valid_values:
                logger.warning(f"No valid values in history for {consumption_sensor}")
                return None

            # Calculate average
            avg_power = sum(valid_values) / len(valid_values)

            # Convert to kWh
            if unit in ['W', 'WATT']:
                consumption_kwh = avg_power / 1000  # W to kW, then * 1h = kWh
            else:  # kW, KILOWATT
                consumption_kwh = avg_power  # kW * 1h = kWh

            logger.info(f"Calculated from {len(valid_values)} samples: avg={avg_power:.1f} {unit} → {consumption_kwh:.3f} kWh")
            return consumption_kwh

        else:
            logger.error(f"⚠️ Unknown sensor unit '{unit}' for {consumption_sensor}. "
                        f"Expected: W, kW, or kWh. Please check sensor configuration.")
            return None

    except Exception as e:
        logger.error(f"Error getting consumption from {consumption_sensor}: {e}", exc_info=True)
        return None


def release_limits_on_shutdown():
    """
    Beim Beenden die Grenzen freigeben.

    Geschriebene Grenzwerte ueberleben das Add-on. Ohne dieses Aufraeumen
    koennte ein gedrosseltes Ladelimit oder ein enger SOC-Korridor
    unbemerkt bestehen bleiben.
    """
    if not modbus_client or modbus_client.dry_run:
        return
    if config.get('charging_strategy', 'forecast') != 'forecast':
        return
    try:
        modbus_client.release_limits(max_power=config.get('max_charge_power'))
    except Exception as e:
        logger.error(f"Konnte Grenzwerte beim Beenden nicht freigeben: {e}")


def publish_plan_to_ha(plan, readback=None):
    """
    Veroeffentlicht den aktuellen Plan als HA-Entitaeten (v0.11.1).

    Damit landet der Zustand im HA-Recorder: Verlauf ueber Wochen,
    Diagramme im Dashboard, Ausloeser fuer Automatisierungen. Das Add-on
    selbst haelt keine Historie - HA kann das ohnehin besser.

    Wird bei jedem Regelzyklus aufgerufen, also alle control_interval
    Sekunden. Fehler hier duerfen die Steuerung nicht stoppen.
    """
    if not ha_client or not plan:
        return

    prefix = config.get('ha_entity_prefix', 'kostal_bm')
    diag = plan.get('diagnostics') or {}
    dry = config.get('dry_run', False)

    entities = [
        (f'sensor.{prefix}_target_soc', plan.get('max_soc'), {
            'friendly_name': 'Batteriemanager Ziel-SOC',
            'unit_of_measurement': '%', 'device_class': 'battery',
            'state_class': 'measurement', 'icon': 'mdi:battery-arrow-up'}),
        (f'sensor.{prefix}_min_soc', plan.get('min_soc'), {
            'friendly_name': 'Batteriemanager Min-SOC',
            'unit_of_measurement': '%', 'device_class': 'battery',
            'state_class': 'measurement', 'icon': 'mdi:battery-arrow-down'}),
        (f'sensor.{prefix}_max_charge_power', plan.get('max_charge_power'), {
            'friendly_name': 'Batteriemanager max. Ladeleistung',
            'unit_of_measurement': 'W', 'device_class': 'power',
            'state_class': 'measurement', 'icon': 'mdi:flash'}),
        (f'sensor.{prefix}_overnight_need', diag.get('overnight_need_kwh'), {
            'friendly_name': 'Batteriemanager Nachtbedarf',
            'unit_of_measurement': 'kWh', 'device_class': 'energy',
            'state_class': 'measurement', 'icon': 'mdi:weather-night'}),
        (f'sensor.{prefix}_tomorrow_shortfall', diag.get('tomorrow_shortfall_kwh'), {
            'friendly_name': 'Batteriemanager Fehlbetrag morgen',
            'unit_of_measurement': 'kWh', 'device_class': 'energy',
            'state_class': 'measurement', 'icon': 'mdi:weather-sunny-alert'}),
        (f'sensor.{prefix}_pv_forecast_today', diag.get('pv_today_kwh'), {
            'friendly_name': 'Batteriemanager PV-Prognose heute',
            'unit_of_measurement': 'kWh', 'device_class': 'energy',
            'state_class': 'measurement', 'icon': 'mdi:solar-power'}),
        # Status traegt die Begruendung als Attribut - so ist im Verlauf
        # nachvollziehbar, WARUM eine Entscheidung fiel.
        (f'sensor.{prefix}_status', plan.get('mode'), {
            'friendly_name': 'Batteriemanager Status',
            'icon': 'mdi:shield-check',
            'begruendung': plan.get('reason'),
            'dry_run': dry,
            'aktueller_soc': plan.get('current_soc'),
            'sonnenuntergang': diag.get('sunset_hour'),
            'register_ist': readback or {},
        }),
    ]

    for entity_id, value, attrs in entities:
        if value is None:
            value = 'unknown'
        try:
            ha_client.set_state(entity_id, value, attrs)
        except Exception as e:
            logger.debug(f"Konnte {entity_id} nicht veroeffentlichen: {e}")


def controller_loop():
    """Background thread for battery control"""
    import time
    logger.info("Controller loop started")

    # Ladeplan-Update Intervall (alle 5 Minuten)
    last_plan_update = None
    plan_update_interval = 300  # 5 Minuten

    # v0.4.0 - Consumption recording (every hour)
    last_consumption_recording = None
    consumption_recording_interval = 3600  # 1 Stunde

    # v0.3.1 - Calculate charging plan immediately on startup
    update_charging_plan()
    last_plan_update = datetime.now()

    while True:
        try:
            # Update charging plan periodically (v0.3.0, enhanced v0.9.0)
            now = datetime.now()
            if (last_plan_update is None or
                (now - last_plan_update).total_seconds() > plan_update_interval):
                update_charging_plan()

                # v0.9.0 - Calculate daily battery schedule with predictive optimization
                # v0.10.0 - Only relevant for the legacy price-based strategy;
                # the forecast strategy uses evaluate_evening_topup() instead.
                if (config.get('charging_strategy', 'price') == 'price'
                        and ha_client and tibber_optimizer and consumption_learner):
                    try:
                        current_soc = read_soc(ha_client, config, fallback=50.0)

                        # Get Tibber prices
                        prices = []
                        tibber_sensor = config.get('tibber_price_sensor', 'sensor.tibber_prices')
                        attrs = ha_client.get_attributes(tibber_sensor)
                        if attrs and 'today' in attrs:
                            prices = attrs['today']

                        # Generate full-day schedule
                        schedule = tibber_optimizer.plan_daily_battery_schedule(
                            ha_client=ha_client,
                            config=config,
                            current_soc=current_soc,
                            prices=prices
                        )

                        if schedule:
                            app_state['daily_battery_schedule'] = schedule
                            logger.info(f"✓ Daily battery schedule updated: "
                                      f"{len(schedule.get('charging_windows', []))} charging windows, "
                                      f"min SOC {schedule.get('min_soc_reached', 0):.1f}%")
                        else:
                            logger.warning("Failed to generate daily battery schedule")

                    except Exception as e:
                        logger.error(f"Error updating daily battery schedule: {e}", exc_info=True)

                last_plan_update = now

            # Record consumption periodically (v0.4.0, improved in v0.7.13)
            if (consumption_learner and ha_client and
                config.get('enable_consumption_learning', True)):
                if (last_consumption_recording is None or
                    (now - last_consumption_recording).total_seconds() > consumption_recording_interval):
                    try:
                        consumption_sensor = config.get('home_consumption_sensor')
                        if consumption_sensor:
                            # Get consumption in kWh, handling W/kW/kWh sensors automatically
                            consumption_kwh = get_consumption_kwh(ha_client, consumption_sensor, now)

                            if consumption_kwh is not None:
                                # Warn user if negative value detected (Kostal Smart Meter bug)
                                if consumption_kwh < 0:
                                    add_log('WARNING', f'⚠️ Negativer Verbrauchswert vom Sensor: {consumption_kwh:.3f} kWh (Kostal Smart Meter Bug - Wert ignoriert)')
                                else:
                                    consumption_learner.record_consumption(now, consumption_kwh)
                                    logger.info(f"✓ Recorded consumption: {consumption_kwh:.3f} kWh at {now.strftime('%H:%M')}")

                                last_consumption_recording = now
                    except Exception as e:
                        logger.error(f"Error recording consumption: {e}", exc_info=True)

            if app_state['controller_running'] and config.get('auto_optimization_enabled', True):
                strategy = config.get('charging_strategy', 'price')

                # v0.10.0 - Prognosebasiertes PV-Shaping (keine Preislogik,
                # KEINE Netzladung). Wir setzen ausschliesslich Grenzwerte
                # (Modbus 1038/1040/1042/1044) und lassen die interne
                # Eigenverbrauchs-Optimierung des Wechselrichters darin laufen.
                if strategy == 'forecast' and ha_client and modbus_client and pv_shaping_planner:
                    try:
                        # Bei unbrauchbarem Sensorwert den letzten bekannten SOC
                        # weiterverwenden - der Zyklus MUSS durchlaufen.
                        current_soc = read_soc(ha_client, config,
                                               fallback=app_state['battery'].get('soc'))
                        if current_soc is None:
                            add_log('WARNING', 'SOC unbekannt und kein Vorwert - Planung uebersprungen')
                            raise _SkipCycle()
                        app_state['battery']['soc'] = current_soc
                        battery_capacity = config.get('battery_capacity', 10.6)

                        plan = pv_shaping_planner.plan(
                            ha_client=ha_client,
                            config=config,
                            current_soc=current_soc,
                            battery_capacity=battery_capacity
                        )
                        app_state['shaping_plan'] = plan

                        report = modbus_client.set_battery_limits(
                            max_charge_power=plan['max_charge_power'],
                            max_discharge_power=plan['max_discharge_power'],
                            min_soc=plan['min_soc'],
                            max_soc=plan['max_soc'],
                        )

                        # Nur loggen, wenn sich der Plan tatsaechlich geaendert
                        # hat - sonst flutet der 30s-Takt das Logbuch.
                        if report['written']:
                            prefix = '[DRY-RUN] ' if modbus_client.dry_run else ''
                            add_log('INFO', f"{prefix}PV-Shaping [{plan['mode']}]: "
                                            f"{', '.join(report['written'])} | {plan['reason']}")
                        if report['failed']:
                            add_log('WARNING', f"Limits konnten nicht geschrieben werden: "
                                               f"{', '.join(report['failed'])}")

                        # Verifikation. Lesen ist gefahrlos und laeuft deshalb
                        # AUCH im Dry-Run - nur so laesst sich vor dem
                        # Scharfschalten pruefen, ob die Limit-Register am
                        # Wechselrichter ueberhaupt ansprechbar sind.
                        if report['written']:
                            readback = modbus_client.read_battery_limits()
                            app_state['limits_readback'] = readback

                            if not readback:
                                add_log('WARNING', 'Limit-Register 1038/1040/1042/1044 nicht '
                                                   'lesbar - der Wechselrichter unterstuetzt sie '
                                                   'moeglicherweise nicht')
                            elif modbus_client.dry_run:
                                # Im Dry-Run zeigen wir Ist gegen Plan, damit
                                # erkennbar ist, was sich aendern wuerde.
                                ist = ' · '.join(f"{k}={v}" for k, v in sorted(readback.items()))
                                add_log('INFO', f'[DRY-RUN] Register-Ist-Zustand: {ist}')
                            else:
                                for key, target in (('max_soc', plan['max_soc']),
                                                    ('min_soc', plan['min_soc']),
                                                    ('max_charge_power', plan['max_charge_power']),
                                                    ('max_discharge_power', plan['max_discharge_power'])):
                                    actual = readback.get(key)
                                    if actual is None:
                                        continue
                                    tolerance = 1.0 if 'soc' in key else 50.0
                                    if abs(actual - target) > tolerance:
                                        add_log('WARNING', f"Register-Rueckmeldung weicht ab: "
                                                           f"{key} gesetzt={target} gelesen={actual}")

                        app_state['inverter']['mode'] = f"shaping_{plan['mode']}"

                        # Plan als HA-Entitaeten veroeffentlichen (Verlauf,
                        # Diagramme, Automatisierungen)
                        if config.get('publish_ha_sensors', True):
                            publish_plan_to_ha(plan, app_state.get('limits_readback'))

                    except _SkipCycle:
                        pass
                    except Exception as e:
                        logger.error(f"Error in PV shaping: {e}", exc_info=True)

                # v0.3.0 - Legacy: Intelligent Tibber-based (price) charging
                elif strategy == 'price' and ha_client and kostal_api and modbus_client and tibber_optimizer:
                    try:
                        # Hole aktuelle Werte
                        current_soc = read_soc(ha_client, config,
                                               fallback=app_state['battery'].get('soc') or 0.0)
                        app_state['battery']['soc'] = current_soc

                        # v0.3.4 - Use existing parameters consistently
                        min_soc = config.get('auto_safety_soc', 20)
                        max_soc = config.get('auto_charge_below_soc', 95)

                        # v0.9.0 - Use daily battery schedule for charging decisions
                        should_charge = False
                        reason = "No action"

                        # Safety check: SOC too low
                        if current_soc < min_soc:
                            should_charge = True
                            reason = f"SAFETY: SOC below minimum ({current_soc:.1f}% < {min_soc}%)"

                        # Safety check: Battery full
                        elif current_soc >= max_soc:
                            should_charge = False
                            reason = f"Battery full ({current_soc:.1f}% >= {max_soc}%)"

                        # Use daily schedule if available
                        elif app_state['daily_battery_schedule']:
                            schedule = app_state['daily_battery_schedule']
                            current_hour = now.hour

                            # Check if current hour is in charging windows
                            charging_windows = schedule.get('charging_windows', [])
                            current_window = None
                            for window in charging_windows:
                                if window['hour'] == current_hour:
                                    current_window = window
                                    break

                            if current_window:
                                should_charge = True
                                reason = (f"Planned charging window: {current_window['charge_kwh']:.2f} kWh "
                                        f"@ {current_window['price']*100:.2f} Cent/kWh "
                                        f"({current_window['reason']})")
                            else:
                                should_charge = False
                                min_soc_forecast = schedule.get('min_soc_reached', 100)
                                reason = f"No charging needed - Schedule OK (min SOC: {min_soc_forecast:.1f}%)"

                        else:
                            # Fallback if no schedule available (v0.8.1 method)
                            planned_start = None
                            if app_state['charging_plan']['planned_start']:
                                planned_start = datetime.fromisoformat(app_state['charging_plan']['planned_start'])

                            should_charge, reason = tibber_optimizer.should_charge_now(
                                planned_start=planned_start,
                                current_soc=current_soc,
                                min_soc=min_soc,
                                max_soc=max_soc,
                                ha_client=ha_client,
                                config=config
                            )

                        # Aktion ausführen
                        if should_charge and app_state['inverter']['mode'] not in ['manual_charging', 'auto_charging']:
                            # Starte automatisches Laden
                            kostal_api.set_external_control(True)
                            charge_power = -config['max_charge_power']
                            modbus_client.write_battery_power(charge_power)
                            app_state['inverter']['mode'] = 'auto_charging'
                            app_state['inverter']['control_mode'] = 'external'
                            add_log('INFO', f'Auto-Optimization started charging: {reason}')

                        elif not should_charge and app_state['inverter']['mode'] == 'auto_charging':
                            # Stoppe automatisches Laden
                            modbus_client.write_battery_power(0)
                            kostal_api.set_external_control(False)
                            app_state['inverter']['mode'] = 'automatic'
                            app_state['inverter']['control_mode'] = 'internal'
                            add_log('INFO', f'Auto-Optimization stopped charging: {reason}')

                    except Exception as e:
                        logger.error(f"Error in auto-optimization: {e}")

            # Sleep for control interval
            time.sleep(config.get('control_interval', 30))

        except Exception as e:
            logger.error(f"Error in controller loop: {e}")
            add_log('ERROR', f'Controller error: {str(e)}')

# Start controller thread
controller_thread = threading.Thread(target=controller_loop, daemon=True)
controller_thread.start()

# Aufraeumen beim Beenden registrieren. Geschriebene Grenzwerte ueberleben
# das Add-on - ohne das hier bliebe eine Drosselung dauerhaft stehen.
# Home Assistant beendet Add-ons per SIGTERM, gunicorn reicht das durch.
atexit.register(release_limits_on_shutdown)
try:
    # Bisherigen Handler merken, damit wir ihn nach unserem Aufraeumen
    # aufrufen koennen statt ihn zu verdraengen.
    _previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _shutdown_handler)
except (ValueError, OSError):
    # In einem Nicht-Haupt-Thread nicht moeglich; atexit greift trotzdem
    logger.debug("SIGTERM-Handler konnte nicht registriert werden")

# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8099))
    logger.info(f"Starting Flask app on port {port}")
    logger.info(f"Inverter: {config['inverter_ip']}:{config['inverter_port']}")
    add_log('INFO', f'Application started on port {port}')
    
    app.run(host='0.0.0.0', port=port, debug=(log_level == 'DEBUG'))
