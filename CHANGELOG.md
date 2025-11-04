# Changelog

## [0.3.7] - 2025-11-03

### Fixed
- Improved condition labels to be more positive and intuitive
- "SOC unter Sicherheitsminimum" → "Sicherheits-SOC nicht unterschritten" (when OK)
- "Batterie bereits voll" → "Lade-Limit nicht erreicht/erreicht"
- Added actual values to all condition labels for better transparency
- Fixed logic error where 10% was shown as "< 10%"

### Changed
- Removed redundant "Geplante Ladezeit erreicht" condition
- Conditions now use: ✅ = Normal/OK, ❌ = Problem/Action needed
- All labels now show actual values in comparison (e.g., "17% ≥ 10%")

### Examples
Before:
- ❌ SOC unter Sicherheitsminimum (10% < 10%) ← Wrong!
- ❌ Batterie bereits voll (10% ≥ 100%) ← Confusing!
- ❌ Geplante Ladezeit erreicht ← Redundant

After:
- ✅ Sicherheits-SOC nicht unterschritten (17% ≥ 10%) ← Clear!
- ✅ Lade-Limit nicht erreicht (45% < 95%) ← Better!
- ✅ PV-Ertrag ausreichend (12.0 kWh > 5.0 kWh) ← Informative!

## [0.3.6] - 2025-11-03

### Added
- **Dynamic charging status explanation** on dashboard showing WHY and WHEN battery will be charged
- New "Ladestatus" card with human-readable explanation
- Visual condition checkboxes with green checkmarks (✅) and red crosses (❌)
- Shows all relevant conditions:
  - SOC below safety minimum
  - Battery already full
  - Sufficient PV expected
  - Planned charging time reached
  - Charging plan available
- Auto-updates every 5 seconds for real-time status
- New API endpoint `/api/charging_status` for detailed charging decision logic

### Examples
Status texts dynamically generated:
- "⚡ Der Speicher wird SOFORT geladen, weil der SOC (15%) unter dem Sicherheitsminimum von 20% liegt."
- "⏳ Der Speicher wird ab 01:34 Uhr geladen, sodass er bis 04:00 Uhr bei 95% ist."
- "☀️ Der Speicher wird nicht aus dem Netz geladen, weil der prognostizierte Solarertrag mit 12 kWh über dem Schwellwert von 5 kWh liegt."
- "✅ Der Speicher wird nicht geladen, weil er bereits bei 96% liegt (Ziel: 95%)."

### Technical
- Added `get_charging_status_explanation()` function for status generation
- Condition evaluation with priority system
- Integrated with existing charging decision logic

## [0.3.5] - 2025-11-03

### Added
- Comprehensive CONFIGURATION.md documentation explaining all parameters
- Detailed inline comments for all automation parameters
- Better explanation of `auto_charge_below_soc` (means "charge UP TO this SOC", not "charge only when below")

### Changed
- `battery_soc_sensor` is now visible and required in configuration (was hidden/optional before)
- Improved parameter descriptions with German explanations
- Added section headers in config.yaml for better organization

### Documentation
- Created detailed CONFIGURATION.md with:
  - Explanation of all SOC parameters and their meaning
  - Tibber smart charging parameter details
  - Example scenarios and calculations
  - Troubleshooting common issues
- Clarified that `auto_charge_below_soc` is the TARGET SOC (charge UP TO), not a condition
- Explained `auto_safety_soc` as immediate charging trigger (charge WHEN BELOW)

## [0.3.4] - 2025-11-03

### Fixed
- Removed redundant `min_soc` and `max_soc` parameters that were conflicting with existing parameters
- Now consistently uses `auto_safety_soc` as safety minimum (default 20%)
- Now consistently uses `auto_charge_below_soc` as target SOC (default 95%)

### Removed
- Config parameters `min_soc` and `max_soc` (use existing `auto_safety_soc` and `auto_charge_below_soc` instead)

### Changed
- Charging plan calculation and controller now use the same SOC parameters as other automation logic
- Better consistency across the entire application

## [0.3.3] - 2025-11-03

### Fixed
- **Critical:** Fixed timezone comparison error preventing charging plan calculation
- Changed `datetime.now()` to `datetime.now().astimezone()` for timezone-aware comparisons
- Resolved "can't compare offset-naive and offset-aware datetimes" error
- Charging plan calculation now works correctly with Tibber price data

### Technical
- All datetime comparisons in TibberOptimizer are now timezone-aware
- Properly handles timezone information from Tibber sensor data (UTC/ISO format)

## [0.3.2] - 2025-11-03

### Fixed
- Significantly improved logging for charging plan calculation to identify issues
- Added detailed error messages when calculation fails
- Now logs each step: checking prerequisites, fetching price data, analyzing prices
- Marks `last_calculated` even when no optimal plan is found

### Added
- Manual "Neu berechnen" button in charging plan card for testing
- New API endpoint `/api/recalculate_plan` to manually trigger calculation
- Better visibility of why charging plan calculation succeeds or fails

### Improved
- Logging now shows: number of prices (today/tomorrow), sensor names, missing data
- Error messages appear in system logs AND in dashboard logs
- Helps diagnose issues with Tibber sensor or missing price data

## [0.3.1] - 2025-11-03

### Changed
- Charging plan calculation now runs immediately on startup (not after 5 minutes)
- Improved documentation for `input_datetime` helpers in config.yaml

### Documentation
- Added detailed explanation of optional Home Assistant `input_datetime` integration
- Explained that input_datetime helpers must be created manually in HA configuration.yaml
- Added example YAML configuration for creating the helpers
- Clarified that input_datetime integration is optional and addon works without it

## [0.3.0] - 2025-11-03

### Added
- **Intelligent Tibber-based charging optimization** - Advanced price analysis for optimal charging
- Automatic detection of price increase point (end of cheap period)
- Backward calculation of optimal charging start time based on battery SOC
- Charging plan display in dashboard showing planned start/end times and last calculation
- New `TibberOptimizer` core module for smart charging logic
- Support for configurable price thresholds:
  - `tibber_price_threshold_1h`: Price increase threshold vs previous hour (default 8%)
  - `tibber_price_threshold_3h`: 3-hour block comparison threshold (default 8%)
  - `charge_duration_per_10_percent`: Charging time per 10% SOC (default 18 minutes)
  - `min_soc`: Minimum safety SOC (default 20%)
  - `max_soc`: Maximum target SOC (default 95%)
- Optional Home Assistant input_datetime integration for charging plan visualization
- New API endpoint `/api/charging_plan` for charging schedule information
- Periodic charging plan updates (every 5 minutes)

### Changed
- Auto-optimization mode now uses sophisticated price trend analysis instead of simple price levels
- Controller considers both price trends (1h and 3h windows) and PV forecast
- Charging starts automatically at calculated optimal time
- Charging stops when price increases or battery reaches max SOC
- Enhanced `/api/status` endpoint now includes charging plan information

### Technical
- Ported Home Assistant automation logic to Python for standalone operation
- Added charging plan calculation with timezone-aware datetime handling
- Integration with Home Assistant `input_datetime` helpers (optional)
- Improved error handling for missing/invalid price data
- Fallback behavior when no optimal charging time is found
- Comprehensive logging for all charging decisions
- Manual charging control remains fully functional alongside automatic optimization

## [0.2.7] - 2025-11-03

### Fixed
- Dashboard now displays correct SOC parameters (`auto_safety_soc` and `auto_charge_below_soc` instead of removed `min_soc`/`max_soc`)
- Updated labels: "Sicherheits-SOC" and "Lade-Limit" for better clarity

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
