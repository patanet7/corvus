# Home Assistant API Reference

## Entity IDs
Format: `<domain>.<name>`, e.g., `light.living_room`, `switch.office_fan`, `sensor.temperature`.

## Common Domains
- `light` — Lights (turn_on, turn_off, toggle)
- `switch` — Switches (turn_on, turn_off, toggle)
- `sensor` — Sensors (read-only state)
- `climate` — Thermostats (set_temperature, set_hvac_mode)
- `media_player` — Media devices (play, pause, volume)

## Service Call Data
The `--data` parameter accepts a JSON string, e.g.:
- Turn on a light at 50% brightness: `--data '{"brightness_pct": 50}'`
- Set thermostat: `--data '{"temperature": 72, "hvac_mode": "heat"}'`

## Confirmation
`call_service` is confirm-gated — destructive actions require user approval.
