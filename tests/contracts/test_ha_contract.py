"""Contract tests for HA tools against a fake HA REST API server.

NO mocks. Real HTTP requests to a real BaseHTTPRequestHandler server.
Tests verify the tool→API contract: input shapes, output shapes, status codes.
"""

import json

import pytest

from corvus.tools.ha import (
    _ha_request,
    configure,
    ha_call_service,
    ha_get_state,
    ha_list_entities,
)
from tests.contracts.fake_ha_api import (
    FAKE_TOKEN,
    SAMPLE_ENTITIES,
    FakeHAHandler,
    start_fake_ha_server,
)


@pytest.fixture(autouse=True)
def _ha_server():
    """Start a fresh fake HA server and configure the tools module for each test."""
    server, base_url = start_fake_ha_server()
    configure(base_url, FAKE_TOKEN)
    FakeHAHandler.service_calls.clear()
    yield base_url
    server.shutdown()


def _parse_tool_content(result: dict) -> dict:
    """Extract and parse the JSON text from a tool response."""
    return json.loads(result["content"][0]["text"])


class TestHAListEntities:
    """Contract: ha_list_entities → GET /api/states with optional domain filter."""

    def test_returns_all_entities(self):
        result = ha_list_entities()
        data = _parse_tool_content(result)
        assert data["count"] == len(SAMPLE_ENTITIES)
        assert len(data["entities"]) == data["count"]

    def test_each_entity_has_required_fields(self):
        result = ha_list_entities()
        data = _parse_tool_content(result)
        for entity in data["entities"]:
            assert "entity_id" in entity
            assert "state" in entity
            assert "friendly_name" in entity
            assert "attributes" in entity

    def test_filter_by_domain_light(self):
        result = ha_list_entities(domain="light")
        data = _parse_tool_content(result)
        assert data["count"] == 2
        for entity in data["entities"]:
            assert entity["entity_id"].startswith("light.")

    def test_filter_by_domain_sensor(self):
        result = ha_list_entities(domain="sensor")
        data = _parse_tool_content(result)
        assert data["count"] == 2
        for entity in data["entities"]:
            assert entity["entity_id"].startswith("sensor.")

    def test_filter_by_domain_switch(self):
        result = ha_list_entities(domain="switch")
        data = _parse_tool_content(result)
        assert data["count"] == 1
        assert data["entities"][0]["entity_id"] == "switch.kitchen"

    def test_filter_by_domain_no_match(self):
        result = ha_list_entities(domain="lock")
        data = _parse_tool_content(result)
        assert data["count"] == 0
        assert data["entities"] == []

    def test_no_domain_filter_returns_all(self):
        result = ha_list_entities(domain=None)
        data = _parse_tool_content(result)
        assert data["count"] == len(SAMPLE_ENTITIES)

    def test_entity_friendly_name_preserved(self):
        result = ha_list_entities(domain="light")
        data = _parse_tool_content(result)
        names = {e["friendly_name"] for e in data["entities"]}
        assert "Living Room Light" in names
        assert "Bedroom Light" in names

    def test_response_shape(self):
        """Tool response matches standard format: {content: [{type, text}]}."""
        result = ha_list_entities()
        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        # text should be valid JSON
        json.loads(result["content"][0]["text"])


class TestHAGetState:
    """Contract: ha_get_state → GET /api/states/{entity_id}."""

    def test_returns_full_entity(self):
        result = ha_get_state("light.living_room")
        data = _parse_tool_content(result)
        assert data["entity_id"] == "light.living_room"
        assert data["state"] == "on"
        assert data["attributes"]["friendly_name"] == "Living Room Light"
        assert data["attributes"]["brightness"] == 255

    def test_sensor_entity(self):
        result = ha_get_state("sensor.outdoor_temp")
        data = _parse_tool_content(result)
        assert data["entity_id"] == "sensor.outdoor_temp"
        assert data["state"] == "42.5"
        assert data["attributes"]["unit_of_measurement"] == "°F"

    def test_climate_entity(self):
        result = ha_get_state("climate.thermostat")
        data = _parse_tool_content(result)
        assert data["entity_id"] == "climate.thermostat"
        assert data["state"] == "heat"
        assert data["attributes"]["temperature"] == 72
        assert data["attributes"]["current_temperature"] == 69.5

    def test_unknown_entity_returns_error(self):
        result = ha_get_state("light.nonexistent")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "404" in data["error"]

    def test_response_shape(self):
        result = ha_get_state("light.living_room")
        assert "content" in result
        assert result["content"][0]["type"] == "text"


class TestHACallService:
    """Contract: ha_call_service → POST /api/services/{domain}/{service}."""

    def test_basic_service_call(self):
        result = ha_call_service(
            domain="light",
            service="turn_on",
            entity_id="light.living_room",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["service_called"] == "light.turn_on"
        assert data["entity_id"] == "light.living_room"

    def test_service_call_with_data(self):
        result = ha_call_service(
            domain="light",
            service="turn_on",
            entity_id="light.living_room",
            data={"brightness": 128},
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["data"]["brightness"] == 128
        assert data["data"]["entity_id"] == "light.living_room"

    def test_service_call_recorded_on_server(self):
        ha_call_service(
            domain="switch",
            service="turn_off",
            entity_id="switch.kitchen",
        )
        assert len(FakeHAHandler.service_calls) == 1
        call = FakeHAHandler.service_calls[0]
        assert call["domain"] == "switch"
        assert call["service"] == "turn_off"
        assert call["data"]["entity_id"] == "switch.kitchen"

    def test_climate_set_temperature(self):
        result = ha_call_service(
            domain="climate",
            service="set_temperature",
            entity_id="climate.thermostat",
            data={"temperature": 72},
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["service_called"] == "climate.set_temperature"

        call = FakeHAHandler.service_calls[-1]
        assert call["data"]["temperature"] == 72

    def test_service_call_without_entity_id(self):
        result = ha_call_service(
            domain="automation",
            service="trigger",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["entity_id"] is None

    def test_multiple_service_calls_recorded(self):
        ha_call_service(domain="light", service="turn_on", entity_id="light.living_room")
        ha_call_service(domain="light", service="turn_off", entity_id="light.bedroom")
        assert len(FakeHAHandler.service_calls) == 2

    def test_response_shape(self):
        result = ha_call_service(domain="light", service="turn_on")
        assert "content" in result
        assert result["content"][0]["type"] == "text"


class TestHAAuth:
    """Contract: all endpoints require valid Bearer token."""

    def test_missing_token_returns_error(self, _ha_server):
        """Configure with a bad token → tools should return HTTP error."""
        configure(_ha_server, "wrong-token")
        result = ha_list_entities()
        data = _parse_tool_content(result)
        assert "error" in data
        assert "401" in data["error"]

    def test_get_state_bad_token(self, _ha_server):
        configure(_ha_server, "wrong-token")
        result = ha_get_state("light.living_room")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "401" in data["error"]

    def test_call_service_bad_token(self, _ha_server):
        configure(_ha_server, "wrong-token")
        result = ha_call_service(domain="light", service="turn_on")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "401" in data["error"]


class TestHAConfigError:
    """Contract: tools error gracefully when not configured."""

    def test_unconfigured_raises(self):
        from corvus.tools import ha as ha_module

        # Reset config
        ha_module._ha_url = None
        ha_module._ha_token = None

        with pytest.raises(RuntimeError, match="not configured"):
            _ha_request("GET", "/api/states")
