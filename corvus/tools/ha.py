"""Home Assistant tools — direct functions for smart home control.

Ported from mcp_servers/ha_server.py. These functions will be registered
as @tool functions when the Claude Agent SDK is available.

Tools:
    ha_list_entities — List entities, optionally filtered by domain
    ha_get_state     — Get detailed state of a specific entity
    ha_call_service  — Call a service to control a device (CONFIRM-GATED)

Configuration:
    Call configure(ha_url, ha_token) before using any tool.
"""

from typing import Any

import requests

from corvus.tools.response import make_error_response, make_tool_response

# Module-level configuration set via configure()
_ha_url: str | None = None
_ha_token: str | None = None


def configure(ha_url: str, ha_token: str) -> None:
    """Set the HA API base URL and authentication token.

    Args:
        ha_url: Home Assistant base URL (e.g., "http://homeassistant.local:8123").
        ha_token: Long-lived access token for the HA REST API.
    """
    global _ha_url, _ha_token  # noqa: PLW0603
    _ha_url = ha_url.rstrip("/")
    _ha_token = ha_token


def _get_config() -> tuple[str, str]:
    """Return (url, token) or raise if not configured."""
    if _ha_url is None or _ha_token is None:
        raise RuntimeError("HA tools not configured. Call gateway.tools.ha.configure(url, token) first.")
    return _ha_url, _ha_token


def _ha_request(method: str, path: str, data: dict[str, Any] | None = None) -> dict | list:
    """Make an authenticated request to the HA REST API."""
    url, token = _get_config()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"{url}{path}", headers=headers, json=data, timeout=10)
    resp.raise_for_status()
    result: dict | list = resp.json()
    return result


def _format_entity(state: dict[str, Any]) -> dict[str, Any]:
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


# NOTE: When claude_agent_sdk is available, decorate these with @tool.
# Tests call these functions directly, so they work with or without the SDK.


def ha_list_entities(domain: str | None = None) -> dict[str, Any]:
    """List Home Assistant entities, optionally filtered by domain.

    Args:
        domain: Entity domain filter (e.g., "light", "switch", "sensor").
                 Omit or pass None for all entities.

    Returns:
        Tool response with count and entities array.
    """
    try:
        raw_states = _ha_request("GET", "/api/states")
        states: list[dict[str, Any]] = raw_states if isinstance(raw_states, list) else []
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        entities = [_format_entity(s) for s in states]
        return make_tool_response({"count": len(entities), "entities": entities})
    except requests.exceptions.ConnectionError:
        return make_error_response("Home Assistant is unreachable. Check if homeassistant.local is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Home Assistant API error: {e.response.status_code} {e.response.text}")


def ha_get_state(entity_id: str) -> dict[str, Any]:
    """Get the current state and attributes of a specific HA entity.

    Args:
        entity_id: Full entity ID (e.g., "light.living_room").

    Returns:
        Tool response with the full entity state dict.
    """
    try:
        raw_state = _ha_request("GET", f"/api/states/{entity_id}")
        state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
        return make_tool_response(state)
    except requests.exceptions.ConnectionError:
        return make_error_response("Home Assistant is unreachable. Check if homeassistant.local is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Home Assistant API error: {e.response.status_code} {e.response.text}")


def ha_call_service(
    domain: str,
    service: str,
    entity_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Home Assistant service to control a device. CONFIRM-GATED.

    Args:
        domain: Service domain (e.g., "light", "switch", "climate").
        service: Service name (e.g., "turn_on", "turn_off", "set_temperature").
        entity_id: Target entity ID (optional, included in service data).
        data: Additional service data (e.g., {"brightness": 128}).

    Returns:
        Tool response confirming the service call.
    """
    try:
        service_data = dict(data) if data else {}
        if entity_id:
            service_data["entity_id"] = entity_id

        _ha_request("POST", f"/api/services/{domain}/{service}", service_data)

        return make_tool_response(
            {
                "status": "ok",
                "service_called": f"{domain}.{service}",
                "entity_id": entity_id,
                "data": service_data,
            }
        )
    except requests.exceptions.ConnectionError:
        return make_error_response("Home Assistant is unreachable. Check if homeassistant.local is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Home Assistant API error: {e.response.status_code} {e.response.text}")
