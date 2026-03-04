"""Gmail contract tests — exercises email tools against fake Gmail API server.

Verifies the full flow: tool function -> GoogleClient HTTP -> fake server -> response parsing.
NO MOCKS. Real HTTP, real JSON parsing, real server.
"""

import json
import threading
from http.server import HTTPServer

import pytest
import requests

from corvus.google_client import GoogleClient
from corvus.tools.email import (
    configure,
    email_archive,
    email_draft,
    email_label,
    email_labels,
    email_list,
    email_read,
    email_send,
)
from tests.contracts.fake_gmail_api import (
    FakeGmailHandler,
    _drafts,
    _label_changes,
    reset_state,
)


@pytest.fixture(scope="module")
def gmail_server():
    server = HTTPServer(("127.0.0.1", 0), FakeGmailHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def setup_client(gmail_server):
    """Configure email tools to use fake server before each test."""
    client = GoogleClient(base_url=gmail_server, static_token="test-token")
    configure(google_client=client)
    reset_state()
    yield
    configure()


# --- email_list contract ---


class TestEmailListContract:
    @pytest.mark.asyncio
    async def test_returns_count_and_messages(self):
        result = await email_list({"provider": "gmail", "query": "is:inbox"})
        content = json.loads(result["content"][0]["text"])
        assert "count" in content
        assert "messages" in content
        assert isinstance(content["messages"], list)

    @pytest.mark.asyncio
    async def test_message_has_required_fields(self):
        result = await email_list({"provider": "gmail", "query": "is:inbox"})
        content = json.loads(result["content"][0]["text"])
        assert content["count"] > 0
        required = {"id", "thread_id", "subject", "from", "to", "date", "snippet", "labels"}
        for msg in content["messages"]:
            assert required.issubset(msg.keys()), f"Missing: {required - msg.keys()}"

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        result = await email_list({"provider": "gmail", "query": "is:inbox", "limit": 1})
        content = json.loads(result["content"][0]["text"])
        assert content["count"] == 1

    @pytest.mark.asyncio
    async def test_data_matches_server(self):
        result = await email_list({"provider": "gmail", "query": "is:inbox"})
        content = json.loads(result["content"][0]["text"])
        assert content["messages"][0]["subject"] == "Re: Migration Plan"
        assert content["messages"][0]["from"] == "Jane Doe <jane@example.com>"
        assert content["messages"][1]["subject"] == "Your order has shipped"


# --- email_read contract ---


class TestEmailReadContract:
    @pytest.mark.asyncio
    async def test_returns_full_message(self):
        result = await email_read({"provider": "gmail", "message_id": "18e1a2b3c4d5e6f7"})
        content = json.loads(result["content"][0]["text"])
        assert "body" in content
        assert "subject" in content
        assert "attachments" in content

    @pytest.mark.asyncio
    async def test_body_decoded_from_base64url(self):
        result = await email_read({"provider": "gmail", "message_id": "18e1a2b3c4d5e6f7"})
        content = json.loads(result["content"][0]["text"])
        assert "migration plan" in content["body"].lower()

    @pytest.mark.asyncio
    async def test_prefers_plain_text(self):
        """Multipart message should return text/plain, not HTML."""
        result = await email_read({"provider": "gmail", "message_id": "18e1a2b3c4d5e6f7"})
        content = json.loads(result["content"][0]["text"])
        assert "<p>" not in content["body"]

    @pytest.mark.asyncio
    async def test_nonexistent_message_returns_error(self):
        """Reading a nonexistent message should raise or return an error."""
        with pytest.raises(requests.exceptions.HTTPError):
            await email_read({"provider": "gmail", "message_id": "nonexistent-id"})

    @pytest.mark.asyncio
    async def test_data_matches_server(self):
        result = await email_read({"provider": "gmail", "message_id": "28f2b3c4d5e6f708"})
        content = json.loads(result["content"][0]["text"])
        assert content["subject"] == "Your order has shipped"
        assert content["from"] == "Amazon <ship@amazon.com>"
        assert "shipped" in content["body"].lower()


# --- email_draft contract ---


class TestEmailDraftContract:
    @pytest.mark.asyncio
    async def test_creates_draft(self):
        result = await email_draft({"to": "jane@example.com", "subject": "Test", "body": "Hello"})
        content = json.loads(result["content"][0]["text"])
        assert content["status"] == "created"
        assert "draft_id" in content
        assert content["draft_id"].startswith("r-")

    @pytest.mark.asyncio
    async def test_draft_recorded_on_server(self):
        await email_draft({"to": "jane@example.com", "subject": "Test", "body": "Hello"})
        assert len(_drafts) == 1
        assert "message" in _drafts[0]


class TestEmailSendContract:
    @pytest.mark.asyncio
    async def test_send_draft(self):
        draft = await email_draft({"to": "a@b.com", "subject": "S", "body": "B"})
        draft_id = json.loads(draft["content"][0]["text"])["draft_id"]
        result = await email_send({"draft_id": draft_id})
        content = json.loads(result["content"][0]["text"])
        assert content["status"] == "sent"
        assert "message_id" in content

    @pytest.mark.asyncio
    async def test_send_direct(self):
        result = await email_send({"to": "a@b.com", "subject": "Direct", "body": "Hi"})
        content = json.loads(result["content"][0]["text"])
        assert content["status"] == "sent"


class TestEmailArchiveContract:
    @pytest.mark.asyncio
    async def test_archive_removes_inbox(self):
        result = await email_archive({"provider": "gmail", "message_id": "18e1a2b3c4d5e6f7"})
        content = json.loads(result["content"][0]["text"])
        assert content["status"] == "archived"
        assert len(_label_changes) == 1
        assert "INBOX" in _label_changes[0]["removeLabelIds"]


class TestEmailLabelContract:
    @pytest.mark.asyncio
    async def test_add_labels(self):
        result = await email_label({"message_id": "18e1a2b3c4d5e6f7", "add_labels": ["Work"]})
        content = json.loads(result["content"][0]["text"])
        assert content["status"] == "updated"
        assert "Work" in content["labels_added"]

    @pytest.mark.asyncio
    async def test_remove_labels(self):
        result = await email_label({"message_id": "18e1a2b3c4d5e6f7", "remove_labels": ["UNREAD"]})
        content = json.loads(result["content"][0]["text"])
        assert "UNREAD" in content["labels_removed"]


class TestEmailLabelsContract:
    @pytest.mark.asyncio
    async def test_lists_labels(self):
        result = await email_labels({})
        content = json.loads(result["content"][0]["text"])
        assert "labels" in content
        label_names = [lbl["name"] for lbl in content["labels"]]
        assert "INBOX" in label_names
        assert "Work" in label_names
