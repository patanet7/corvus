"""Opt-in live Google Drive API tests. Skipped unless credentials are set.

These tests hit the real Drive API to verify tool→API integration.
They only assert response shapes, not specific content (live data varies).
Read-only operations only — nothing is created, modified, or deleted.

Run manually:
    GOOGLE_ACCOUNT_personal_TOKEN=/path/to/token.json \
    GOOGLE_ACCOUNT_personal_EMAIL=you@gmail.com \
    pytest tests/integration/test_drive_live.py -v -m integration
"""

import json
import os

import pytest

from corvus.google_client import GoogleClient
from corvus.tools.drive import configure as configure_drive
from corvus.tools.drive import drive_list, drive_read

# Skip entire module if no Google credentials configured
SKIP = not os.environ.get("GOOGLE_ACCOUNT_personal_TOKEN")


@pytest.mark.integration
@pytest.mark.skipif(SKIP, reason="GOOGLE_ACCOUNT_personal_TOKEN not set — skipping live tests")
class TestDriveLiveList:
    """Live Drive API list/search tests — read-only."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        client = GoogleClient.from_env()
        configure_drive(client)
        yield
        configure_drive(GoogleClient(base_url="http://unused", static_token="unused"))

    def test_drive_list_returns_files(self):
        """drive_list returns a valid file list from the real Drive API."""
        result = drive_list(limit=5)
        assert "content" in result
        assert result["content"][0]["type"] == "text"
        content = json.loads(result["content"][0]["text"])
        assert "count" in content
        assert "files" in content
        assert isinstance(content["files"], list)
        if content["count"] > 0:
            f = content["files"][0]
            assert "id" in f
            assert "name" in f
            assert "mimeType" in f

    def test_drive_list_with_query(self):
        """drive_list handles search queries without error."""
        result = drive_list(query="name contains 'test'", limit=3)
        content = json.loads(result["content"][0]["text"])
        assert "count" in content
        assert isinstance(content["files"], list)


@pytest.mark.integration
@pytest.mark.skipif(SKIP, reason="GOOGLE_ACCOUNT_personal_TOKEN not set — skipping live tests")
class TestDriveLiveRead:
    """Live Drive API read tests — read-only."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        client = GoogleClient.from_env()
        configure_drive(client)
        yield
        configure_drive(GoogleClient(base_url="http://unused", static_token="unused"))

    def test_drive_read_existing_file(self):
        """drive_read returns metadata for an existing file."""
        list_result = drive_list(limit=1)
        list_content = json.loads(list_result["content"][0]["text"])

        if list_content.get("count", 0) == 0:
            pytest.skip("No files in Drive to read")

        file_id = list_content["files"][0]["id"]

        result = drive_read(file_id)
        content = json.loads(result["content"][0]["text"])
        assert "metadata" in content
        assert content["metadata"]["id"] == file_id

    def test_drive_read_invalid_id_returns_error(self):
        """drive_read with a bogus ID returns an error, not a crash."""
        result = drive_read("nonexistent-file-id-00000")
        content = json.loads(result["content"][0]["text"])
        assert "error" in content
