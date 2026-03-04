"""Contract tests for Drive/Docs tools against a fake Drive API server.

NO mocks. Real HTTP requests to a real BaseHTTPRequestHandler server.
Tests verify the tool→API contract: input shapes, output shapes, status codes.
"""

import json

import pytest

from corvus.google_client import GoogleClient
from corvus.tools.drive import (
    configure,
    drive_cleanup,
    drive_create,
    drive_delete,
    drive_edit,
    drive_list,
    drive_move,
    drive_permanent_delete,
    drive_read,
    drive_share,
)
from tests.contracts.fake_drive_api import (
    SAMPLE_CSV_CONTENT,
    SAMPLE_DOC_CONTENT,
    SAMPLE_FILES,
    get_batch_updates,
    get_created_files,
    get_deleted,
    get_moved,
    get_shared,
    get_trashed,
    reset_state,
    start_fake_drive_server,
)

FAKE_TOKEN = "test-drive-token-xyz"


@pytest.fixture(autouse=True)
def _drive_server():
    """Start a fresh fake Drive server and configure tools for each test."""
    server, base_url = start_fake_drive_server()
    client = GoogleClient(
        base_url=base_url,
        static_token=FAKE_TOKEN,
        accounts={"test": {"email": "test@example.com", "token": FAKE_TOKEN}},
        default_account="test",
    )
    configure(client)
    reset_state()
    yield base_url
    server.shutdown()


def _parse_tool_content(result: dict) -> dict:
    """Extract and parse the JSON text from a tool response."""
    return json.loads(result["content"][0]["text"])


class TestDriveList:
    """Contract: drive_list → GET /drive/v3/files."""

    def test_returns_all_files(self):
        result = drive_list()
        data = _parse_tool_content(result)
        assert data["count"] == len(SAMPLE_FILES)
        assert len(data["files"]) == data["count"]

    def test_each_file_has_required_fields(self):
        result = drive_list()
        data = _parse_tool_content(result)
        for f in data["files"]:
            assert "id" in f
            assert "name" in f
            assert "mimeType" in f
            assert "modifiedTime" in f

    def test_search_by_query(self):
        result = drive_list(query="name contains 'Report'")
        data = _parse_tool_content(result)
        assert data["count"] == 1
        assert data["files"][0]["name"] == "Q4 Report"

    def test_search_no_match(self):
        result = drive_list(query="name contains 'nonexistent'")
        data = _parse_tool_content(result)
        assert data["count"] == 0
        assert data["files"] == []

    def test_response_shape(self):
        result = drive_list()
        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        json.loads(result["content"][0]["text"])


class TestDriveRead:
    """Contract: drive_read → GET metadata + export content."""

    def test_read_google_doc(self):
        result = drive_read("1BxiMVs0XRA5nFMdKvBdBZjg")
        data = _parse_tool_content(result)
        assert "metadata" in data
        assert data["metadata"]["id"] == "1BxiMVs0XRA5nFMdKvBdBZjg"
        assert data["metadata"]["name"] == "Q4 Report"
        assert data["content"] == SAMPLE_DOC_CONTENT
        assert data["export_format"] == "text/plain"

    def test_read_spreadsheet(self):
        result = drive_read("2CyiNWt1YSB6oGNeLeDeAzhi")
        data = _parse_tool_content(result)
        assert data["metadata"]["name"] == "Budget 2026.xlsx"
        assert data["content"] == SAMPLE_CSV_CONTENT
        assert data["export_format"] == "text/csv"

    def test_read_non_exportable_file(self):
        result = drive_read("3DziOXu2ZTC7pH0fMgEfBaij")
        data = _parse_tool_content(result)
        assert data["metadata"]["mimeType"] == "image/jpeg"
        assert "content" not in data

    def test_read_unknown_file(self):
        result = drive_read("nonexistent-id")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "404" in data["error"]

    def test_response_shape(self):
        result = drive_read("1BxiMVs0XRA5nFMdKvBdBZjg")
        assert result["content"][0]["type"] == "text"


class TestDriveCreate:
    """Contract: drive_create → POST /drive/v3/files."""

    def test_create_google_doc(self):
        result = drive_create(name="New Document")
        data = _parse_tool_content(result)
        assert data["name"] == "New Document"
        assert data["mimeType"] == "application/vnd.google-apps.document"
        assert "id" in data

    def test_create_with_custom_mime(self):
        result = drive_create(name="notes.txt", mime_type="text/plain")
        data = _parse_tool_content(result)
        assert data["mimeType"] == "text/plain"

    def test_create_in_folder(self):
        result = drive_create(name="In Folder", folder_id="folder-123")
        data = _parse_tool_content(result)
        assert data["name"] == "In Folder"
        # Verify server recorded the creation
        created = get_created_files()
        assert len(created) == 1
        assert created[0]["name"] == "In Folder"

    def test_created_file_has_id(self):
        result = drive_create(name="Test File")
        data = _parse_tool_content(result)
        assert data["id"].startswith("new-")

    def test_multiple_creates(self):
        drive_create(name="File A")
        drive_create(name="File B")
        created = get_created_files()
        assert len(created) == 2


class TestDriveEdit:
    """Contract: drive_edit → POST /v1/documents/{id}:batchUpdate."""

    def test_insert_text(self):
        result = drive_edit(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            insertions=[{"index": 1, "text": "Hello world"}],
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["changes_applied"] == 1

    def test_replace_text(self):
        result = drive_edit(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            replacements=[{"old": "Q4", "new": "Q1", "match_case": True}],
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["changes_applied"] == 1

    def test_mixed_operations(self):
        result = drive_edit(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            insertions=[{"index": 1, "text": "Prefix: "}],
            replacements=[{"old": "Revenue", "new": "Sales"}],
        )
        data = _parse_tool_content(result)
        assert data["changes_applied"] == 2

    def test_batch_update_recorded(self):
        drive_edit(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            insertions=[{"index": 5, "text": "test"}],
        )
        updates = get_batch_updates()
        assert len(updates) == 1
        assert updates[0]["documentId"] == "1BxiMVs0XRA5nFMdKvBdBZjg"
        assert len(updates[0]["requests"]) == 1
        assert "insertText" in updates[0]["requests"][0]

    def test_no_operations_returns_error(self):
        result = drive_edit(file_id="1BxiMVs0XRA5nFMdKvBdBZjg")
        data = _parse_tool_content(result)
        assert "error" in data


class TestDriveMove:
    """Contract: drive_move → PATCH /drive/v3/files/{id} with addParents."""

    def test_move_file(self):
        result = drive_move(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            folder_id="new-folder-123",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["moved_to"] == "new-folder-123"

    def test_move_recorded_on_server(self):
        drive_move(file_id="1BxiMVs0XRA5nFMdKvBdBZjg", folder_id="dest-folder")
        moved = get_moved()
        assert len(moved) == 1
        assert moved[0]["file_id"] == "1BxiMVs0XRA5nFMdKvBdBZjg"
        assert moved[0]["addParents"] == "dest-folder"


class TestDriveDelete:
    """Contract: drive_delete → PATCH with trashed=true."""

    def test_trash_file(self):
        result = drive_delete(file_id="1BxiMVs0XRA5nFMdKvBdBZjg")
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["trashed"] is True

    def test_trash_recorded_on_server(self):
        drive_delete(file_id="1BxiMVs0XRA5nFMdKvBdBZjg")
        trashed = get_trashed()
        assert "1BxiMVs0XRA5nFMdKvBdBZjg" in trashed


class TestDrivePermanentDelete:
    """Contract: drive_permanent_delete → DELETE /drive/v3/files/{id}."""

    def test_permanent_delete(self):
        result = drive_permanent_delete(file_id="1BxiMVs0XRA5nFMdKvBdBZjg")
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["permanently_deleted"] is True

    def test_delete_recorded_on_server(self):
        drive_permanent_delete(file_id="1BxiMVs0XRA5nFMdKvBdBZjg")
        deleted = get_deleted()
        assert "1BxiMVs0XRA5nFMdKvBdBZjg" in deleted


class TestDriveShare:
    """Contract: drive_share → POST /drive/v3/files/{id}/permissions."""

    def test_share_as_reader(self):
        result = drive_share(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            email="jane@example.com",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["shared_with"] == "jane@example.com"
        assert data["role"] == "reader"

    def test_share_as_writer(self):
        result = drive_share(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            email="jane@example.com",
            role="writer",
        )
        data = _parse_tool_content(result)
        assert data["role"] == "writer"

    def test_share_recorded_on_server(self):
        drive_share(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            email="bob@example.com",
            role="commenter",
        )
        shared = get_shared()
        assert len(shared) == 1
        assert shared[0]["file_id"] == "1BxiMVs0XRA5nFMdKvBdBZjg"
        assert shared[0]["emailAddress"] == "bob@example.com"
        assert shared[0]["role"] == "commenter"

    def test_share_has_permission_id(self):
        result = drive_share(
            file_id="1BxiMVs0XRA5nFMdKvBdBZjg",
            email="alice@example.com",
        )
        data = _parse_tool_content(result)
        assert data["permission_id"] is not None


class TestDriveCleanup:
    """Contract: drive_cleanup → search + optional trash of old files."""

    def test_dry_run_returns_all_files_no_filter(self):
        result = drive_cleanup(dry_run=True)
        data = _parse_tool_content(result)
        assert data["status"] == "dry_run"
        assert data["matched_count"] == len(SAMPLE_FILES)
        for f in data["files"]:
            assert "id" in f
            assert "name" in f

    def test_dry_run_does_not_trash(self):
        drive_cleanup(dry_run=True)
        assert get_trashed() == []

    def test_cleanup_trashes_matching_files(self):
        # older_than=0 means cutoff = now, all sample files have past dates
        result = drive_cleanup(older_than=0, dry_run=False)
        data = _parse_tool_content(result)
        assert data["status"] == "ok"
        assert data["trashed_count"] == len(SAMPLE_FILES)
        assert len(data["trashed_ids"]) == data["trashed_count"]
        # Verify trashed on server
        trashed = get_trashed()
        assert len(trashed) == len(SAMPLE_FILES)

    def test_cleanup_with_query_filter(self):
        result = drive_cleanup(query="name contains 'Report'", dry_run=True)
        data = _parse_tool_content(result)
        assert data["matched_count"] == 1
        assert data["files"][0]["name"] == "Q4 Report"


class TestDriveAuth:
    """Contract: all endpoints require valid Bearer token."""

    def test_bad_token_list(self, _drive_server):
        client = GoogleClient(
            base_url=_drive_server,
            static_token="bad-token-very-short",
            accounts={"test": {"email": "t@t.com", "token": "bad-token-very-short"}},
            default_account="test",
        )
        configure(client)
        result = drive_list()
        data = _parse_tool_content(result)
        # The fake server checks auth but any token > 7 chars is accepted
        # so we test with empty token to trigger 401
        client_no_auth = GoogleClient(
            base_url=_drive_server,
            static_token="",
            accounts={"test": {"email": "t@t.com", "token": ""}},
            default_account="test",
        )
        configure(client_no_auth)
        result = drive_list()
        data = _parse_tool_content(result)
        assert "error" in data
        assert "401" in data["error"]


class TestDriveConfigError:
    """Contract: tools error gracefully when not configured."""

    def test_unconfigured_raises(self):
        from corvus.tools import drive as drive_module

        drive_module._client = None
        with pytest.raises(RuntimeError, match="not configured"):
            drive_list()
