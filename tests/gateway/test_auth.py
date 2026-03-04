"""Behavioral tests for Authelia auth middleware.

Tests real HTTP requests through a real FastAPI app using TestClient.
NO mocks — exercises the real get_user dependency with real header handling.
"""

import os

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from corvus.auth import get_user


def _build_auth_app() -> FastAPI:
    """Build a minimal FastAPI app that uses the real get_user dependency."""
    test_app = FastAPI()

    @test_app.get("/protected")
    def protected(user: str = Depends(get_user)):
        return {"user": user}

    return test_app


@pytest.fixture
def auth_app():
    """Create a fresh test app for each test."""
    return _build_auth_app()


@pytest.fixture
def client(auth_app):
    """Create a TestClient wrapping the real auth app."""
    return TestClient(auth_app)


class TestAuthGetUser:
    """Test get_user auth extraction via real HTTP requests."""

    def test_extracts_x_remote_user(self, client):
        resp = client.get("/protected", headers={"X-Remote-User": "testuser"})
        assert resp.status_code == 200
        assert resp.json() == {"user": "testuser"}

    def test_extracts_remote_user_fallback(self, client):
        resp = client.get("/protected", headers={"Remote-User": "testuser"})
        assert resp.status_code == 200
        assert resp.json() == {"user": "testuser"}

    def test_prefers_x_remote_user_over_remote_user(self, client):
        resp = client.get(
            "/protected",
            headers={"X-Remote-User": "testuser", "Remote-User": "other"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"user": "testuser"}

    def test_returns_401_when_no_header(self, client):
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert "No Remote-User header" in resp.json()["detail"]

    def test_returns_403_for_unknown_user(self, client):
        resp = client.get("/protected", headers={"X-Remote-User": "hacker"})
        assert resp.status_code == 403
        assert "not allowed" in resp.json()["detail"]


class TestAuthAllowedUsersConfig:
    """Test ALLOWED_USERS configuration via environment variable."""

    def test_allows_configured_users(self):
        """Set ALLOWED_USERS env var, reimport config, and verify access."""
        import importlib

        import corvus.auth
        import corvus.config

        original = os.environ.get("ALLOWED_USERS")
        try:
            os.environ["ALLOWED_USERS"] = "alice,bob"
            importlib.reload(corvus.config)
            importlib.reload(corvus.auth)

            app = FastAPI()

            @app.get("/check")
            def check(user: str = Depends(corvus.auth.get_user)):
                return {"user": user}

            test_client = TestClient(app)

            # alice should be allowed
            resp = test_client.get("/check", headers={"X-Remote-User": "alice"})
            assert resp.status_code == 200
            assert resp.json() == {"user": "alice"}

            # bob should be allowed
            resp = test_client.get("/check", headers={"X-Remote-User": "bob"})
            assert resp.status_code == 200
            assert resp.json() == {"user": "bob"}

            # charlie should be blocked
            resp = test_client.get("/check", headers={"X-Remote-User": "charlie"})
            assert resp.status_code == 403
        finally:
            # Restore original env and reload
            if original is not None:
                os.environ["ALLOWED_USERS"] = original
            else:
                os.environ.pop("ALLOWED_USERS", None)
            importlib.reload(corvus.config)
            importlib.reload(corvus.auth)

    def test_no_default_allowed_users(self):
        """Without ALLOWED_USERS env var, the list should be empty (fail-closed)."""
        import importlib

        import corvus.config

        original = os.environ.pop("ALLOWED_USERS", None)
        try:
            importlib.reload(corvus.config)
            assert corvus.config.ALLOWED_USERS == []
        finally:
            if original is not None:
                os.environ["ALLOWED_USERS"] = original
            importlib.reload(corvus.config)

    def test_empty_allowed_users_rejects_all(self):
        """When ALLOWED_USERS is empty, all requests should be rejected (fail-closed)."""
        import importlib

        import corvus.auth
        import corvus.config

        original = os.environ.pop("ALLOWED_USERS", None)
        try:
            os.environ["ALLOWED_USERS"] = ""
            importlib.reload(corvus.config)
            importlib.reload(corvus.auth)

            app = FastAPI()

            @app.get("/check")
            def check(user: str = Depends(corvus.auth.get_user)):
                return {"user": user}

            test_client = TestClient(app)
            resp = test_client.get("/check", headers={"X-Remote-User": "anyone"})
            assert resp.status_code == 403
            assert "not configured" in resp.json()["detail"]
        finally:
            if original is not None:
                os.environ["ALLOWED_USERS"] = original
            else:
                os.environ.setdefault("ALLOWED_USERS", "testuser")
            importlib.reload(corvus.config)
            importlib.reload(corvus.auth)
