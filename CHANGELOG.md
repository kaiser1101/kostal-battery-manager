# Changelog

## [0.2.6] - 2025-11-03

### Changed
- Removed duplicate SOC parameters `min_soc` and `max_soc` (now only using `auto_safety_soc` and `auto_charge_below_soc` for clarity)
- Renamed "Modus" to "Status" in status overview with German labels:
  - "Standby" (statt "automatic")
  - "Lädt (manuell)" (statt "manual_charging")
  - "Lädt (Auto)" (statt "auto_charging")
- Removed redundant "Steuerung" display from status overview

### Removed
- Config parameters `min_soc` and `max_soc` (replaced by clearer `auto_safety_soc` and `auto_charge_below_soc`)

## [0.2.5] - 2025-11-03

### Added
- Automation status display in status overview
- Toggle switch for automation (replaces button)
- Configurable automation parameters:
  - `auto_pv_threshold`: PV forecast threshold (default 5.0 kWh)
  - `auto_charge_below_soc`: Maximum SOC for charging (default 95%)
  - `auto_safety_soc`: Safety minimum SOC (default 20%)
- New API endpoint: `/api/control` with `toggle_automation` action

### Changed
- Automation is now ON by default on startup
- Controller logic uses configurable parameters instead of hardcoded values
- Improved automation status visibility with toggle switch and status indicator
- Button replaced with professional toggle switch for better UX

### UI
- Real-time automation status display (AN/AUS with colored dot)
- Toggle switch shows current state and allows easy on/off control
- Automation parameters now configurable in addon configuration

## [0.2.4] - 2025-11-03

### Fixed
- Charging power slider value now correctly applied when starting charge
- Previously always used max_charge_power, now uses slider value
- Dark mode text visibility significantly improved with white text

### Changed
- Improved dark mode: All text now white (#ffffff) for better readability
- Labels and secondary text in light gray (#cccccc) in dark mode

## [0.2.3] - 2025-11-03

### Added
- Automatic connection test on startup
- Intelligent battery status display with charging/discharging/standby states

### Changed
- Price display now in Cents instead of Euro for better readability
- Removed navigation menu for cleaner UI (Dashboard, Konfiguration, Logs links)
- Removed "Verbindung testen" button - now automatic on startup
- Improved dark mode contrast (darker background, pure white text)

### UI
- Battery power status: "Batterie wird geladen/entladen: xxxx W" or "Batterie in Standby"
- Price display: "XX.XX Cent/kWh" instead of "0.XXXX €/kWh"
- Better visibility in dark mode with improved contrast
- Simplified header with only title

## [0.2.2] - 2025-11-03

### Fixed
- Tibber current price now correctly read from sensor state
- Tibber price level correctly read from German level sensor
- Average price calculation from Tibber attributes working
- PV forecast tomorrow now displays correctly (sum of both roofs)

### Changed
- Simplified Tibber price reading logic (removed complex timezone parsing)
- Controller now supports both German and English price levels
- Added automatic dark/light mode detection
- Light mode is now the default for better readability

### UI
- Automatic dark mode activation when system prefers dark color scheme
- Better contrast in both light and dark mode
- Improved overall readability

## [0.2.1] - 2025-11-03

### Changed
- Update interval reduced from 10s to 2s for more responsive UI
- Improved Tibber price parsing to correctly show current price from hourly price array
- Added support for dual-roof PV systems (separate sensors for each roof orientation)
- PV forecast now sums production from both roof orientations
- Price level strings now use English format (CHEAP, EXPENSIVE, etc.)

### Removed
- SOC synchronization feature removed (min/max SOC should be configured directly in inverter)
- Removed `/api/sync_soc` endpoint
- Removed `set_battery_soc_limits()` method from kostal_api
- Removed SOC sync button from dashboard

### Fixed
- Current electricity price now correctly displayed from Tibber sensor attributes
- PV forecast calculation for systems with multiple roof orientations
- Timezone handling for Tibber price matching

### Technical
- Added `get_state_with_attributes()` method to ha_client for full entity data retrieval
- New PV sensor configuration: `pv_power_now_roof1/2`, `pv_remaining_today_roof1/2`, etc.
- Removed legacy `pv_forecast_sensor` and `consumption_sensor` options

## [0.2.0] - 2025-11-03

### Added
- Live battery power display from Home Assistant sensor
- Battery voltage sensor integration (optional)
- SOC limit synchronization to inverter (min/max SOC)
- Live charging power adjustment during active charging
- Automatic optimization mode based on Tibber price levels
- PV forecast integration for smart charging decisions
- New configuration options for sensors and automation:
  - `battery_power_sensor`: Real-time battery power monitoring
  - `battery_voltage_sensor`: Battery voltage monitoring (optional)
  - `tibber_price_sensor`: Tibber price data
  - `tibber_price_level_sensor`: Price level classification
  - `pv_forecast_sensor`: PV generation forecast
  - `consumption_sensor`: Consumption data
  - `auto_optimization_enabled`: Enable/disable automatic optimization
- New API endpoints:
  - `/api/sync_soc`: Synchronize SOC limits to inverter
  - `/api/adjust_power`: Adjust charging power during active charging
- SOC synchronization button in dashboard

### Changed
- Dashboard now shows real-time battery power
- Power slider can adjust charging power during active charging sessions
- Controller loop now includes intelligent auto-optimization logic
- Improved error handling in API endpoints
- Enhanced sensor integration with fallback mechanisms

### Fixed
- Improved error handling for missing or unavailable sensors
- Better state management for charging modes

## [0.1.1] - 2025-10-XX

### Fixed
- Connection test and CORS issues
- Authentication flow improvements

## [0.1.0] - 2025-10-XX

### Added
- Initial release
- Basic battery control via Kostal API
- Modbus TCP integration for charging control
- Home Assistant integration
- Manual charging control
- Tibber integration for price optimization
- Web dashboard with real-time status
