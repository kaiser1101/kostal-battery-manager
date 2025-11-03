# Changelog

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
