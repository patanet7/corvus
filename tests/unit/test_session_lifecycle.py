"""Behavioral tests for session lifecycle summary building.

Tests build_session_summary with real AuditEntry instances —
no mocks, no patches. Verifies contracts: input shape to output shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from corvus.security.audit import AuditEntry
from corvus.security.session_lifecycle import (
    SessionSummary,
    ToolCallSummary,
    build_session_summary,
)


def _make_entry(
    tool_name: str,
    outcome: str,
    agent_name: str = "work",
    session_id: str = "sess-1",
) -> AuditEntry:
    """Create a real AuditEntry for testing."""
    return AuditEntry(
        timestamp=datetime.now(UTC).isoformat(),
        agent_name=agent_name,
        session_id=session_id,
        tool_name=tool_name,
        outcome=outcome,
    )


START = datetime(2026, 3, 8, 10, 0, 0, tzinfo=UTC)
END = datetime(2026, 3, 8, 10, 15, 0, tzinfo=UTC)


class TestEmptyAuditEntries:
    """No tool calls at all — pure conversation session."""

    def test_empty_entries_gives_success_outcome(self) -> None:
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-empty",
            started_at=START,
            ended_at=END,
            audit_entries=[],
        )
        assert summary.outcome == "success"
        assert summary.total_calls == 0
        assert summary.total_denied == 0
        assert summary.total_failed == 0
        assert summary.tools_used == []
        assert summary.mutations == []

    def test_empty_entries_has_correct_agent_and_session(self) -> None:
        summary = build_session_summary(
            agent_name="finance",
            session_id="sess-42",
            started_at=START,
            ended_at=END,
            audit_entries=[],
        )
        assert summary.agent_name == "finance"
        assert summary.session_id == "sess-42"


class TestAllSuccessEntries:
    """All tool calls succeeded — outcome should be success."""

    def test_all_allowed_gives_success(self) -> None:
        entries = [
            _make_entry("read_file", "allowed"),
            _make_entry("read_file", "allowed"),
            _make_entry("list_dir", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-ok",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.outcome == "success"
        assert summary.total_calls == 3
        assert summary.total_denied == 0
        assert summary.total_failed == 0

    def test_tool_stats_are_correct(self) -> None:
        entries = [
            _make_entry("read_file", "allowed"),
            _make_entry("read_file", "allowed"),
            _make_entry("list_dir", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-ok",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        # tools_used is sorted by name
        assert len(summary.tools_used) == 2
        assert summary.tools_used[0].tool_name == "list_dir"
        assert summary.tools_used[0].call_count == 1
        assert summary.tools_used[0].success_count == 1
        assert summary.tools_used[1].tool_name == "read_file"
        assert summary.tools_used[1].call_count == 2
        assert summary.tools_used[1].success_count == 2


class TestMixedOutcomes:
    """Some denied or failed — outcome should be partial."""

    def test_success_with_denials_gives_partial(self) -> None:
        entries = [
            _make_entry("read_file", "allowed"),
            _make_entry("write_file", "denied"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-mix",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.outcome == "partial"
        assert summary.total_denied == 1
        assert summary.total_failed == 0

    def test_success_with_failures_gives_partial(self) -> None:
        entries = [
            _make_entry("read_file", "allowed"),
            _make_entry("read_file", "allowed"),
            _make_entry("api_call", "failed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-mix2",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.outcome == "partial"
        assert summary.total_failed == 1


class TestMostlyFailures:
    """More failures than successes — outcome should be failed."""

    def test_more_failures_than_success_gives_failed(self) -> None:
        entries = [
            _make_entry("api_call", "failed"),
            _make_entry("api_call", "failed"),
            _make_entry("api_call", "failed"),
            _make_entry("read_file", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-fail",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.outcome == "failed"
        assert summary.total_failed == 3

    def test_all_failed_gives_failed(self) -> None:
        entries = [
            _make_entry("api_call", "failed"),
            _make_entry("api_call", "failed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-allfail",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.outcome == "failed"


class TestMutationTracking:
    """Mutations are only tracked when the tool is allowed and in mutation_tools."""

    def test_allowed_mutation_is_tracked(self) -> None:
        entries = [
            _make_entry("write_file", "allowed"),
            _make_entry("read_file", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-mut",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
            mutation_tools={"write_file", "delete_file"},
        )
        assert summary.mutations == ["write_file"]

    def test_denied_mutation_not_tracked(self) -> None:
        entries = [
            _make_entry("write_file", "denied"),
            _make_entry("read_file", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-denied-mut",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
            mutation_tools={"write_file"},
        )
        assert summary.mutations == []

    def test_failed_mutation_not_tracked(self) -> None:
        entries = [
            _make_entry("write_file", "failed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-fail-mut",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
            mutation_tools={"write_file"},
        )
        assert summary.mutations == []

    def test_duplicate_mutation_listed_once(self) -> None:
        entries = [
            _make_entry("write_file", "allowed"),
            _make_entry("write_file", "allowed"),
            _make_entry("write_file", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-dup-mut",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
            mutation_tools={"write_file"},
        )
        assert summary.mutations == ["write_file"]

    def test_no_mutation_tools_means_empty_mutations(self) -> None:
        entries = [
            _make_entry("write_file", "allowed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-no-mut",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert summary.mutations == []


class TestToolCallSummaryAggregation:
    """Verify per-tool aggregation across multiple outcomes."""

    def test_single_tool_mixed_outcomes(self) -> None:
        entries = [
            _make_entry("api_call", "allowed"),
            _make_entry("api_call", "allowed"),
            _make_entry("api_call", "denied"),
            _make_entry("api_call", "failed"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-agg",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        assert len(summary.tools_used) == 1
        tool = summary.tools_used[0]
        assert tool.tool_name == "api_call"
        assert tool.call_count == 4
        assert tool.success_count == 2
        assert tool.denied_count == 1
        assert tool.failed_count == 1

    def test_multiple_tools_sorted_by_name(self) -> None:
        entries = [
            _make_entry("zebra_tool", "allowed"),
            _make_entry("alpha_tool", "allowed"),
            _make_entry("middle_tool", "denied"),
        ]
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-sort",
            started_at=START,
            ended_at=END,
            audit_entries=entries,
        )
        names = [t.tool_name for t in summary.tools_used]
        assert names == ["alpha_tool", "middle_tool", "zebra_tool"]


class TestTimestampFormat:
    """Verify started_at and ended_at are ISO 8601 strings."""

    def test_timestamps_are_iso_format(self) -> None:
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-ts",
            started_at=START,
            ended_at=END,
            audit_entries=[],
        )
        assert summary.started_at == "2026-03-08T10:00:00+00:00"
        assert summary.ended_at == "2026-03-08T10:15:00+00:00"

    def test_naive_datetime_produces_iso_without_tz(self) -> None:
        naive_start = datetime(2026, 3, 8, 10, 0, 0)
        naive_end = datetime(2026, 3, 8, 10, 15, 0)
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-naive",
            started_at=naive_start,
            ended_at=naive_end,
            audit_entries=[],
        )
        assert summary.started_at == "2026-03-08T10:00:00"
        assert summary.ended_at == "2026-03-08T10:15:00"


class TestReturnTypes:
    """Verify the returned object is the correct type with correct field types."""

    def test_returns_session_summary_instance(self) -> None:
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-type",
            started_at=START,
            ended_at=END,
            audit_entries=[_make_entry("read_file", "allowed")],
        )
        assert isinstance(summary, SessionSummary)

    def test_tools_used_contains_tool_call_summary_instances(self) -> None:
        summary = build_session_summary(
            agent_name="work",
            session_id="sess-type2",
            started_at=START,
            ended_at=END,
            audit_entries=[_make_entry("read_file", "allowed")],
        )
        for tool in summary.tools_used:
            assert isinstance(tool, ToolCallSummary)
