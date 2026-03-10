"""Schedule data models, DB schema, and CronScheduler with APScheduler.

Provides:
- ScheduleType enum and ScheduleEntry Pydantic model
- SQLite schema for schedules + run log (idempotent)
- YAML config loading with DB merge (factory defaults + runtime overrides)
- CronScheduler class wiring APScheduler to agent dispatch
"""

from __future__ import annotations

import asyncio
import enum
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

from corvus.events import EventEmitter

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Enum & Model
# ---------------------------------------------------------------------------


class ScheduleType(enum.StrEnum):
    """Supported schedule dispatch types."""

    prompt = "prompt"
    skill = "skill"
    webhook = "webhook"
    script = "script"


class ScheduleEntry(BaseModel):
    """A single schedule definition."""

    name: str
    description: str = ""
    type: ScheduleType
    cron: str = "0 0 * * *"
    enabled: bool = True
    agent: str = ""
    prompt_template: str = ""
    skill: str = ""
    webhook_type: str = ""
    payload: dict[str, Any] | None = None
    script: str = ""
    args: list[str] | None = None


# ---------------------------------------------------------------------------
# DB Schema
# ---------------------------------------------------------------------------


def init_schedule_db(conn: sqlite3.Connection) -> None:
    """Create schedules + schedule_run_log tables (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schedules (
            name TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            type TEXT NOT NULL,
            cron TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            agent TEXT DEFAULT '',
            prompt_template TEXT DEFAULT '',
            skill TEXT DEFAULT '',
            webhook_type TEXT DEFAULT '',
            payload TEXT DEFAULT '',
            script TEXT DEFAULT '',
            args TEXT DEFAULT '',
            last_run TEXT,
            last_status TEXT,
            run_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS schedule_run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            detail TEXT DEFAULT '',
            FOREIGN KEY (schedule_name) REFERENCES schedules(name)
        );

        CREATE INDEX IF NOT EXISTS idx_run_log_schedule
            ON schedule_run_log(schedule_name);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Config loading & merge
# ---------------------------------------------------------------------------


def load_schedule_config(config_path: Path) -> dict[str, ScheduleEntry]:
    """Load schedule definitions from a YAML file.

    Returns an empty dict if the file is missing or malformed (fail-open).
    """
    if not config_path.exists():
        logger.warning("schedule_config_not_found", path=str(config_path))
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text())
    except Exception:
        logger.warning("schedule_config_parse_failed", path=str(config_path), exc_info=True)
        return {}

    if not isinstance(raw, dict) or "schedules" not in raw:
        logger.warning("schedule_config_missing_key", path=str(config_path), key="schedules")
        return {}

    entries: dict[str, ScheduleEntry] = {}
    schedules = raw["schedules"]
    if not isinstance(schedules, dict):
        logger.warning("schedule_config_invalid_type", path=str(config_path))
        return {}

    for name, data in schedules.items():
        try:
            if not isinstance(data, dict):
                logger.warning("schedule_entry_not_mapping", name=name)
                continue
            entries[name] = ScheduleEntry(name=name, **data)
        except Exception:
            logger.warning("schedule_entry_invalid", name=name, exc_info=True)

    return entries


def merge_with_db(
    defaults: dict[str, ScheduleEntry],
    conn: sqlite3.Connection,
) -> dict[str, ScheduleEntry]:
    """Merge YAML defaults with DB overrides.

    - DB values take precedence for: cron, enabled, agent, prompt_template, skill
    - DB-only entries are included
    - YAML-only entries are preserved
    """
    merged = dict(defaults)  # shallow copy

    old_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM schedules").fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist yet — nothing to merge
        conn.row_factory = old_row_factory
        return merged
    finally:
        conn.row_factory = old_row_factory

    for row in rows:
        name = row["name"]
        if name in merged:
            # DB overrides specific fields
            entry = merged[name]
            merged[name] = entry.model_copy(
                update={
                    "cron": row["cron"] or entry.cron,
                    "enabled": bool(row["enabled"]),
                    "agent": row["agent"] or entry.agent,
                    "prompt_template": row["prompt_template"] or entry.prompt_template,
                    "skill": row["skill"] or entry.skill,
                },
            )
        else:
            # DB-only entry
            payload_raw = row["payload"]
            payload = None
            if payload_raw:
                try:
                    payload = json.loads(payload_raw)
                except Exception:
                    pass

            args_raw = row["args"]
            args = None
            if args_raw:
                try:
                    args = json.loads(args_raw)
                except Exception:
                    pass

            merged[name] = ScheduleEntry(
                name=name,
                description=row["description"] or "",
                type=ScheduleType(row["type"]),
                cron=row["cron"],
                enabled=bool(row["enabled"]),
                agent=row["agent"] or "",
                prompt_template=row["prompt_template"] or "",
                skill=row["skill"] or "",
                webhook_type=row["webhook_type"] or "",
                payload=payload,
                script=row["script"] or "",
                args=args,
            )

    return merged


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class CronScheduler:
    """APScheduler-backed cron scheduler for Corvus scheduled tasks."""

    def __init__(
        self,
        config_path: Path,
        db_path: Path,
        emitter: EventEmitter,
    ) -> None:
        self._config_path = config_path
        self._db_path = db_path
        self._emitter = emitter
        self._scheduler = AsyncIOScheduler()
        self._schedules: dict[str, ScheduleEntry] = {}

    @property
    def running(self) -> bool:
        """Whether the APScheduler loop is running."""
        return bool(self._scheduler.running)

    @property
    def schedules(self) -> dict[str, ScheduleEntry]:
        """Read-only access to loaded schedule entries."""
        return self._schedules

    # -- DB connection -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh SQLite connection and ensure schema exists.

        Returns a new connection each time — callers must close it when done.
        This avoids sharing a single connection across async coroutines which
        is not safe with sqlite3 (no built-in async synchronisation).
        """
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        init_schedule_db(conn)
        return conn

    # -- WebSocket push notifications ----------------------------------------

    def set_connections(self, connections: set) -> None:
        """Set the WebSocket connection registry for push notifications."""
        self._connections = connections

    async def _broadcast_notification(self, schedule_name: str, status: str, message: str) -> None:
        """Push a notification to all connected WebSocket clients."""
        if not hasattr(self, "_connections") or not self._connections:
            return

        payload = {
            "type": "notification",
            "source": "scheduler",
            "task": schedule_name,
            "status": status,
            "message": message,
        }

        dead: list = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections.discard(ws)

    # -- Lifecycle -----------------------------------------------------------

    def load(self) -> dict[str, ScheduleEntry]:
        """Load schedules from config YAML and merge with DB overrides."""
        defaults = load_schedule_config(self._config_path)
        conn = self._connect()
        try:
            self._schedules = merge_with_db(defaults, conn)
        finally:
            conn.close()
        logger.info(
            "schedules_loaded",
            total=len(self._schedules),
            enabled=sum(1 for s in self._schedules.values() if s.enabled),
        )
        return self._schedules

    async def start(self) -> None:
        """Register enabled schedules as APScheduler cron jobs and start."""
        if not self._schedules:
            self.load()

        for name, entry in self._schedules.items():
            if not entry.enabled:
                continue
            try:
                trigger = CronTrigger.from_crontab(entry.cron)
            except ValueError:
                logger.warning("schedule_invalid_cron", name=name, cron=entry.cron)
                continue
            self._scheduler.add_job(
                self._run_job,
                trigger=trigger,
                args=[name],
                id=name,
                name=name,
                max_instances=3,
                replace_existing=True,
            )
            logger.debug("schedule_job_registered", name=name, cron=entry.cron)

        self._scheduler.start()
        logger.info("cron_scheduler_started")

    async def stop(self) -> None:
        """Shut down the APScheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            # AsyncIOScheduler processes shutdown on the next event-loop tick
            await asyncio.sleep(0)
            logger.info("cron_scheduler_stopped")

    # -- Job execution -------------------------------------------------------

    async def _run_job(self, schedule_name: str) -> None:
        """Execute a scheduled job: dispatch, emit events, update DB."""
        entry = self._schedules.get(schedule_name)
        if entry is None:
            logger.error("schedule_unknown", name=schedule_name)
            return

        started_at = datetime.now(UTC).isoformat()
        status = "success"
        detail = ""

        await self._emitter.emit(
            "scheduled_task_start",
            schedule=schedule_name,
            type=entry.type.value,
            agent=entry.agent,
        )

        try:
            if entry.type == ScheduleType.prompt:
                await self._dispatch_prompt(entry)
            else:
                raise NotImplementedError(f"Schedule type '{entry.type.value}' not yet implemented")
        except asyncio.CancelledError:
            status = "error"
            detail = "cancelled"
            logger.warning("schedule_cancelled", name=schedule_name)
        except Exception as exc:
            status = "error"
            detail = str(exc)
            logger.exception("schedule_failed", name=schedule_name)

        finished_at = datetime.now(UTC)

        # Update DB — use per-operation connection for async safety
        conn = self._connect()
        try:
            # First ensure the row exists
            conn.execute(
                "INSERT OR IGNORE INTO schedules (name, type, agent, cron, enabled) VALUES (?, ?, ?, ?, ?)",
                (entry.name, entry.type.value, entry.agent, entry.cron, int(entry.enabled)),
            )
            # Then update only audit columns
            conn.execute(
                "UPDATE schedules SET last_run = ?, last_status = ?, run_count = run_count + 1, updated_at = datetime('now') WHERE name = ?",
                (finished_at.isoformat(), status, entry.name),
            )
            conn.execute(
                """INSERT INTO schedule_run_log (schedule_name, started_at, finished_at, status, detail)
                   VALUES (?, ?, ?, ?, ?)""",
                (schedule_name, started_at, finished_at.isoformat(), status, detail),
            )
            conn.commit()
        finally:
            conn.close()

        await self._emitter.emit(
            "scheduled_task_complete",
            schedule=schedule_name,
            status=status,
            detail=detail,
        )

        await self._broadcast_notification(
            schedule_name,
            status,
            f"Scheduled task '{schedule_name}' completed ({status})",
        )

    async def _dispatch_prompt(self, entry: ScheduleEntry) -> None:
        """Dispatch a prompt-type schedule to the appropriate agent.

        Cross-module dependency: uses corvus.webhooks._dispatch_to_agent
        (same package, acceptable coupling — both modules share the agent
        dispatch contract).
        """
        from corvus.webhooks import _dispatch_to_agent

        payload = entry.payload or {}
        target_agents_raw = payload.get("target_agents")
        target_agents = target_agents_raw if isinstance(target_agents_raw, list) else None
        dispatch_mode_raw = payload.get("dispatch_mode")
        if isinstance(dispatch_mode_raw, str) and dispatch_mode_raw.strip():
            dispatch_mode = dispatch_mode_raw.strip().lower()
        else:
            dispatch_mode = "parallel" if target_agents else "direct"
        requested_model_raw = payload.get("model")
        requested_model = (
            str(requested_model_raw).strip()
            if isinstance(requested_model_raw, str) and requested_model_raw.strip()
            else None
        )
        session_user_raw = payload.get("user")
        session_user = (
            str(session_user_raw).strip() if isinstance(session_user_raw, str) and session_user_raw.strip() else None
        )

        result = await _dispatch_to_agent(
            agent=entry.agent,
            webhook_type=f"schedule:{entry.name}",
            prompt=entry.prompt_template,
            error_message=f"Scheduled prompt '{entry.name}' failed",
            target_agents=target_agents,
            dispatch_mode=dispatch_mode,
            requested_model=requested_model,
            source="scheduler",
            session_user=session_user,
        )
        if result is not None:
            raise RuntimeError(result.message or f"Dispatch failed for {entry.name}")

    # -- Manual trigger & status ---------------------------------------------

    async def trigger(self, schedule_name: str) -> dict[str, str]:
        """Manually trigger a schedule by name.

        Returns a dict with name and status.
        Raises KeyError for unknown schedules.
        """
        if schedule_name not in self._schedules:
            raise KeyError(f"Unknown schedule: {schedule_name}")

        await self._run_job(schedule_name)

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT last_status FROM schedules WHERE name = ?",
                (schedule_name,),
            ).fetchone()
            last_status = row["last_status"] if row else "unknown"
        finally:
            conn.close()

        return {"name": schedule_name, "status": last_status}

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all schedules."""
        conn = self._connect()
        try:
            result: list[dict[str, Any]] = []

            for name, entry in self._schedules.items():
                row = conn.execute(
                    "SELECT last_run, last_status, run_count FROM schedules WHERE name = ?",
                    (name,),
                ).fetchone()

                result.append(
                    {
                        "name": name,
                        "description": entry.description,
                        "type": entry.type.value,
                        "cron": entry.cron,
                        "enabled": entry.enabled,
                        "agent": entry.agent,
                        "last_run": row["last_run"] if row else None,
                        "last_status": row["last_status"] if row else None,
                        "run_count": row["run_count"] if row else 0,
                    }
                )

            return result
        finally:
            conn.close()
