"""End-to-end tests for webhook HTTP endpoints.

Uses FastAPI TestClient to exercise the actual HTTP endpoint,
including auth, validation, dispatch, and response contracts for
all 4 webhook types (transcript, email, paperless, finance).

Existing test_webhooks.py covers Pydantic models and source-contract
checks. This file focuses on the HTTP layer: real requests through
the FastAPI app with auth headers, payload validation, and response
shape verification.

The webhook handlers dispatch to domain agents via ClaudeSDKClient.
Without a live Claude API, dispatch will fail and _dispatch_to_agent
returns WebhookResponse(status="error"). The endpoint still returns
HTTP 200 with the error response body -- this is correct behavior.
These tests verify the full HTTP round-trip regardless.
"""

import importlib
import os

import pytest

# Set a test webhook secret BEFORE importing anything that reads it at module
# level (claw.webhooks reads WEBHOOK_SECRET at import time).
_TEST_SECRET = "test-secret-for-webhooks-64chars-exactly-padded-to-be-long-enough"
os.environ.setdefault("WEBHOOK_SECRET", _TEST_SECRET)

# SDK availability check -- claw.server imports claude_agent_sdk at top level
SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed -- run in Docker for full coverage",
)


def _get_test_secret() -> str:
    """Return the webhook secret that the running server expects.

    claw.webhooks.WEBHOOK_SECRET is read from os.environ at import time.
    We set it above via setdefault before any imports, so this is the
    canonical value.
    """
    return os.environ["WEBHOOK_SECRET"]


# ---------------------------------------------------------------------------
# 1. Auth tests -- verify X-Webhook-Secret enforcement at the HTTP layer
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestWebhookEndpointAuth:
    """Webhook authentication via X-Webhook-Secret header.

    Tests that the endpoint rejects requests with missing, empty, or
    incorrect secrets before any payload parsing occurs.
    """

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)

    def test_missing_secret_returns_401(self):
        """No X-Webhook-Secret header at all."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "standup", "transcript": "discussed items"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["status"] == "error"

    def test_empty_secret_returns_401(self):
        """X-Webhook-Secret header present but empty string."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "standup", "transcript": "discussed items"},
            headers={"X-Webhook-Secret": ""},
        )
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self):
        """X-Webhook-Secret header present but incorrect value."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "standup", "transcript": "discussed items"},
            headers={"X-Webhook-Secret": "completely-wrong-secret-value"},
        )
        assert resp.status_code == 401

    def test_auth_checked_before_type_validation(self):
        """Auth rejection happens before webhook_type check.

        Even an unknown type should return 401 if the secret is wrong,
        not 400.
        """
        resp = self.client.post(
            "/api/webhooks/nonexistent",
            json={},
            headers={"X-Webhook-Secret": "wrong"},
        )
        assert resp.status_code == 401

    def test_auth_checked_before_payload_validation(self):
        """Auth rejection happens before payload validation.

        Even an invalid payload should return 401 if the secret is wrong,
        not 422.
        """
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"garbage": True},
            headers={"X-Webhook-Secret": "wrong"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Routing + validation tests -- correct secret, check type & payload errors
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestWebhookEndpointValidation:
    """Webhook type routing and payload validation.

    These tests use the correct secret and verify that the endpoint
    returns the right error codes for unknown types and invalid payloads.
    """

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_unknown_type_returns_400(self):
        resp = self.client.post(
            "/api/webhooks/unknown_type",
            json={"foo": "bar"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert "unknown_type" in body["message"].lower()

    def test_empty_string_type_returns_400(self):
        """Webhook type '' routed as path segment -- FastAPI serves 404/307."""
        resp = self.client.post(
            "/api/webhooks/",
            json={},
            headers={"X-Webhook-Secret": self.secret},
        )
        # FastAPI returns 404 or 307 for trailing-slash mismatches
        assert resp.status_code in (307, 400, 404, 405)

    # -- Transcript validation --

    def test_transcript_missing_required_fields_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    def test_transcript_missing_title_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"transcript": "some text"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    def test_transcript_missing_transcript_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "Standup"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    # -- Email validation --

    def test_email_missing_message_id_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/email",
            json={"subject": "hi", "sender": "a@b.com"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    # -- Paperless validation --

    def test_paperless_missing_document_id_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={"title": "Invoice"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    def test_paperless_wrong_id_type_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={"document_id": "not-an-int"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422

    # -- Finance validation --

    def test_finance_missing_trigger_returns_422(self):
        resp = self.client.post(
            "/api/webhooks/finance",
            json={"amount": 42.50},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3. Happy-path e2e tests -- valid payloads through the full HTTP endpoint
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestTranscriptWebhookE2E:
    """End-to-end tests for POST /api/webhooks/transcript with valid payloads."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_minimal_valid_payload_returns_200(self):
        """Minimal valid transcript: title + transcript only."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "Daily Standup", "transcript": "We discussed sprint goals."},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "transcript"
        assert body["status"] in ("processed", "error")
        assert "memories_saved" in body

    def test_full_payload_returns_200(self):
        """Full transcript payload with all optional fields."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={
                "title": "Sprint Planning",
                "transcript": "The team reviewed backlog items and estimated story points.",
                "participants": ["Alice", "Bob", "Charlie"],
                "meeting_date": "2026-02-28T14:00:00",
                "source": "otter",
                "duration_minutes": 45,
            },
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "transcript"
        assert body["status"] in ("processed", "error")

    def test_response_contains_required_fields(self):
        """Response body matches WebhookResponse contract."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "Retro", "transcript": "What went well..."},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        # WebhookResponse has: status, webhook_type, message (optional), memories_saved
        assert "status" in body
        assert "webhook_type" in body
        assert "memories_saved" in body


@skip_no_sdk
class TestEmailWebhookE2E:
    """End-to-end tests for POST /api/webhooks/email with valid payloads."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_minimal_valid_payload_returns_200(self):
        """Minimal valid email: message_id only (others have defaults)."""
        resp = self.client.post(
            "/api/webhooks/email",
            json={"message_id": "msg-001"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "email"
        assert body["status"] in ("processed", "error")

    def test_full_payload_returns_200(self):
        """Full email payload with all optional fields."""
        resp = self.client.post(
            "/api/webhooks/email",
            json={
                "message_id": "msg-456",
                "subject": "Invoice Attached",
                "sender": "billing@example.com",
                "snippet": "Please find the attached invoice for February...",
                "labels": ["INBOX", "UNREAD", "IMPORTANT"],
                "provider": "gmail",
            },
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "email"
        assert body["status"] in ("processed", "error")

    def test_response_contract(self):
        """Response body matches WebhookResponse contract."""
        resp = self.client.post(
            "/api/webhooks/email",
            json={"message_id": "msg-contract-test"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "webhook_type" in body
        assert "memories_saved" in body


@skip_no_sdk
class TestPaperlessWebhookE2E:
    """End-to-end tests for POST /api/webhooks/paperless with valid payloads."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_minimal_valid_payload_returns_200(self):
        """Minimal valid paperless: document_id only."""
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={"document_id": 42},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "paperless"
        assert body["status"] in ("processed", "error")

    def test_full_payload_returns_200(self):
        """Full paperless payload with all optional fields."""
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={
                "document_id": 99,
                "title": "Insurance Policy 2026",
                "correspondent": "State Farm",
                "document_type": "insurance",
                "tags": ["insurance", "2026", "auto"],
            },
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "paperless"
        assert body["status"] in ("processed", "error")

    def test_response_contract(self):
        """Response body matches WebhookResponse contract."""
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={"document_id": 1},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "webhook_type" in body
        assert "memories_saved" in body


@skip_no_sdk
class TestFinanceWebhookE2E:
    """End-to-end tests for POST /api/webhooks/finance with valid payloads."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_minimal_valid_payload_returns_200(self):
        """Minimal valid finance: trigger only."""
        resp = self.client.post(
            "/api/webhooks/finance",
            json={"trigger": "nightly_reconcile"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "finance"
        assert body["status"] in ("processed", "error")

    def test_full_payload_with_date_range_returns_200(self):
        """Full finance payload with date range."""
        resp = self.client.post(
            "/api/webhooks/finance",
            json={
                "trigger": "manual",
                "date_range_start": "2026-02-01",
                "date_range_end": "2026-02-28",
            },
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webhook_type"] == "finance"
        assert body["status"] in ("processed", "error")

    def test_response_contract(self):
        """Response body matches WebhookResponse contract."""
        resp = self.client.post(
            "/api/webhooks/finance",
            json={"trigger": "nightly_reconcile"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "webhook_type" in body
        assert "memories_saved" in body


# ---------------------------------------------------------------------------
# 4. Cross-cutting endpoint behavior
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestWebhookEndpointCrossCutting:
    """Cross-cutting concerns: content-type, method enforcement, etc."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.secret = _get_test_secret()

    def test_get_method_not_allowed(self):
        """Webhook endpoint only accepts POST."""
        resp = self.client.get(
            "/api/webhooks/transcript",
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 405

    def test_put_method_not_allowed(self):
        """Webhook endpoint only accepts POST."""
        resp = self.client.put(
            "/api/webhooks/transcript",
            json={"title": "test", "transcript": "data"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 405

    def test_all_four_types_accepted(self):
        """Verify all 4 webhook types pass auth + validation (HTTP 200)."""
        payloads = {
            "transcript": {"title": "Standup", "transcript": "Notes here."},
            "email": {"message_id": "msg-all-types"},
            "paperless": {"document_id": 7},
            "finance": {"trigger": "nightly_reconcile"},
        }
        for wtype, payload in payloads.items():
            resp = self.client.post(
                f"/api/webhooks/{wtype}",
                json=payload,
                headers={"X-Webhook-Secret": self.secret},
            )
            assert resp.status_code == 200, f"Expected 200 for {wtype}, got {resp.status_code}"
            body = resp.json()
            assert body["webhook_type"] == wtype, f"Wrong webhook_type for {wtype}"

    def test_response_is_json(self):
        """All webhook responses have application/json content-type."""
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "Test", "transcript": "Content"},
            headers={"X-Webhook-Secret": self.secret},
        )
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("content-type", "")

    def test_response_body_serializable(self):
        """Response body is valid JSON matching WebhookResponse model_dump."""
        resp = self.client.post(
            "/api/webhooks/email",
            json={"message_id": "msg-serializable"},
            headers={"X-Webhook-Secret": self.secret},
        )
        body = resp.json()
        # All WebhookResponse fields present
        expected_keys = {"status", "webhook_type", "memories_saved"}
        assert expected_keys.issubset(body.keys()), f"Missing keys: {expected_keys - body.keys()}"
