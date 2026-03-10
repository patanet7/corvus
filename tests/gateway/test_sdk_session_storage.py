"""Test SDK session ID storage in SessionManager — no mocks."""

from corvus.session_manager import SessionManager


class TestSDKSessionStorage:
    def test_store_and_get(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path=db_path)
        mgr.store_sdk_session_id("sess-1", "work", "sdk-abc-123")
        result = mgr.get_sdk_session_id("sess-1", "work")
        assert result == "sdk-abc-123"

    def test_overwrite(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path=db_path)
        mgr.store_sdk_session_id("sess-1", "work", "sdk-abc-123")
        mgr.store_sdk_session_id("sess-1", "work", "sdk-xyz-789")
        result = mgr.get_sdk_session_id("sess-1", "work")
        assert result == "sdk-xyz-789"

    def test_missing_returns_none(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path=db_path)
        result = mgr.get_sdk_session_id("sess-1", "nonexistent")
        assert result is None

    def test_multiple_agents(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path=db_path)
        mgr.store_sdk_session_id("sess-1", "work", "sdk-work-1")
        mgr.store_sdk_session_id("sess-1", "codex", "sdk-codex-1")
        assert mgr.get_sdk_session_id("sess-1", "work") == "sdk-work-1"
        assert mgr.get_sdk_session_id("sess-1", "codex") == "sdk-codex-1"

    def test_different_sessions(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path=db_path)
        mgr.store_sdk_session_id("sess-1", "work", "sdk-1")
        mgr.store_sdk_session_id("sess-2", "work", "sdk-2")
        assert mgr.get_sdk_session_id("sess-1", "work") == "sdk-1"
        assert mgr.get_sdk_session_id("sess-2", "work") == "sdk-2"
