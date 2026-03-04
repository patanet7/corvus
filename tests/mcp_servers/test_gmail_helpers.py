"""Behavioral tests for Gmail helper functions — real data structures, NO mocks."""

from corvus.tools.email import (
    _extract_body,
    _extract_header,
    _format_message_summary,
    _parse_message_list_response,
)


class TestExtractHeader:
    def test_finds_subject(self):
        headers = [
            {"name": "From", "value": "alice@example.com"},
            {"name": "Subject", "value": "Test Subject"},
            {"name": "Date", "value": "Wed, 26 Feb 2026 10:30:00 -0500"},
        ]
        assert _extract_header(headers, "Subject") == "Test Subject"

    def test_missing_header_returns_empty(self):
        headers = [{"name": "From", "value": "alice@example.com"}]
        assert _extract_header(headers, "Subject") == ""

    def test_case_insensitive(self):
        headers = [{"name": "subject", "value": "Lowercase Subject"}]
        assert _extract_header(headers, "Subject") == "Lowercase Subject"

    def test_empty_headers_list(self):
        assert _extract_header([], "Subject") == ""

    def test_header_with_empty_value(self):
        headers = [{"name": "Subject", "value": ""}]
        assert _extract_header(headers, "Subject") == ""

    def test_returns_first_match(self):
        headers = [
            {"name": "Subject", "value": "First"},
            {"name": "Subject", "value": "Second"},
        ]
        assert _extract_header(headers, "Subject") == "First"


class TestExtractBody:
    def test_plain_text_part(self):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": "SGVsbG8gV29ybGQ="},  # base64url "Hello World"
        }
        assert _extract_body(payload) == "Hello World"

    def test_multipart_prefers_plain(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "UGxhaW4gdGV4dA=="}},
                {"mimeType": "text/html", "body": {"data": "PGI+SFRNTDWVYD4="}},
            ],
        }
        assert _extract_body(payload) == "Plain text"

    def test_empty_body(self):
        payload = {"mimeType": "text/plain", "body": {}}
        assert _extract_body(payload) == ""

    def test_html_fallback_strips_tags(self):
        # base64url encode "<b>Bold</b> text"
        import base64

        html = "<b>Bold</b> text"
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        payload = {"mimeType": "text/html", "body": {"data": encoded}}
        result = _extract_body(payload)
        assert "Bold" in result
        assert "<b>" not in result
        assert "text" in result

    def test_multipart_no_plain_falls_back_to_first(self):
        import base64

        html = "<p>HTML only</p>"
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": encoded}},
            ],
        }
        result = _extract_body(payload)
        assert "HTML only" in result

    def test_nested_multipart(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": "TmVzdGVk"},  # "Nested"
                        },
                    ],
                },
            ],
        }
        assert _extract_body(payload) == "Nested"

    def test_unknown_mime_type(self):
        payload = {"mimeType": "application/pdf", "body": {"data": "abc"}}
        assert _extract_body(payload) == ""

    def test_missing_body_key(self):
        payload = {"mimeType": "text/plain"}
        assert _extract_body(payload) == ""


class TestFormatMessageSummary:
    def test_formats_basic_message(self):
        msg = {
            "id": "msg123",
            "threadId": "thread456",
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "Preview of the message...",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Email"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Date", "value": "Wed, 26 Feb 2026 10:00:00 -0500"},
                ],
            },
        }
        result = _format_message_summary(msg)
        assert result["id"] == "msg123"
        assert result["thread_id"] == "thread456"
        assert result["subject"] == "Test Email"
        assert result["from"] == "sender@example.com"
        assert result["to"] == "me@example.com"
        assert result["date"] == "Wed, 26 Feb 2026 10:00:00 -0500"
        assert result["snippet"] == "Preview of the message..."
        assert "INBOX" in result["labels"]
        assert "UNREAD" in result["labels"]

    def test_missing_headers(self):
        msg = {
            "id": "msg999",
            "threadId": "thread999",
            "labelIds": [],
            "snippet": "",
            "payload": {"headers": []},
        }
        result = _format_message_summary(msg)
        assert result["id"] == "msg999"
        assert result["subject"] == ""
        assert result["from"] == ""

    def test_missing_payload(self):
        msg = {"id": "msg_no_payload"}
        result = _format_message_summary(msg)
        assert result["id"] == "msg_no_payload"
        assert result["subject"] == ""
        assert result["labels"] == []


class TestParseMessageListResponse:
    def test_parses_multiple_messages(self):
        messages = [
            {
                "id": "a",
                "threadId": "t1",
                "labelIds": ["INBOX"],
                "snippet": "Hello",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "First"},
                    ],
                },
            },
            {
                "id": "b",
                "threadId": "t2",
                "labelIds": [],
                "snippet": "World",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Second"},
                    ],
                },
            },
        ]
        result = _parse_message_list_response(messages)
        assert result["count"] == 2
        assert len(result["messages"]) == 2
        assert result["messages"][0]["id"] == "a"
        assert result["messages"][0]["subject"] == "First"
        assert result["messages"][1]["id"] == "b"
        assert result["messages"][1]["subject"] == "Second"

    def test_empty_list(self):
        result = _parse_message_list_response([])
        assert result["count"] == 0
        assert result["messages"] == []
