"""Source-contract tests: verify config.py has Paperless + Firefly settings.

NO MOCKS — reads real source files to verify wiring strings are present.

Note: Tool module wiring (imports, configure, MCP server creation) moved from
server.py to the CapabilitiesRegistry. Those are tested via the capabilities
registry tests. Config env-var contracts are still verified here.

Agent-level tool allowlists are defined in YAML config files under
config/agents/. Confirm-gated tool sets are YAML-driven and passed dynamically
to create_hooks(). These are tested via the agent config registry tests.
"""

from pathlib import Path

CLAW_DIR = Path(__file__).parent.parent.parent / "corvus"


class TestPaperlessConfig:
    """Verify Paperless env vars are defined in config.py."""

    def test_config_has_paperless_url(self):
        config_src = (CLAW_DIR / "config.py").read_text()
        assert "PAPERLESS_URL" in config_src

    def test_config_has_paperless_api_token(self):
        config_src = (CLAW_DIR / "config.py").read_text()
        assert "PAPERLESS_API_TOKEN" in config_src


class TestFireflyConfig:
    """Verify Firefly env vars are defined in config.py."""

    def test_config_has_firefly_url(self):
        config_src = (CLAW_DIR / "config.py").read_text()
        assert "FIREFLY_URL" in config_src

    def test_config_has_firefly_api_token(self):
        config_src = (CLAW_DIR / "config.py").read_text()
        assert "FIREFLY_API_TOKEN" in config_src


# NOTE: TestConfirmGateCompleteness was removed — confirm-gated tools are now
# YAML-driven and passed dynamically to create_hooks(). hooks.py no longer
# contains any hardcoded tool names, so negative assertions are always true.
