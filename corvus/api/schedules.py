"""Schedule management REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from corvus.auth import get_user
from corvus.scheduler import CronScheduler

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_scheduler: CronScheduler | None = None


def configure(scheduler: CronScheduler) -> None:
    """Wire router to the active CronScheduler instance."""
    if not isinstance(scheduler, CronScheduler):
        raise TypeError(f"Expected CronScheduler, got {type(scheduler).__name__}")
    global _scheduler
    _scheduler = scheduler


def _require_scheduler() -> CronScheduler:
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    return _scheduler


@router.get("")
async def list_schedules(user: str = Depends(get_user)):
    """List all schedules with status."""
    return JSONResponse(_require_scheduler().get_status())


@router.get("/{name}")
async def get_schedule(name: str, user: str = Depends(get_user)):
    """Get a single schedule's details."""
    status = _require_scheduler().get_status()
    for entry in status:
        if entry["name"] == name:
            return JSONResponse(entry)
    return JSONResponse({"error": f"Schedule not found: {name}"}, status_code=404)


@router.patch("/{name}")
async def update_schedule(name: str, request: Request, user: str = Depends(get_user)):
    """Update enabled/cron/prompt schedule fields in the DB."""
    scheduler = _require_scheduler()
    if name not in scheduler.schedules:
        return JSONResponse({"error": f"Schedule not found: {name}"}, status_code=404)

    body = await request.json()
    conn = scheduler._connect()
    try:
        entry = scheduler.schedules[name]
        conn.execute(
            "INSERT OR REPLACE INTO schedules (name, type, agent, cron, enabled, prompt_template) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                entry.type.value,
                body.get("agent", entry.agent),
                body.get("cron", entry.cron),
                int(body.get("enabled", entry.enabled)),
                body.get("prompt", entry.prompt_template),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    scheduler.load()
    return JSONResponse({"status": "updated", "name": name})


@router.post("/{name}/trigger")
async def trigger_schedule(name: str, user: str = Depends(get_user)):
    """Manually trigger a schedule."""
    try:
        result = await _require_scheduler().trigger(name)
    except KeyError:
        return JSONResponse({"error": f"Schedule not found: {name}"}, status_code=404)
    return JSONResponse(result)
