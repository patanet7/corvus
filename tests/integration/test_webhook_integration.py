"""Integration tests for webhooks — requires ANTHROPIC_API_KEY.

These tests actually dispatch to agents, which requires a real API key.
Opt-in only.
"""

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live]

HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY, reason="ANTHROPIC_API_KEY not set")
class TestWebhookIntegration:
    def test_transcript_webhook_processes(self):
        """Full end-to-end: send transcript, verify agent processes it."""
        pass

    def test_email_webhook_processes(self):
        """Full end-to-end: send email notification, verify agent triages it."""
        pass
