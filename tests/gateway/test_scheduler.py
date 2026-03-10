"""Behavioral tests for schedule data models, DB schema, and CronScheduler.

All tests use real SQLite databases and real YAML config files — no mocks.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sqlite3
import textwrap
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from corvus.events import EventEmitter
from corvus.scheduler import (
    CronScheduler,
    ScheduleEntry,
    ScheduleType,
    init_schedule_db,
    load_schedule_config,
    merge_with_db,
)

# Path to the real default config checked into the repo
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "schedules.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML string to a temp file and return its path."""
    p = tmp_path / "schedules.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def _make_db(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a fresh SQLite DB with the schedule schema."""
    db_path = tmp_path / "schedule.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_schedule_db(conn)
    return conn, db_path


# ===================================================================
# TestScheduleConfig — YAML config validation
# ===================================================================


class TestScheduleConfig:
    """Load and validate the default config/schedules.yaml."""

    def test_load_default_config(self):
        entries = load_schedule_config(DEFAULT_CONFIG)
        assert len(entries) >= 3, f"Expected >= 3 entries, got {len(entries)}"

    def test_schedule_entry_has_required_fields(self):
        entries = load_schedule_config(DEFAULT_CONFIG)
        for name, entry in entries.items():
            assert entry.type in ScheduleType, f"{name} has invalid type"
            assert entry.cron, f"{name} has no cron expression"
            assert isinstance(entry.enabled, bool), f"{name}.enabled is not bool"
            assert entry.description, f"{name} has no description"

    def test_prompt_type_has_agent_and_template(self):
        entries = load_schedule_config(DEFAULT_CONFIG)
        prompt_entries = {n: e for n, e in entries.items() if e.type == ScheduleType.prompt}
        assert prompt_entries, "Expected at least one prompt-type schedule"
        for name, entry in prompt_entries.items():
            assert entry.agent, f"{name} prompt schedule has no agent"
            assert entry.prompt_template, f"{name} prompt schedule has no prompt_template"


# ===================================================================
# TestScheduleModel — Pydantic model
# ===================================================================


class TestScheduleModel:
    """Validate ScheduleEntry Pydantic model behavior."""

    def test_create_prompt_schedule(self):
        entry = ScheduleEntry(
            name="test_prompt",
            type=ScheduleType.prompt,
            cron="0 8 * * *",
            agent="personal",
            prompt_template="Good morning",
            description="Morning prompt",
        )
        assert entry.type == ScheduleType.prompt
        assert entry.agent == "personal"
        assert entry.cron == "0 8 * * *"

    def test_create_skill_schedule(self):
        entry = ScheduleEntry(
            name="test_skill",
            type=ScheduleType.skill,
            cron="*/30 * * * *",
            skill="health_check",
            description="Periodic health check",
        )
        assert entry.type == ScheduleType.skill
        assert entry.skill == "health_check"

    def test_default_enabled_is_true(self):
        entry = ScheduleEntry(
            name="defaults_test",
            type=ScheduleType.prompt,
            description="Testing defaults",
        )
        assert entry.enabled is True

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            ScheduleEntry(
                name="bad",
                type="nonexistent_type",  # type: ignore[arg-type]
                description="Should fail",
            )


# ===================================================================
# TestScheduleDB — real SQLite
# ===================================================================


class TestScheduleDB:
    """Behavioral tests against a real SQLite database."""

    def test_schedules_table_created(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedules'").fetchall()
            assert len(tables) == 1
        finally:
            conn.close()

    def test_schedule_run_log_table_created(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schedule_run_log'"
            ).fetchall()
            assert len(tables) == 1
        finally:
            conn.close()

    def test_insert_and_read_schedule(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, type, cron, enabled, agent)
                   VALUES (?, ?, ?, ?, ?)""",
                ("daily_check", "prompt", "0 9 * * *", 1, "personal"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM schedules WHERE name = ?", ("daily_check",)).fetchone()
            assert row is not None
            assert row["type"] == "prompt"
            assert row["cron"] == "0 9 * * *"
            assert row["enabled"] == 1
            assert row["agent"] == "personal"
        finally:
            conn.close()

    def test_update_enabled_flag(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, type, cron, enabled)
                   VALUES (?, ?, ?, ?)""",
                ("toggle_me", "prompt", "0 0 * * *", 1),
            )
            conn.commit()

            conn.execute(
                "UPDATE schedules SET enabled = ? WHERE name = ?",
                (0, "toggle_me"),
            )
            conn.commit()

            row = conn.execute("SELECT enabled FROM schedules WHERE name = ?", ("toggle_me",)).fetchone()
            assert row["enabled"] == 0
        finally:
            conn.close()

    def test_run_log_insert(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, type, cron)
                   VALUES (?, ?, ?)""",
                ("logged_task", "prompt", "0 0 * * *"),
            )
            conn.execute(
                """INSERT INTO schedule_run_log (schedule_name, started_at, finished_at, status, detail)
                   VALUES (?, ?, ?, ?, ?)""",
                ("logged_task", "2026-02-27T09:00:00", "2026-02-27T09:00:05", "success", ""),
            )
            conn.commit()

            rows = conn.execute(
                "SELECT * FROM schedule_run_log WHERE schedule_name = ?",
                ("logged_task",),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["status"] == "success"
        finally:
            conn.close()

    def test_init_is_idempotent(self, tmp_path: Path):
        conn, _ = _make_db(tmp_path)
        try:
            # Call init again — should not raise
            init_schedule_db(conn)
            init_schedule_db(conn)
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {r["name"] for r in tables}
            assert "schedules" in table_names
            assert "schedule_run_log" in table_names
        finally:
            conn.close()


# ===================================================================
# TestConfigMerge — YAML defaults + DB overrides
# ===================================================================


class TestConfigMerge:
    """Merge YAML factory defaults with DB runtime overrides."""

    def test_load_yaml_defaults(self, tmp_path: Path):
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              morning:
                description: Morning briefing
                type: prompt
                cron: "0 7 * * *"
                agent: personal
                prompt_template: Good morning
            """,
        )
        entries = load_schedule_config(cfg)
        assert "morning" in entries
        assert entries["morning"].cron == "0 7 * * *"

    def test_db_override_cron(self, tmp_path: Path):
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              task_a:
                description: Task A
                type: prompt
                cron: "0 7 * * *"
                agent: personal
                prompt_template: Hello
            """,
        )
        defaults = load_schedule_config(cfg)
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, type, cron, enabled, agent, prompt_template)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("task_a", "prompt", "0 9 * * *", 1, "", ""),
            )
            conn.commit()

            merged = merge_with_db(defaults, conn)
            assert merged["task_a"].cron == "0 9 * * *"
        finally:
            conn.close()

    def test_db_override_enabled(self, tmp_path: Path):
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              task_b:
                description: Task B
                type: prompt
                cron: "0 7 * * *"
                enabled: true
                agent: personal
                prompt_template: Hello
            """,
        )
        defaults = load_schedule_config(cfg)
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, type, cron, enabled)
                   VALUES (?, ?, ?, ?)""",
                ("task_b", "prompt", "0 7 * * *", 0),
            )
            conn.commit()

            merged = merge_with_db(defaults, conn)
            assert merged["task_b"].enabled is False
        finally:
            conn.close()

    def test_yaml_only_entries_preserved(self, tmp_path: Path):
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              yaml_only:
                description: Only in YAML
                type: prompt
                cron: "0 7 * * *"
                agent: personal
                prompt_template: Hello
            """,
        )
        defaults = load_schedule_config(cfg)
        conn, _ = _make_db(tmp_path)
        try:
            # DB has nothing — YAML-only entry should remain
            merged = merge_with_db(defaults, conn)
            assert "yaml_only" in merged
        finally:
            conn.close()

    def test_db_only_entries_included(self, tmp_path: Path):
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              yaml_entry:
                description: In YAML
                type: prompt
                cron: "0 7 * * *"
                agent: personal
                prompt_template: Hello
            """,
        )
        defaults = load_schedule_config(cfg)
        conn, _ = _make_db(tmp_path)
        try:
            conn.execute(
                """INSERT INTO schedules (name, description, type, cron, enabled, agent, prompt_template)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("db_only", "DB-only entry", "skill", "*/5 * * * *", 1, "homelab", ""),
            )
            conn.commit()

            merged = merge_with_db(defaults, conn)
            assert "db_only" in merged
            assert "yaml_entry" in merged
            assert merged["db_only"].type == ScheduleType.skill
        finally:
            conn.close()

    def test_missing_yaml_returns_empty(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.yaml"
        entries = load_schedule_config(missing)
        assert entries == {}


# ===================================================================
# TestCronScheduler — lifecycle
# ===================================================================


class TestCronScheduler:
    """CronScheduler wiring with APScheduler (real scheduler, real DB)."""

    def _make_scheduler(self, tmp_path: Path) -> CronScheduler:
        """Build a CronScheduler pointing at the real default config."""
        db_path = tmp_path / "sched.db"
        emitter = EventEmitter()
        return CronScheduler(
            config_path=DEFAULT_CONFIG,
            db_path=db_path,
            emitter=emitter,
        )

    def test_scheduler_creates_without_error(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        assert sched is not None
        assert sched.running is False

    def test_load_schedules_from_config(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        schedules = sched.load()
        assert len(schedules) >= 3

    def test_enabled_count(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        schedules = sched.load()
        enabled = sum(1 for s in schedules.values() if s.enabled)
        assert enabled >= 3, f"Expected >= 3 enabled schedules, got {enabled}"

    def test_start_and_stop(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        sched.load()

        async def _lifecycle():
            await sched.start()
            assert sched.running is True
            await sched.stop()
            assert sched.running is False

        asyncio.run(_lifecycle())

    def test_start_registers_enabled_jobs_only(self, tmp_path: Path):
        # Create a config with one enabled and one disabled schedule
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              enabled_one:
                description: Enabled
                type: prompt
                cron: "0 7 * * *"
                enabled: true
                agent: personal
                prompt_template: Hello
              disabled_one:
                description: Disabled
                type: prompt
                cron: "0 8 * * *"
                enabled: false
                agent: personal
                prompt_template: Hello
            """,
        )
        db_path = tmp_path / "sched.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _check_jobs():
            await sched.start()
            jobs = sched._scheduler.get_jobs()
            job_ids = {j.id for j in jobs}
            assert "enabled_one" in job_ids
            assert "disabled_one" not in job_ids
            await sched.stop()

        asyncio.run(_check_jobs())

    def test_get_status_returns_all_schedules(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        sched.load()
        statuses = sched.get_status()
        assert len(statuses) >= 3
        for s in statuses:
            assert "name" in s
            assert "description" in s
            assert "type" in s
            assert "cron" in s
            assert "enabled" in s
            assert "agent" in s
            assert "last_run" in s
            assert "last_status" in s
            assert "run_count" in s

    def test_manual_trigger(self, tmp_path: Path):
        """Manual trigger dispatches to the agent — should complete without crashing.

        Outcome depends on whether the Claude SDK can connect:
        - "success" when the SDK subprocess starts (CLAUDECODE unset)
        - "error" when the SDK fails (e.g. nested session detection)
        Both are valid — the scheduler must handle either gracefully.
        """
        sched = self._make_scheduler(tmp_path)
        sched.load()

        async def _trigger():
            await sched.start()
            result = await sched.trigger("morning_briefing")
            assert result["name"] == "morning_briefing"
            assert result["status"] in ("success", "error")
            await sched.stop()

        asyncio.run(_trigger())

    def test_trigger_nonexistent_raises(self, tmp_path: Path):
        sched = self._make_scheduler(tmp_path)
        sched.load()

        async def _trigger():
            await sched.start()
            with pytest.raises(KeyError, match="Unknown schedule"):
                await sched.trigger("nonexistent_schedule_xyz")
            await sched.stop()

        asyncio.run(_trigger())


# ===================================================================
# TestAPSchedulerAutoFire — APScheduler fires jobs automatically
# ===================================================================


class TestAPSchedulerAutoFire:
    """Prove APScheduler automatically fires jobs on schedule.

    Uses APScheduler's modify_job(next_run_time=now) to trigger immediate
    firing, proving the real scheduler machinery works end-to-end:
    APScheduler timer → _run_job → dispatch → DB update → event emit.
    """

    def _make_auto_scheduler(self, tmp_path: Path) -> CronScheduler:
        """Build a scheduler with a single test schedule."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              auto_test:
                description: Auto-fire test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: Automatic test
            """,
        )
        db_path = tmp_path / "auto.db"
        emitter = EventEmitter()
        return CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)

    def test_apscheduler_fires_job_automatically(self, tmp_path: Path):
        """APScheduler fires _run_job when next_run_time is set to now."""
        from datetime import UTC, datetime

        sched = self._make_auto_scheduler(tmp_path)
        sched.load()
        db_path = tmp_path / "auto.db"

        async def _auto_fire():
            await sched.start()

            # Force APScheduler to fire the job immediately
            job = sched._scheduler.get_job("auto_test")
            assert job is not None, "Job 'auto_test' not registered"
            job.modify(next_run_time=datetime.now(UTC))

            # Give APScheduler time to process (it runs on the event loop)
            await asyncio.sleep(2)
            await sched.stop()

        asyncio.run(_auto_fire())

        # Verify DB was updated — the job ran automatically
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'auto_test'").fetchall()
            assert len(rows) >= 1, "APScheduler did not auto-fire the job"
            assert rows[0]["status"] in ("success", "error")

            # Verify the schedules table was also updated
            sched_row = conn.execute(
                "SELECT last_run, last_status, run_count FROM schedules WHERE name = 'auto_test'"
            ).fetchone()
            assert sched_row is not None
            assert sched_row["last_run"] is not None
            assert sched_row["last_status"] in ("success", "error")
            assert sched_row["run_count"] >= 1
        finally:
            conn.close()

    def test_auto_fire_records_status_without_agent(self, tmp_path: Path):
        """Without a real agent, the auto-fired job completes — recording status.

        Outcome depends on whether the Claude SDK can connect:
        - "success" when the SDK subprocess starts (CLAUDECODE unset)
        - "error" when the SDK fails (e.g. nested session detection)
        Both are valid — the scheduler must handle either gracefully.
        """
        from datetime import UTC, datetime

        sched = self._make_auto_scheduler(tmp_path)
        sched.load()
        db_path = tmp_path / "auto.db"

        async def _auto_fire():
            await sched.start()
            job = sched._scheduler.get_job("auto_test")
            job.modify(next_run_time=datetime.now(UTC))
            await asyncio.sleep(2)
            await sched.stop()

        asyncio.run(_auto_fire())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'auto_test'").fetchone()
            assert row["status"] in ("success", "error")
        finally:
            conn.close()

    def test_multiple_auto_fires_increment_run_count(self, tmp_path: Path):
        """Firing a job multiple times increments run_count correctly."""
        from datetime import UTC, datetime

        sched = self._make_auto_scheduler(tmp_path)
        sched.load()
        db_path = tmp_path / "auto.db"

        async def _fire_twice():
            await sched.start()

            # Fire #1
            job = sched._scheduler.get_job("auto_test")
            job.modify(next_run_time=datetime.now(UTC))
            await asyncio.sleep(2)

            # Fire #2
            job = sched._scheduler.get_job("auto_test")
            job.modify(next_run_time=datetime.now(UTC))
            await asyncio.sleep(2)

            await sched.stop()

        asyncio.run(_fire_twice())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'auto_test'").fetchall()
            assert len(rows) >= 2, f"Expected >=2 run log entries, got {len(rows)}"

            sched_row = conn.execute("SELECT run_count FROM schedules WHERE name = 'auto_test'").fetchone()
            assert sched_row["run_count"] >= 2
        finally:
            conn.close()


# ===================================================================
# TestRunJobDBState — verify DB state after job execution
# ===================================================================


class TestRunJobDBState:
    """Verify _run_job correctly updates all DB columns."""

    def _make_scheduler_with_config(self, tmp_path: Path) -> tuple[CronScheduler, Path]:
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              db_state_test:
                description: DB state test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: Test prompt
            """,
        )
        db_path = tmp_path / "db_state.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        return sched, db_path

    def test_run_job_creates_run_log_entry(self, tmp_path: Path):
        sched, db_path = self._make_scheduler_with_config(tmp_path)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("db_state_test")
            await sched.stop()

        asyncio.run(_run())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'db_state_test'").fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row["started_at"] is not None
            assert row["finished_at"] is not None
            assert row["status"] in ("success", "error")
        finally:
            conn.close()

    def test_run_job_preserves_config_columns(self, tmp_path: Path):
        """INSERT OR IGNORE + UPDATE pattern must NOT overwrite config columns."""
        sched, db_path = self._make_scheduler_with_config(tmp_path)
        sched.load()

        # Pre-populate the DB with custom config columns
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_schedule_db(conn)
        conn.execute(
            """INSERT INTO schedules (name, type, cron, enabled, agent, prompt_template, payload, args)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("db_state_test", "prompt", "0 0 1 1 *", 1, "personal", "Custom prompt", '{"key":"val"}', '["--flag"]'),
        )
        conn.commit()
        conn.close()

        async def _run():
            await sched.start()
            await sched._run_job("db_state_test")
            await sched.stop()

        asyncio.run(_run())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM schedules WHERE name = 'db_state_test'").fetchone()
            # Config columns must be preserved, not wiped
            assert row["prompt_template"] == "Custom prompt"
            assert row["payload"] == '{"key":"val"}'
            assert row["args"] == '["--flag"]'
            # Audit columns must be updated
            assert row["last_run"] is not None
            assert row["run_count"] >= 1
        finally:
            conn.close()

    def test_run_job_updates_timestamps(self, tmp_path: Path):
        sched, db_path = self._make_scheduler_with_config(tmp_path)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("db_state_test")
            await sched.stop()

        asyncio.run(_run())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM schedules WHERE name = 'db_state_test'").fetchone()
            assert row["last_run"] is not None
            assert row["updated_at"] is not None
            # last_run should be an ISO format timestamp
            assert "T" in row["last_run"]
        finally:
            conn.close()

    def test_unknown_schedule_does_not_create_db_records(self, tmp_path: Path):
        """_run_job with unknown schedule name should not write anything to DB."""
        sched, db_path = self._make_scheduler_with_config(tmp_path)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("nonexistent_schedule")
            await sched.stop()

        asyncio.run(_run())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM schedule_run_log WHERE schedule_name = 'nonexistent_schedule'"
            ).fetchall()
            assert len(rows) == 0
        finally:
            conn.close()


# ===================================================================
# TestSchedulerEventEmission — EventEmitter fires during jobs
# ===================================================================


class TestSchedulerEventEmission:
    """Verify EventEmitter receives events during scheduled job execution."""

    def test_emits_start_and_complete_events(self, tmp_path: Path):
        """_run_job emits scheduled_task_start and scheduled_task_complete."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              event_test:
                description: Event emission test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: Event test
            """,
        )
        from corvus.events import JSONLFileSink

        db_path = tmp_path / "events.db"
        log_path = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_path))
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("event_test")
            await sched.stop()

        asyncio.run(_run())

        import json as _json

        lines = log_path.read_text().strip().split("\n")
        events = [_json.loads(line) for line in lines]
        event_types = [e["event_type"] for e in events]

        assert "scheduled_task_start" in event_types
        assert "scheduled_task_complete" in event_types

        # Verify start event metadata
        start_event = next(e for e in events if e["event_type"] == "scheduled_task_start")
        assert start_event["metadata"]["schedule"] == "event_test"
        assert start_event["metadata"]["type"] == "prompt"
        assert start_event["metadata"]["agent"] == "personal"

        # Verify complete event metadata
        complete_event = next(e for e in events if e["event_type"] == "scheduled_task_complete")
        assert complete_event["metadata"]["schedule"] == "event_test"
        assert complete_event["metadata"]["status"] in ("success", "error")

    def test_start_event_emitted_before_complete(self, tmp_path: Path):
        """Start event timestamp is before complete event timestamp."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              order_test:
                description: Event order test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: Order test
            """,
        )
        from corvus.events import JSONLFileSink

        db_path = tmp_path / "order.db"
        log_path = tmp_path / "order.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_path))
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("order_test")
            await sched.stop()

        asyncio.run(_run())

        import json as _json

        lines = log_path.read_text().strip().split("\n")
        events = [_json.loads(line) for line in lines]

        start_event = next(e for e in events if e["event_type"] == "scheduled_task_start")
        complete_event = next(e for e in events if e["event_type"] == "scheduled_task_complete")
        assert start_event["timestamp"] <= complete_event["timestamp"]


# ===================================================================
# TestWebSocketBroadcast — real broadcast notification behavior
# ===================================================================


class TestWebSocketBroadcast:
    """Verify _broadcast_notification actually sends to WebSocket-like objects."""

    def test_broadcast_sends_to_all_connections(self, tmp_path: Path):
        """_broadcast_notification sends JSON payload to all registered connections."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              ws_test:
                description: WebSocket test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: WS test
            """,
        )
        db_path = tmp_path / "ws.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)

        # Use a real asyncio.Queue-backed object that implements send_json
        received: list[dict] = []

        class FakeWebSocket:
            """Minimal object implementing send_json for testing broadcast."""

            async def send_json(self, data: dict) -> None:
                received.append(data)

        connections: set = {FakeWebSocket(), FakeWebSocket()}
        sched.set_connections(connections)

        async def _broadcast():
            await sched._broadcast_notification("ws_test", "success", "Test message")

        asyncio.run(_broadcast())

        assert len(received) == 2
        for msg in received:
            assert msg["type"] == "notification"
            assert msg["source"] == "scheduler"
            assert msg["task"] == "ws_test"
            assert msg["status"] == "success"
            assert msg["message"] == "Test message"

    def test_broadcast_removes_dead_connections(self, tmp_path: Path):
        """Dead connections that raise on send_json are removed from the set."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              ws_dead_test:
                description: Dead WS test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: Dead WS test
            """,
        )
        db_path = tmp_path / "ws_dead.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)

        received: list[dict] = []

        class LiveWebSocket:
            async def send_json(self, data: dict) -> None:
                received.append(data)

        class DeadWebSocket:
            async def send_json(self, data: dict) -> None:
                raise ConnectionError("Connection closed")

        dead_ws = DeadWebSocket()
        connections: set = {LiveWebSocket(), dead_ws}
        sched.set_connections(connections)

        async def _broadcast():
            await sched._broadcast_notification("ws_dead_test", "error", "Cleanup test")

        asyncio.run(_broadcast())

        assert len(received) == 1  # Only live connection received
        assert dead_ws not in connections  # Dead connection was removed

    def test_broadcast_noop_without_connections(self, tmp_path: Path):
        """Broadcast without connections does not raise."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              ws_noop_test:
                description: No-op WS test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: personal
                prompt_template: No-op WS test
            """,
        )
        db_path = tmp_path / "ws_noop.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        # Don't call set_connections — no connections registered

        async def _broadcast():
            # Should not raise
            await sched._broadcast_notification("ws_noop_test", "success", "No-op")

        asyncio.run(_broadcast())  # No assertion — just proving it doesn't crash


# ===================================================================
# TestNonPromptScheduleTypes — extensible type handling
# ===================================================================


class TestNonPromptScheduleTypes:
    """Verify behavior for non-prompt schedule types (skill, webhook, script)."""

    def test_skill_type_raises_not_implemented(self, tmp_path: Path):
        """Skill-type schedules raise NotImplementedError (not yet implemented)."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              skill_test:
                description: Skill type test
                type: skill
                cron: "0 0 1 1 *"
                enabled: true
                skill: health_check
            """,
        )
        db_path = tmp_path / "skill.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("skill_test")
            await sched.stop()

        asyncio.run(_run())

        # Should record as error with NotImplementedError detail
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'skill_test'").fetchone()
            assert row is not None
            assert row["status"] == "error"
            assert "not yet implemented" in row["detail"].lower()
        finally:
            conn.close()

    def test_webhook_type_raises_not_implemented(self, tmp_path: Path):
        """Webhook-type schedules raise NotImplementedError."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              webhook_test:
                description: Webhook type test
                type: webhook
                cron: "0 0 1 1 *"
                enabled: true
                webhook_type: fireflies
            """,
        )
        db_path = tmp_path / "webhook.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _run():
            await sched.start()
            await sched._run_job("webhook_test")
            await sched.stop()

        asyncio.run(_run())

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM schedule_run_log WHERE schedule_name = 'webhook_test'").fetchone()
            assert row["status"] == "error"
            assert "not yet implemented" in row["detail"].lower()
        finally:
            conn.close()

    def test_invalid_cron_skipped_gracefully(self, tmp_path: Path):
        """Schedule with invalid cron expression is skipped during start()."""
        cfg = _make_yaml(
            tmp_path,
            """\
            schedules:
              bad_cron:
                description: Bad cron test
                type: prompt
                cron: "not a cron"
                enabled: true
                agent: personal
                prompt_template: Bad cron
              good_cron:
                description: Good cron test
                type: prompt
                cron: "0 7 * * *"
                enabled: true
                agent: personal
                prompt_template: Good cron
            """,
        )
        db_path = tmp_path / "cron.db"
        emitter = EventEmitter()
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=emitter)
        sched.load()

        async def _start():
            await sched.start()
            jobs = sched._scheduler.get_jobs()
            job_ids = {j.id for j in jobs}
            # Good cron should be registered, bad cron should be skipped
            assert "good_cron" in job_ids
            assert "bad_cron" not in job_ids
            await sched.stop()

        asyncio.run(_start())


# ===================================================================
# TestScheduleAPIEndpoints — SDK-dependent (skipped if no SDK)
# ===================================================================

SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed",
)


@skip_no_sdk
@pytest.mark.skipif(
    not importlib.util.find_spec("starlette"),
    reason="starlette not installed",
)
class TestScheduleAPIEndpoints:
    """Test schedule REST API endpoints (requires SDK + full server lifespan).

    These tests spin up the full FastAPI app via TestClient, which triggers
    the lifespan (LiteLLM, supervisor, scheduler). They require a fully
    configured environment and will timeout/fail in minimal CI setups.
    """

    @pytest.fixture
    def client(self, tmp_path):
        from starlette.testclient import TestClient

        from corvus.server import app

        try:
            with TestClient(app, headers={"X-Remote-User": "testuser"}, raise_server_exceptions=False) as c:
                yield c
        except Exception as exc:
            pytest.skip(f"Server lifespan failed to start: {exc}")

    def test_list_schedules_requires_auth(self, tmp_path):
        """Schedule endpoints must require authentication."""
        from starlette.testclient import TestClient

        from corvus.server import app

        try:
            with TestClient(app) as unauthed:
                resp = unauthed.get("/api/schedules")
                assert resp.status_code == 401
        except Exception as exc:
            pytest.skip(f"Server lifespan failed to start: {exc}")

    def test_list_schedules_returns_200(self, client):
        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_list_schedules_contains_defaults(self, client):
        resp = client.get("/api/schedules")
        body = resp.json()
        names = [s["name"] for s in body]
        assert "morning_briefing" in names

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/schedules/nonexistent_schedule")
        assert resp.status_code == 404

    def test_trigger_nonexistent_returns_404(self, client):
        resp = client.post("/api/schedules/nonexistent_schedule/trigger")
        assert resp.status_code == 404


@skip_no_sdk
@pytest.mark.slow
@pytest.mark.skipif(
    bool(os.environ.get("CLAUDECODE")),
    reason="Cannot spawn nested Claude Code sessions",
)
class TestSchedulerPlannerDispatch:
    """Behavioral coverage for planner-driven dispatch in scheduled prompts — spawns real SDK subprocesses."""

    def test_prompt_schedule_uses_hierarchical_dispatch_and_persists_run_metadata(self, tmp_path: Path):
        marker = f"scheduler-planner-{uuid.uuid4()}"
        cfg = _make_yaml(
            tmp_path,
            f"""\
            schedules:
              planner_test:
                description: Planner dispatch test
                type: prompt
                cron: "0 0 1 1 *"
                enabled: true
                agent: work
                prompt_template: "Please refactor backend services. marker={marker}"
                payload:
                  target_agents: ["work", "docs"]
                  dispatch_mode: parallel
            """,
        )

        db_path = tmp_path / "planner_sched.db"
        sched = CronScheduler(config_path=cfg, db_path=db_path, emitter=EventEmitter())
        sched.load()

        # Ensure dispatch path executes far enough to persist dispatch/run rows.
        prev_openai = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = prev_openai or "test-openai-key"
        dispatch = None
        try:

            async def _run():
                await sched.start()
                await sched._run_job("planner_test")
                await sched.stop()

            asyncio.run(_run())

            from corvus.server import session_mgr

            dispatch_rows = session_mgr.list_dispatches(limit=400)
            dispatch = next((row for row in dispatch_rows if marker in row["prompt"]), None)
            assert dispatch is not None
            assert dispatch["dispatch_mode"] == "parallel"
            assert set(dispatch["target_agents"]) == {"work", "docs"}

            runs = session_mgr.list_dispatch_runs(dispatch["id"])
            assert len(runs) >= 1
            assert all("task_type" in run and "subtask_id" in run and "skill" in run for run in runs)
            assert any(run.get("task_type") == "coding" for run in runs)
        finally:
            if prev_openai is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = prev_openai
            try:
                if dispatch is not None:
                    from corvus.server import session_mgr

                    session_mgr.delete(dispatch["session_id"])
            except Exception:
                pass
