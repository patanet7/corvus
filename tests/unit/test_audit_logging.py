"""Behavioral tests for corvus.security.audit — persistent JSONL audit logging.

All tests use real temp files with cleanup. No mocks.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from corvus.security.audit import AuditEntry, AuditLog, _summarize_params


@pytest.fixture()
def audit_log(tmp_path: Path) -> AuditLog:
    """Create an AuditLog backed by a real temp file."""
    return AuditLog(tmp_path / "audit" / "tool_calls.jsonl")


class TestLogToolCall:
    """log_tool_call writes valid JSONL to a real file."""

    def test_writes_jsonl_line(self, audit_log: AuditLog, tmp_path: Path) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="sess-001",
            tool_name="file_read",
            outcome="allowed",
        )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["agent_name"] == "work"
        assert data["session_id"] == "sess-001"
        assert data["tool_name"] == "file_read"
        assert data["outcome"] == "allowed"
        assert "timestamp" in data

    def test_multiple_entries_append(self, audit_log: AuditLog, tmp_path: Path) -> None:
        for i in range(5):
            audit_log.log_tool_call(
                agent_name="finance",
                session_id=f"sess-{i:03d}",
                tool_name="api_call",
                outcome="allowed",
            )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 5
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["session_id"] == f"sess-{i:03d}"

    def test_denied_call_logged(self, audit_log: AuditLog, tmp_path: Path) -> None:
        audit_log.log_tool_call(
            agent_name="homelab",
            session_id="sess-deny",
            tool_name="shell_exec",
            outcome="denied",
            reason="tool blocked by policy",
        )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        data = json.loads(log_file.read_text().strip())
        assert data["outcome"] == "denied"
        assert data["reason"] == "tool blocked by policy"

    def test_failed_call_logged(self, audit_log: AuditLog, tmp_path: Path) -> None:
        audit_log.log_tool_call(
            agent_name="docs",
            session_id="sess-fail",
            tool_name="paperless_upload",
            outcome="failed",
            reason="connection timeout",
            duration_ms=5032.1,
        )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        data = json.loads(log_file.read_text().strip())
        assert data["outcome"] == "failed"
        assert data["reason"] == "connection timeout"
        assert data["duration_ms"] == 5032.1

    def test_params_included_when_provided(
        self, audit_log: AuditLog, tmp_path: Path
    ) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="sess-p",
            tool_name="web_search",
            outcome="allowed",
            params={"query": "corvus security"},
        )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        data = json.loads(log_file.read_text().strip())
        assert data["params_summary"] is not None
        assert "corvus security" in data["params_summary"]

    def test_params_none_when_not_provided(
        self, audit_log: AuditLog, tmp_path: Path
    ) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="sess-np",
            tool_name="list_files",
            outcome="allowed",
        )
        log_file = tmp_path / "audit" / "tool_calls.jsonl"
        data = json.loads(log_file.read_text().strip())
        assert data["params_summary"] is None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        deep_path = tmp_path / "a" / "b" / "c" / "audit.jsonl"
        log = AuditLog(deep_path)
        log.log_tool_call(
            agent_name="test",
            session_id="sess-dir",
            tool_name="noop",
            outcome="allowed",
        )
        assert deep_path.exists()


class TestReadEntries:
    """read_entries reads and filters JSONL from real files."""

    def test_empty_log_returns_empty_list(self, audit_log: AuditLog) -> None:
        entries = audit_log.read_entries()
        assert entries == []

    def test_reads_all_entries(self, audit_log: AuditLog) -> None:
        for name in ("work", "finance", "homelab"):
            audit_log.log_tool_call(
                agent_name=name,
                session_id="sess-all",
                tool_name="tool_a",
                outcome="allowed",
            )
        entries = audit_log.read_entries()
        assert len(entries) == 3
        assert all(isinstance(e, AuditEntry) for e in entries)

    def test_filter_by_agent_name(self, audit_log: AuditLog) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="s1",
            tool_name="t1",
            outcome="allowed",
        )
        audit_log.log_tool_call(
            agent_name="finance",
            session_id="s2",
            tool_name="t2",
            outcome="denied",
            reason="blocked",
        )
        audit_log.log_tool_call(
            agent_name="work",
            session_id="s3",
            tool_name="t3",
            outcome="allowed",
        )
        entries = audit_log.read_entries(agent_name="work")
        assert len(entries) == 2
        assert all(e.agent_name == "work" for e in entries)

    def test_filter_by_session_id(self, audit_log: AuditLog) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="target-sess",
            tool_name="t1",
            outcome="allowed",
        )
        audit_log.log_tool_call(
            agent_name="work",
            session_id="other-sess",
            tool_name="t2",
            outcome="allowed",
        )
        entries = audit_log.read_entries(session_id="target-sess")
        assert len(entries) == 1
        assert entries[0].session_id == "target-sess"

    def test_filter_by_both_agent_and_session(self, audit_log: AuditLog) -> None:
        audit_log.log_tool_call(
            agent_name="work",
            session_id="s1",
            tool_name="t1",
            outcome="allowed",
        )
        audit_log.log_tool_call(
            agent_name="finance",
            session_id="s1",
            tool_name="t2",
            outcome="allowed",
        )
        audit_log.log_tool_call(
            agent_name="work",
            session_id="s2",
            tool_name="t3",
            outcome="allowed",
        )
        entries = audit_log.read_entries(agent_name="work", session_id="s1")
        assert len(entries) == 1
        assert entries[0].agent_name == "work"
        assert entries[0].session_id == "s1"

    def test_entry_fields_round_trip(self, audit_log: AuditLog) -> None:
        audit_log.log_tool_call(
            agent_name="docs",
            session_id="sess-rt",
            tool_name="upload",
            outcome="failed",
            reason="disk full",
            duration_ms=123.45,
            params={"file": "report.pdf"},
        )
        entries = audit_log.read_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.agent_name == "docs"
        assert e.session_id == "sess-rt"
        assert e.tool_name == "upload"
        assert e.outcome == "failed"
        assert e.reason == "disk full"
        assert e.duration_ms == 123.45
        assert "report.pdf" in (e.params_summary or "")


class TestSummarizeParams:
    """_summarize_params truncates and redacts correctly."""

    def test_short_params_unchanged(self) -> None:
        result = _summarize_params({"key": "val"})
        parsed = json.loads(result)
        assert parsed["key"] == "val"

    def test_long_value_truncated(self) -> None:
        long_val = "x" * 100
        result = _summarize_params({"data": long_val})
        parsed = json.loads(result)
        assert len(parsed["data"]) == 50
        assert parsed["data"].endswith("...")

    def test_overall_summary_truncated(self) -> None:
        params = {f"key_{i}": f"value_{i}" for i in range(50)}
        result = _summarize_params(params, max_len=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_empty_params(self) -> None:
        result = _summarize_params({})
        assert result == "{}"
