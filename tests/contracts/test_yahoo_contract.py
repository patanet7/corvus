"""Yahoo Mail IMAP contract tests.

Exercises email tools (Yahoo provider) against a fake IMAP server.
Verifies IMAP LOGIN -> SELECT -> SEARCH -> FETCH flow.
"""

import json

import pytest

from corvus.tools.email import configure, email_list, email_read
from corvus.yahoo_client import YahooClient
from tests.contracts.fake_yahoo_imap import FakeIMAPServer


@pytest.fixture(scope="module")
def yahoo_server():
    server = FakeIMAPServer()
    port = server.start()
    yield port
    server.stop()


@pytest.fixture(autouse=True)
def setup_yahoo_client(yahoo_server):
    """Configure email tools with Yahoo client pointing at fake server."""
    client = YahooClient(
        accounts={
            "test": {
                "email": "thomas@yahoo.com",
                "app_password": "test-pass",
                "host": "127.0.0.1",
                "port": str(yahoo_server),
            },
        }
    )
    configure(yahoo_client=client)
    yield
    configure()


class TestYahooEmailListContract:
    @pytest.mark.asyncio
    async def test_returns_count_and_messages(self):
        result = await email_list({"provider": "yahoo", "query": "invoice", "account": "test"})
        content = json.loads(result["content"][0]["text"])
        assert "count" in content
        assert "messages" in content

    @pytest.mark.asyncio
    async def test_message_has_required_fields(self):
        result = await email_list({"provider": "yahoo", "query": "invoice", "account": "test"})
        content = json.loads(result["content"][0]["text"])
        if content["count"] > 0:
            required = {"id", "subject", "from", "to", "date"}
            for msg in content["messages"]:
                assert required.issubset(msg.keys())


class TestYahooEmailReadContract:
    @pytest.mark.asyncio
    async def test_returns_body(self):
        result = await email_read({"provider": "yahoo", "message_id": "1", "account": "test"})
        content = json.loads(result["content"][0]["text"])
        assert "body" in content
        assert "subject" in content
