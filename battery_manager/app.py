#!/usr/bin/env python3
"""
Kostal Battery Manager - Main Flask Application - FIXED VERSION
"""

import os
import json
import logging
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_cors import CORS

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
            static_url_path='/static',
            template_folder='templates')

# Enable CORS for Ingress
CORS(app)

app.config['SECRET_KEY'] = os.urandom(24)

# Configuration
CONFIG_PATH = os.getenv('CONFIG_PATH', '/data/options.json')

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
        'min_soc': 20,
        'max_soc': 95,
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
        'pv_next_hour_roof2': 'sensor.energy_next_hour_roof2'
    }

# Load configuration
config = load_config()

# Global state
app_state = {
    'controller_running': False,
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
    except ImportError:
        # Fall back to absolute import
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from core.kostal_api import KostalAPI
        from core.modbus_client import ModbusClient
        from core.ha_client import HomeAssistantClient
    
    # Initialize components
    kostal_api = KostalAPI(
        config['inverter_ip'],
        config.get('installer_password', ''),
        config.get('master_password', '')
    )
    modbus_client = ModbusClient(
        config['inverter_ip'],
        config['inverter_port']
    )
    ha_client = HomeAssistantClient()

    add_log('INFO', 'Components initialized successfully')

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
    add_log('WARNING', 'Running in development mode - components not available')
except Exception as e:
    logger.error(f"Error initializing components: {e}")
    kostal_api = None
    modbus_client = None
    ha_client = None
    add_log('ERROR', f'Failed to initialize components: {str(e)}')

# ==============================================================================
# Web Routes
# ==============================================================================

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('dashboard.html', config=config, state=app_state)

@app.route('/config')
def config_page():
    """Configuration page"""
    return render_template('config.html', config=config)

@app.route('/logs')
def logs_page():
    """Logs page"""
    return render_template('logs.html', logs=app_state['logs'])

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
        try:
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
        'pv': app_state.get('pv', {'power_now': 0, 'remaining_today': 0})
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
                # Set charge power
                charge_power = -config['max_charge_power']
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

def controller_loop():
    """Background thread for battery control"""
    import time
    logger.info("Controller loop started")

    while True:
        try:
            if app_state['controller_running'] and config.get('auto_optimization_enabled', True):
                # Auto-optimization logic (v0.2.1)
                if ha_client and kostal_api and modbus_client:
                    try:
                        # Get current data from Home Assistant
                        current_price_level = ha_client.get_state(
                            config.get('tibber_price_level_sensor')
                        )
                        current_soc = float(ha_client.get_state(
                            config.get('battery_soc_sensor', 'sensor.zwh8_8500_battery_soc')
                        ) or 0)

                        # Get PV remaining forecast (sum of both roofs) - v0.2.1
                        pv_remaining = 0
                        for roof in ['roof1', 'roof2']:
                            sensor = config.get(f'pv_remaining_today_{roof}')
                            if sensor:
                                remaining = ha_client.get_state(sensor)
                                if remaining and remaining not in ['unknown', 'unavailable']:
                                    pv_remaining += float(remaining)

                        # Update app state
                        if current_price_level:
                            app_state['price']['level'] = current_price_level

                        # Decision logic
                        should_charge = False

                        # Rule 1: Very cheap prices and low SOC
                        # Support both German and English price levels
                        cheap_levels = ['CHEAP', 'VERY_CHEAP', 'günstig', 'sehr günstig']
                        if current_price_level in cheap_levels and \
                           current_soc < config.get('max_soc', 95):
                            # Only charge if low PV forecast (less than 5 kWh expected)
                            if pv_remaining < 5:
                                should_charge = True
                                logger.debug(f"Rule 1: Cheap price ({current_price_level}), " +
                                           f"low PV remaining ({pv_remaining} kWh)")

                        # Rule 2: SOC below minimum (safety)
                        if current_soc < config.get('min_soc', 20):
                            should_charge = True
                            logger.debug(f"Rule 2: SOC {current_soc}% below minimum")

                        # Rule 3: Expensive prices - don't charge
                        expensive_levels = ['EXPENSIVE', 'VERY_EXPENSIVE', 'teuer', 'sehr teuer']
                        if current_price_level in expensive_levels:
                            should_charge = False
                            logger.debug(f"Rule 3: Expensive price ({current_price_level}), " +
                                       "not charging")

                        # Execute action
                        if should_charge and app_state['inverter']['mode'] not in \
                           ['manual_charging', 'auto_charging']:
                            # Start charging
                            kostal_api.set_external_control(True)
                            charge_power = -config['max_charge_power']
                            modbus_client.write_battery_power(charge_power)
                            app_state['inverter']['mode'] = 'auto_charging'
                            add_log('INFO',
                                  f'Auto-Optimization: Started charging at {current_price_level}')

                        elif not should_charge and app_state['inverter']['mode'] == 'auto_charging':
                            # Stop charging
                            modbus_client.write_battery_power(0)
                            kostal_api.set_external_control(False)
                            app_state['inverter']['mode'] = 'automatic'
                            add_log('INFO', 'Auto-Optimization: Stopped charging')

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

# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8099))
    logger.info(f"Starting Flask app on port {port}")
    logger.info(f"Inverter: {config['inverter_ip']}:{config['inverter_port']}")
    add_log('INFO', f'Application started on port {port}')
    
    app.run(host='0.0.0.0', port=port, debug=(log_level == 'DEBUG'))
