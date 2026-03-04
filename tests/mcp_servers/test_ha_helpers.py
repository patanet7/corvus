"""Behavioral tests for HA helper functions — real data structures, NO mocks."""

from corvus.tools.ha import _filter_entities_by_domain, _format_entity


class TestFormatEntity:
    def test_formats_basic_entity(self):
        state = {
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {
                "friendly_name": "Living Room Light",
                "brightness": 255,
            },
        }
        result = _format_entity(state)
        assert result["entity_id"] == "light.living_room"
        assert result["state"] == "on"
        assert result["friendly_name"] == "Living Room Light"
        assert result["attributes"]["brightness"] == 255

    def test_missing_friendly_name(self):
        state = {
            "entity_id": "sensor.temp",
            "state": "72",
            "attributes": {},
        }
        result = _format_entity(state)
        assert result["friendly_name"] == ""

    def test_empty_state(self):
        state = {}
        result = _format_entity(state)
        assert result["entity_id"] == ""
        assert result["state"] == ""
        assert result["friendly_name"] == ""
        assert result["attributes"] == {}

    def test_preserves_all_attributes(self):
        state = {
            "entity_id": "climate.thermostat",
            "state": "heat",
            "attributes": {
                "friendly_name": "Thermostat",
                "temperature": 72,
                "current_temperature": 69.5,
                "hvac_action": "heating",
            },
        }
        result = _format_entity(state)
        assert result["attributes"]["temperature"] == 72
        assert result["attributes"]["current_temperature"] == 69.5
        assert result["attributes"]["hvac_action"] == "heating"


class TestFilterEntitiesByDomain:
    def test_filters_lights(self):
        states = [
            {"entity_id": "light.living_room", "state": "on", "attributes": {}},
            {"entity_id": "switch.kitchen", "state": "off", "attributes": {}},
            {"entity_id": "light.bedroom", "state": "off", "attributes": {}},
        ]
        filtered = _filter_entities_by_domain(states, "light")
        assert len(filtered) == 2
        assert all(s["entity_id"].startswith("light.") for s in filtered)

    def test_no_filter_returns_all(self):
        states = [
            {"entity_id": "light.a", "state": "on", "attributes": {}},
            {"entity_id": "switch.b", "state": "off", "attributes": {}},
        ]
        filtered = _filter_entities_by_domain(states, None)
        assert len(filtered) == 2

    def test_empty_string_domain_returns_all(self):
        states = [
            {"entity_id": "light.a", "state": "on", "attributes": {}},
            {"entity_id": "switch.b", "state": "off", "attributes": {}},
        ]
        filtered = _filter_entities_by_domain(states, "")
        assert len(filtered) == 2

    def test_no_matching_domain(self):
        states = [
            {"entity_id": "light.a", "state": "on", "attributes": {}},
            {"entity_id": "switch.b", "state": "off", "attributes": {}},
        ]
        filtered = _filter_entities_by_domain(states, "climate")
        assert len(filtered) == 0

    def test_empty_states_list(self):
        filtered = _filter_entities_by_domain([], "light")
        assert filtered == []

    def test_partial_domain_no_false_positive(self):
        """'light' should not match 'light_strip' as a domain prefix."""
        states = [
            {"entity_id": "light.a", "state": "on", "attributes": {}},
            {"entity_id": "light_strip.b", "state": "on", "attributes": {}},
        ]
        filtered = _filter_entities_by_domain(states, "light")
        assert len(filtered) == 1
        assert filtered[0]["entity_id"] == "light.a"
