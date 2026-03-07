# HA Manager Skill Design

**Date:** 2026-02-28
**Status:** Approved

## Problem

The ha-config-analyzer MCP server (from ha-pilot plugin) requires `HA_CONFIG_PATH` — a local path to HA YAML config files. Our HA runs HAOS (VM-based), so there are no local YAML files. Every MCP tool call fails with "HA_CONFIG_PATH environment variable not set."

We need a way to manage HA entities, devices, areas, automations, and diagnostics from Claude Code sessions.

## Decision

Build a **Claude Code skill** (not MCP) that wraps HA REST + WebSocket APIs via bash (curl + websocat). The skill provides reusable command patterns that Claude can execute directly.

## Capabilities

| Category | Operations | API |
|----------|-----------|-----|
| Entity Management | List, get state, rename, hide/unhide, disable/enable, assign area | REST + WS |
| Device Management | List, rename, assign area | WS |
| Area/Floor Management | List, create, update, delete | WS |
| Service Calls | Any HA service (lights, climate, automations) | REST |
| Automation | List, trigger, create, update, delete, reload | REST |
| Config Validation | Check config, core info | REST + SSH |
| Logs & Diagnostics | Error log, entity history, logbook | REST + SSH |
| Templates | Render Jinja2 templates | REST |
| Reload vs Restart | Decision matrix + commands per domain | REST + SSH |

## Credential Safety

All bash patterns read the token server-side:
```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-)
```
Token never appears in Claude Code tool output.

## Location

```
.claude/plugins/ha-pilot/skills/ha-manager/SKILL.md
```

## Cleanup

- Remove ha-config-analyzer MCP from project `.mcp.json`
- Keep ha-pilot plugin directory for colocated skills
- Other ha-pilot skills (api, cli, yaml, etc.) remain as reference material

## HA Access

- REST API: `http://192.168.1.49:8123/api/`
- WebSocket: `ws://192.168.1.49:8123/api/websocket`
- SSH (after add-on install): `ssh root@homeassistant.local`
- websocat: already installed (`/opt/homebrew/bin/websocat` v1.14.1)

## Areas (current)

bathroom, bathroom_2, bedroom, coffee, hallway, janice_office, kitchen, living_room, off, office, primary_bedroom, servrr, office_stream, streaming
