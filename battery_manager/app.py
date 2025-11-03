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
        'battery_soc_sensor': 'sensor.zwh8_8500_battery_soc'
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
    
    return jsonify({
        'status': 'ok',
        'timestamp': app_state['last_update'],
        'controller_running': app_state['controller_running'],
        'inverter': app_state['inverter'],
        'battery': app_state['battery'],
        'price': app_state['price'],
        'forecast': app_state['forecast']
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
    logger.info("Controller loop started")
    
    while True:
        try:
            if app_state['controller_running']:
                # TODO: Implement automatic optimization logic
                pass
            
            # Sleep for control interval
            import time
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
