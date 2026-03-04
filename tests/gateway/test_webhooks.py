"""Behavioral tests for webhook payload models and utility functions.

Tests are split into:
1. Pydantic model + auth tests -- no SDK needed, import corvus.webhooks directly
2. Source-contract tests -- verify server.py imports and dispatches new webhook types
3. Endpoint tests -- require claude_agent_sdk (claw.server imports it), skipped if not installed
"""

import importlib
import os
from datetime import datetime

import pytest
from pydantic import ValidationError

# Set a test webhook secret BEFORE importing anything that reads it
os.environ.setdefault("WEBHOOK_SECRET", "test-secret-for-webhooks-64chars-exactly-padded-to-be-long-enough")

from corvus.webhooks import (
    EmailWebhookPayload,
    FinanceWebhookPayload,
    PaperlessWebhookPayload,
    TranscriptPayload,
    WebhookResponse,
    verify_webhook_secret,
)

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

# --- SDK availability check ---
SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed -- run in Docker for full coverage",
)


# ---------------------------------------------------------------------------
# 1. Pydantic model + verify_webhook_secret tests -- no SDK needed
# ---------------------------------------------------------------------------


class TestTranscriptPayload:
    """TranscriptPayload validation tests."""

    def test_valid_minimal(self):
        p = TranscriptPayload(title="Standup", transcript="We discussed...")
        assert p.title == "Standup"
        assert p.source == "unknown"
        assert p.participants == []

    def test_valid_full(self):
        p = TranscriptPayload(
            title="Sprint Planning",
            transcript="The team...",
            participants=["Alice", "Bob"],
            source="otter",
            duration_minutes=30,
            meeting_date=datetime(2026, 2, 26, 14, 0),
        )
        assert len(p.participants) == 2
        assert p.duration_minutes == 30
        assert p.meeting_date is not None

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            TranscriptPayload(transcript="text")

    def test_missing_transcript_raises(self):
        with pytest.raises(ValidationError):
            TranscriptPayload(title="Test")


class TestEmailWebhookPayload:
    """EmailWebhookPayload validation tests."""

    def test_valid_minimal(self):
        p = EmailWebhookPayload(message_id="msg-123")
        assert p.message_id == "msg-123"
        assert p.provider == "gmail"
        assert p.labels == []

    def test_valid_full(self):
        p = EmailWebhookPayload(
            message_id="msg-456",
            subject="Hello",
            sender="alice@example.com",
            snippet="Preview text...",
            labels=["INBOX", "UNREAD"],
            provider="yahoo",
        )
        assert p.sender == "alice@example.com"
        assert p.provider == "yahoo"

    def test_missing_message_id_raises(self):
        with pytest.raises(ValidationError):
            EmailWebhookPayload()


class TestPaperlessWebhookPayload:
    """PaperlessWebhookPayload validation tests."""

    def test_valid_minimal(self):
        p = PaperlessWebhookPayload(document_id=42)
        assert p.document_id == 42
        assert p.title == ""
        assert p.tags == []

    def test_valid_full(self):
        p = PaperlessWebhookPayload(
            document_id=99,
            title="Invoice 2024",
            correspondent="ACME Corp",
            document_type="invoice",
            tags=["finance", "2024"],
        )
        assert p.correspondent == "ACME Corp"
        assert len(p.tags) == 2

    def test_missing_document_id_raises(self):
        with pytest.raises(ValidationError):
            PaperlessWebhookPayload()

    def test_invalid_document_id_type_raises(self):
        with pytest.raises(ValidationError):
            PaperlessWebhookPayload(document_id="not-a-number")


class TestFinanceWebhookPayload:
    """FinanceWebhookPayload validation tests."""

    def test_valid_minimal(self):
        p = FinanceWebhookPayload(trigger="nightly_reconcile")
        assert p.trigger == "nightly_reconcile"
        assert p.date_range_start is None

    def test_valid_with_dates(self):
        p = FinanceWebhookPayload(
            trigger="manual",
            date_range_start="2024-01-01",
            date_range_end="2024-01-31",
        )
        assert p.date_range_start == "2024-01-01"
        assert p.date_range_end == "2024-01-31"

    def test_missing_trigger_raises(self):
        with pytest.raises(ValidationError):
            FinanceWebhookPayload()


class TestWebhookResponse:
    """WebhookResponse model tests."""

    def test_basic_response(self):
        r = WebhookResponse(status="processed", webhook_type="transcript")
        assert r.status == "processed"
        assert r.memories_saved == 0

    def test_error_response(self):
        r = WebhookResponse(
            status="error",
            webhook_type="email",
            message="Processing failed",
        )
        assert r.message == "Processing failed"

    def test_model_dump(self):
        r = WebhookResponse(status="accepted", webhook_type="paperless")
        d = r.model_dump()
        assert d["status"] == "accepted"
        assert d["webhook_type"] == "paperless"


class TestVerifyWebhookSecret:
    """verify_webhook_secret behavioral tests.

    Directly mutates the module-level WEBHOOK_SECRET attribute and restores
    it in a try/finally -- this is NOT mocking, it is direct module attribute
    manipulation with cleanup.
    """

    def test_empty_secret_returns_false(self):
        """When WEBHOOK_SECRET is empty, always reject."""
        original = os.environ.get("WEBHOOK_SECRET")
        os.environ["WEBHOOK_SECRET"] = ""
        try:
            assert verify_webhook_secret("anything") is False
        finally:
            if original is not None:
                os.environ["WEBHOOK_SECRET"] = original
            else:
                os.environ.pop("WEBHOOK_SECRET", None)

    def test_empty_header_returns_false(self):
        original = os.environ.get("WEBHOOK_SECRET")
        os.environ["WEBHOOK_SECRET"] = "real-secret"
        try:
            assert verify_webhook_secret("") is False
        finally:
            if original is not None:
                os.environ["WEBHOOK_SECRET"] = original
            else:
                os.environ.pop("WEBHOOK_SECRET", None)

    def test_correct_secret_returns_true(self):
        original = os.environ.get("WEBHOOK_SECRET")
        os.environ["WEBHOOK_SECRET"] = "test-secret-123"
        try:
            assert verify_webhook_secret("test-secret-123") is True
        finally:
            if original is not None:
                os.environ["WEBHOOK_SECRET"] = original
            else:
                os.environ.pop("WEBHOOK_SECRET", None)

    def test_wrong_secret_returns_false(self):
        original = os.environ.get("WEBHOOK_SECRET")
        os.environ["WEBHOOK_SECRET"] = "correct"
        try:
            assert verify_webhook_secret("wrong") is False
        finally:
            if original is not None:
                os.environ["WEBHOOK_SECRET"] = original
            else:
                os.environ.pop("WEBHOOK_SECRET", None)


# ---------------------------------------------------------------------------
# 2. Source-contract tests -- verify server.py and webhooks.py wiring
# ---------------------------------------------------------------------------


class TestServerWebhookDispatch:
    """Source-contract tests: verify API webhook router dispatch wiring."""

    def _api_webhooks_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent.parent / "corvus" / "api" / "webhooks.py").read_text()

    def test_imports_paperless_payload(self):
        assert "PaperlessWebhookPayload" in self._api_webhooks_source()

    def test_imports_finance_payload(self):
        assert "FinanceWebhookPayload" in self._api_webhooks_source()

    def test_imports_process_paperless(self):
        assert "process_paperless" in self._api_webhooks_source()

    def test_imports_process_finance(self):
        assert "process_finance" in self._api_webhooks_source()

    def test_dispatches_paperless_type(self):
        src = self._api_webhooks_source()
        assert '"paperless"' in src

    def test_dispatches_finance_type(self):
        src = self._api_webhooks_source()
        assert '"finance"' in src


class TestWebhooksModuleExports:
    """Source-contract tests: verify webhooks.py has the process functions."""

    def _webhooks_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent.parent / "corvus" / "webhooks.py").read_text()

    def _background_dispatch_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "background_dispatch.py").read_text()

    def test_has_process_paperless(self):
        assert "process_paperless" in self._webhooks_source()

    def test_has_process_finance(self):
        assert "process_finance" in self._webhooks_source()

    def test_has_emit_routing_decision(self):
        assert "_emit_routing_decision" in self._webhooks_source()

    def test_webhook_dispatch_uses_task_planner(self):
        src = self._background_dispatch_source()
        assert "runtime.task_planner.plan" in src
        assert '"dispatch_plan"' in src

    def test_webhook_dispatch_persists_dispatch_and_runs(self):
        src = self._background_dispatch_source()
        assert "create_dispatch(" in src
        assert "start_agent_run(" in src


# ---------------------------------------------------------------------------
# 3. Endpoint tests -- require claude_agent_sdk to import corvus.server
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestWebhookAuth:
    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app)

    def test_rejects_missing_secret(self):
        resp = self.client.post("/api/webhooks/transcript", json={"title": "test", "transcript": "content"})
        assert resp.status_code == 401

    def test_rejects_wrong_secret(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "test", "transcript": "content"},
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert resp.status_code == 401

    def test_rejects_empty_secret_header(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"title": "test", "transcript": "content"},
            headers={"X-Webhook-Secret": ""},
        )
        assert resp.status_code == 401


@skip_no_sdk
class TestWebhookRouting:
    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        self.client = TestClient(app)

    def test_rejects_unknown_type(self):
        resp = self.client.post(
            "/api/webhooks/unknown_type",
            json={},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET},
        )
        assert resp.status_code == 400

    def test_rejects_invalid_transcript_payload(self):
        resp = self.client.post(
            "/api/webhooks/transcript",
            json={"not_a_valid_field": True},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET},
        )
        assert resp.status_code == 422

    def test_rejects_invalid_email_payload(self):
        resp = self.client.post(
            "/api/webhooks/email",
            json={"not_valid": True},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET},
        )
        assert resp.status_code == 422

    def test_rejects_invalid_paperless_payload(self):
        resp = self.client.post(
            "/api/webhooks/paperless",
            json={"not_valid": True},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET},
        )
        assert resp.status_code == 422

    def test_rejects_invalid_finance_payload(self):
        resp = self.client.post(
            "/api/webhooks/finance",
            json={"not_valid": True},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET},
        )
        assert resp.status_code == 422
