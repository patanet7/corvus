"""Source-contract tests: verify SERVICE_ENV_MAP has Paperless + Firefly settings.

NO MOCKS — reads real source to verify wiring strings are present.

Service credentials are injected via SERVICE_ENV_MAP in credential_store.py.
Tool module env gates are defined in TOOL_MODULE_DEFS in capabilities/modules.py.
"""

from corvus.credential_store import SERVICE_ENV_MAP


class TestPaperlessConfig:
    """Verify Paperless env vars are in SERVICE_ENV_MAP."""

    def test_service_env_map_has_paperless(self):
        assert "paperless" in SERVICE_ENV_MAP

    def test_paperless_has_url(self):
        assert "url" in SERVICE_ENV_MAP["paperless"]
        assert SERVICE_ENV_MAP["paperless"]["url"] == "PAPERLESS_URL"

    def test_paperless_has_token(self):
        assert "token" in SERVICE_ENV_MAP["paperless"]
        assert SERVICE_ENV_MAP["paperless"]["token"] == "PAPERLESS_API_TOKEN"


class TestFireflyConfig:
    """Verify Firefly env vars are in SERVICE_ENV_MAP."""

    def test_service_env_map_has_firefly(self):
        assert "firefly" in SERVICE_ENV_MAP

    def test_firefly_has_url(self):
        assert "url" in SERVICE_ENV_MAP["firefly"]
        assert SERVICE_ENV_MAP["firefly"]["url"] == "FIREFLY_URL"

    def test_firefly_has_token(self):
        assert "token" in SERVICE_ENV_MAP["firefly"]
        assert SERVICE_ENV_MAP["firefly"]["token"] == "FIREFLY_API_TOKEN"
