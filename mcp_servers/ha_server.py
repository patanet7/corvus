"""Home Assistant MCP stdio server — 3 tools for smart home control.

Runs as a subprocess of the Claw gateway, communicating via stdin/stdout JSON-RPC.
Credentials are read from environment variables (HA_URL, HA_TOKEN).

Tools:
  ha_list_entities  — List entities, optionally filtered by domain
  ha_get_state      — Get detailed state of a specific entity
  ha_call_service   — Call a service to control a device (CONFIRM-GATED)
"""

import json
import logging
import os
import sys

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("ha-mcp")

server = Server("homeassistant")


# --- Helper functions (testable independently) ---


def _format_entity(state: dict) -> dict:
    """Format an HA state dict into a clean entity summary."""
    return {
        "entity_id": state.get("entity_id", ""),
        "state": state.get("state", ""),
        "friendly_name": state.get("attributes", {}).get("friendly_name", ""),
        "attributes": state.get("attributes", {}),
    }


def _filter_entities_by_domain(states: list[dict], domain: str | None) -> list[dict]:
    """Filter entity states by domain prefix."""
    if not domain:
        return states
    return [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]


def _ha_request(method: str, path: str, data: dict | None = None) -> dict | list:
    """Make an authenticated request to the HA REST API."""
    url = os.environ["HA_URL"].rstrip("/") + path
    headers = {
        "Authorization": f"Bearer {os.environ['HA_TOKEN']}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()


# --- MCP Tool Definitions ---


TOOLS = [
    Tool(
        name="ha_list_entities",
        description=(
            "List Home Assistant entities. Optionally filter by domain "
            "(light, switch, sensor, climate, lock, automation, etc.)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": (
                        "Entity domain filter (e.g., 'light', 'switch', 'sensor', "
                        "'climate', 'lock'). Omit for all entities."
                    ),
                },
                "area": {
                    "type": "string",
                    "description": "Filter by area name (e.g., 'Living Room', 'Kitchen')",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="ha_get_state",
        description=(
            "Get the current state and attributes of a specific Home Assistant entity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": (
                        "Full entity ID (e.g., 'light.living_room', "
                        "'climate.thermostat', 'sensor.outdoor_temp')"
                    ),
                },
            },
            "required": ["entity_id"],
        },
    ),
    Tool(
        name="ha_call_service",
        description=(
            "Call a Home Assistant service to control a device or run an automation. "
            "REQUIRES USER CONFIRMATION. Examples: turn_on, turn_off, set_temperature, "
            "lock, unlock, trigger."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g., 'light', 'switch', 'climate', 'lock', 'automation')",
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'turn_on', 'turn_off', 'set_temperature', 'lock', 'trigger')",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Target entity ID",
                },
                "data": {
                    "type": "object",
                    "description": 'Service data (e.g., {"brightness": 128}, {"temperature": 72})',
                },
            },
            "required": ["domain", "service"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "ha_list_entities":
            states = _ha_request("GET", "/api/states")
            domain_filter = arguments.get("domain")
            filtered = _filter_entities_by_domain(states, domain_filter)
            entities = [_format_entity(s) for s in filtered]
            return [TextContent(
                type="text",
                text=json.dumps({"count": len(entities), "entities": entities}),
            )]

        elif name == "ha_get_state":
            entity_id = arguments["entity_id"]
            state = _ha_request("GET", f"/api/states/{entity_id}")
            return [TextContent(type="text", text=json.dumps(state))]

        elif name == "ha_call_service":
            domain = arguments["domain"]
            service = arguments["service"]
            service_data = arguments.get("data", {})
            if "entity_id" in arguments:
                service_data["entity_id"] = arguments["entity_id"]
            _ha_request("POST", f"/api/services/{domain}/{service}", service_data)
            return [TextContent(type="text", text=json.dumps({
                "status": "ok",
                "service_called": f"{domain}.{service}",
                "entity_id": arguments.get("entity_id"),
                "data": service_data,
            }))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except requests.exceptions.ConnectionError:
        return [TextContent(type="text", text=json.dumps({
            "error": "Home Assistant is unreachable. Check if homeassistant.local is online.",
        }))]
    except requests.exceptions.HTTPError as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Home Assistant API error: {e.response.status_code} {e.response.text}",
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
