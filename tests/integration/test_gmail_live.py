"""Opt-in live Gmail API tests. Skipped unless credentials are set.

These tests hit the real Gmail API to verify tool→API integration.
They only assert response shapes, not specific content (live data varies).
Read-only operations only — nothing is created, modified, or deleted.

Run manually:
    GOOGLE_ACCOUNT_personal_TOKEN=/path/to/token.json \
    pytest tests/integration/test_gmail_live.py -v -m integration
"""

import json
import os

import pytest

from corvus.google_client import GoogleClient
from corvus.tools.email import configure as configure_email
from corvus.tools.email import email_list, email_read

# Skip entire module if no Gmail credentials configured
SKIP = not os.environ.get("GOOGLE_ACCOUNT_personal_TOKEN")


@pytest.mark.integration
@pytest.mark.skipif(SKIP, reason="GOOGLE_ACCOUNT_personal_TOKEN not set — skipping live tests")
class TestGmailLive:
    """Live Gmail API integration tests — read-only."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        client = GoogleClient.from_env()
        configure_email(google_client=client)
        yield
        configure_email()

    @pytest.mark.asyncio
    async def test_email_list_returns_results(self):
        """email_list returns a valid response shape from the real Gmail API."""
        result = await email_list({"provider": "gmail", "query": "is:inbox", "limit": 5})
        assert "content" in result
        assert result["content"][0]["type"] == "text"
        content = json.loads(result["content"][0]["text"])
        assert "count" in content
        assert "messages" in content
        assert isinstance(content["messages"], list)
        if content["count"] > 0:
            msg = content["messages"][0]
            assert "id" in msg
            assert "subject" in msg
            assert "from" in msg

    @pytest.mark.asyncio
    async def test_email_list_with_search_query(self):
        """email_list handles search queries without error."""
        result = await email_list(
            {
                "provider": "gmail",
                "query": "newer_than:7d",
                "limit": 3,
            }
        )
        content = json.loads(result["content"][0]["text"])
        assert "error" not in content or content.get("count", 0) == 0

    @pytest.mark.asyncio
    async def test_email_read_with_valid_id(self):
        """email_read returns full message when given a valid ID."""
        list_result = await email_list(
            {
                "provider": "gmail",
                "query": "is:inbox",
                "limit": 1,
            }
        )
        list_content = json.loads(list_result["content"][0]["text"])

        if list_content.get("count", 0) == 0:
            pytest.skip("No messages in inbox to read")

        message_id = list_content["messages"][0]["id"]

        result = await email_read(
            {
                "provider": "gmail",
                "message_id": message_id,
            }
        )
        content = json.loads(result["content"][0]["text"])
        assert "id" in content
        assert "subject" in content
        assert "body" in content

    @pytest.mark.asyncio
    async def test_email_read_invalid_id_returns_error(self):
        """email_read with a bogus ID returns an error, not a crash."""
        result = await email_read(
            {
                "provider": "gmail",
                "message_id": "nonexistent-id-00000",
            }
        )
        content = json.loads(result["content"][0]["text"])
        assert "error" in content


@pytest.mark.integration
@pytest.mark.skipif(SKIP, reason="GOOGLE_ACCOUNT_personal_TOKEN not set — skipping live tests")
class TestGmailLiveLabels:
    """Live Gmail label tests — read-only."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        client = GoogleClient.from_env()
        configure_email(google_client=client)
        yield
        configure_email()

    @pytest.mark.asyncio
    async def test_email_labels_returns_list(self):
        """email_labels returns available Gmail labels."""
        from corvus.tools.email import email_labels

        result = await email_labels({"account": None})
        content = json.loads(result["content"][0]["text"])
        assert "labels" in content
        assert isinstance(content["labels"], list)
        label_names = {lbl.get("name", "") for lbl in content["labels"]}
        assert "INBOX" in label_names or len(content["labels"]) > 0
