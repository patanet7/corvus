"""Tests for Grafana dashboard completeness.

Validates that the Claw Gateway Grafana dashboard at
infra/observability/grafana/dashboards/claw-overview.json
covers all 6 audit sections required by 10A #6:
  1. Fleet Health
  2. Agent Activity
  3. Security
  4. Sessions
  5. Models
  6. Webhooks
"""

import json
from pathlib import Path

import pytest

DASHBOARD_PATH = (
    Path(__file__).parent.parent.parent / "infra" / "observability" / "grafana" / "dashboards" / "claw-overview.json"
)

REQUIRED_SECTIONS = [
    "fleet health",
    "agent activity",
    "security",
    "sessions",
    "models",
    "webhooks",
]

# Each required section must have at least one panel querying these event_types
SECTION_EVENT_TYPES = {
    "fleet health": ["heartbeat"],
    "agent activity": ["routing_decision"],
    "security": ["security_block", "confirm_gate"],
    "sessions": ["session_start", "session_end"],
    "models": ["llm_output", "routing_decision"],
    "webhooks": ["webhook_received"],
}

# Minimum panel count per section (row itself does not count)
MIN_PANELS_PER_SECTION = {
    "fleet health": 2,
    "agent activity": 2,
    "security": 2,
    "sessions": 2,
    "models": 2,
    "webhooks": 2,
}


def _load_dashboard() -> dict:
    """Load and return the dashboard JSON."""
    return json.loads(DASHBOARD_PATH.read_text())


def _extract_panel_titles(dashboard: dict) -> list[str]:
    """Extract all panel and row titles from dashboard JSON."""
    titles = []
    for panel in dashboard.get("panels", []):
        if panel.get("title"):
            titles.append(panel["title"].lower())
        # Check nested panels in collapsed rows
        for nested in panel.get("panels", []):
            if nested.get("title"):
                titles.append(nested["title"].lower())
    return titles


def _extract_all_queries(dashboard: dict) -> list[str]:
    """Extract all LogQL query expressions from dashboard JSON."""
    queries = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if expr:
                queries.append(expr)
        for nested in panel.get("panels", []):
            for target in nested.get("targets", []):
                expr = target.get("expr", "")
                if expr:
                    queries.append(expr)
    return queries


def _get_section_panels(dashboard: dict, section_name: str) -> list[dict]:
    """Get all non-row panels that belong to a section (row title match).

    Walks panels in order; once a row matching section_name is found,
    collects all subsequent panels until the next row or end-of-list.
    """
    panels = dashboard.get("panels", [])
    collecting = False
    result = []
    for panel in panels:
        is_row = panel.get("type") == "row"
        if is_row:
            title = (panel.get("title") or "").lower()
            if section_name in title:
                collecting = True
                # Include nested panels from collapsed rows
                for nested in panel.get("panels", []):
                    result.append(nested)
                continue
            elif collecting:
                # Hit the next row, stop collecting
                break
        if collecting:
            result.append(panel)
    return result


def _panel_ids(dashboard: dict) -> list[int]:
    """Extract all panel IDs including nested ones."""
    ids = []
    for panel in dashboard.get("panels", []):
        if "id" in panel:
            ids.append(panel["id"])
        for nested in panel.get("panels", []):
            if "id" in nested:
                ids.append(nested["id"])
    return ids


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not DASHBOARD_PATH.exists(), reason=f"Infrastructure file not present: {DASHBOARD_PATH}")
class TestGrafanaDashboard:
    """Validate Claw Gateway Grafana dashboard completeness."""

    def test_dashboard_file_exists(self):
        assert DASHBOARD_PATH.exists(), f"Dashboard file not found at {DASHBOARD_PATH}"

    def test_dashboard_is_valid_json(self):
        data = _load_dashboard()
        # The provisioning wrapper has a "dashboard" key
        inner = data.get("dashboard", data)
        assert "panels" in inner, "Dashboard JSON must contain 'panels' key"

    def test_all_six_sections_present(self):
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        titles = _extract_panel_titles(inner)
        all_text = " ".join(titles)
        missing = []
        for section in REQUIRED_SECTIONS:
            if section not in all_text:
                missing.append(section)
        assert not missing, f"Missing dashboard sections: {missing}. Found titles: {titles}"

    def test_dashboard_has_loki_queries(self):
        raw = DASHBOARD_PATH.read_text()
        assert "claw-gateway" in raw, "Dashboard should contain queries referencing 'claw-gateway' source"

    @pytest.mark.parametrize("section", REQUIRED_SECTIONS)
    def test_section_has_panels(self, section: str):
        """Each section row should contain at least MIN_PANELS_PER_SECTION panels."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        panels = _get_section_panels(inner, section)
        min_count = MIN_PANELS_PER_SECTION[section]
        assert len(panels) >= min_count, f"Section '{section}' has {len(panels)} panels, expected at least {min_count}"

    @pytest.mark.parametrize("section", REQUIRED_SECTIONS)
    def test_section_queries_correct_event_types(self, section: str):
        """Each section must query at least one of its expected event_types."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        panels = _get_section_panels(inner, section)
        expected_events = SECTION_EVENT_TYPES[section]

        # Collect all query expressions from section panels
        section_queries = []
        for panel in panels:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                if expr:
                    section_queries.append(expr)

        all_query_text = " ".join(section_queries)
        found_events = [evt for evt in expected_events if evt in all_query_text]
        assert found_events, (
            f"Section '{section}' should query at least one of {expected_events} but found none in: {section_queries}"
        )

    def test_no_duplicate_panel_ids(self):
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        ids = _panel_ids(inner)
        seen = set()
        duplicates = []
        for pid in ids:
            if pid in seen:
                duplicates.append(pid)
            seen.add(pid)
        assert not duplicates, f"Duplicate panel IDs: {duplicates}"

    def test_all_panels_have_grid_position(self):
        """Every panel should have a gridPos for Grafana layout."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        for panel in inner.get("panels", []):
            assert "gridPos" in panel, f"Panel '{panel.get('title', panel.get('id'))}' missing gridPos"

    def test_dashboard_uses_loki_datasource_variable(self):
        """Dashboard should use a templated Loki datasource variable."""
        raw = DASHBOARD_PATH.read_text()
        assert "DS_LOKI" in raw, "Dashboard should use a DS_LOKI datasource variable"

    def test_webhook_section_queries_webhook_received(self):
        """Webhooks section specifically must query webhook_received events."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        panels = _get_section_panels(inner, "webhooks")
        all_exprs = []
        for panel in panels:
            for target in panel.get("targets", []):
                all_exprs.append(target.get("expr", ""))
        combined = " ".join(all_exprs)
        assert "webhook_received" in combined, (
            f"Webhooks section must query 'webhook_received' events. Queries found: {all_exprs}"
        )

    def test_fleet_health_has_heartbeat_query(self):
        """Fleet Health must query heartbeat events for uptime monitoring."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        panels = _get_section_panels(inner, "fleet health")
        all_exprs = []
        for panel in panels:
            for target in panel.get("targets", []):
                all_exprs.append(target.get("expr", ""))
        combined = " ".join(all_exprs)
        assert "heartbeat" in combined, (
            f"Fleet Health section must query 'heartbeat' events. Queries found: {all_exprs}"
        )

    def test_security_has_block_and_gate_queries(self):
        """Security section must cover both security_block and confirm_gate."""
        data = _load_dashboard()
        inner = data.get("dashboard", data)
        panels = _get_section_panels(inner, "security")
        all_exprs = []
        for panel in panels:
            for target in panel.get("targets", []):
                all_exprs.append(target.get("expr", ""))
        combined = " ".join(all_exprs)
        assert "security_block" in combined, "Security section must query 'security_block' events"
        assert "confirm_gate" in combined, "Security section must query 'confirm_gate' events"
