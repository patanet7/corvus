---
name: ha
description: Control and monitor Home Assistant entities. List devices, check states, and call services to control smart home.
allowed-tools: Bash(python *)
user-invocable: false
---

# Home Assistant Tools

Control smart home devices via Home Assistant. For detailed API information, see [reference.md](reference.md).

## Available Actions

Run via: `python .claude/skills/ha/scripts/ha.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `list_entities` | `--domain <domain>` | List entities, optionally filtered by domain (light, switch, sensor, etc.) |
| `get_state` | `--entity_id <id>` | Get current state and attributes of an entity |
| `call_service` | `--domain <domain>` `--service <service>` `--entity_id <id>` `--data <json>` | Call a HA service (e.g., turn_on, turn_off). **Requires confirmation.** |
