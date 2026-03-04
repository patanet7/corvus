"""Agent domain application service."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from corvus.agents.hub import AgentsHub
from corvus.agents.spec import AgentSpec
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.config import CLAUDE_HOME_SCOPE, CLAUDE_RUNTIME_HOME
from corvus.gateway.options import resolve_claude_runtime_home
from corvus.model_router import ModelRouter
from corvus.permissions import build_policy_entries, normalize_permission_mode

if TYPE_CHECKING:
    from corvus.session_manager import SessionManager


class AgentsService:
    """Transport-agnostic service for agent/capability operations."""

    _ACTIVE_STATUSES = {"queued", "routing", "planning", "executing", "compacting"}

    def __init__(
        self,
        *,
        hub: AgentsHub,
        capabilities: CapabilitiesRegistry,
        session_mgr: SessionManager | None = None,
        model_router: ModelRouter | None = None,
        claude_runtime_home: Path = CLAUDE_RUNTIME_HOME,
        claude_home_scope: str = CLAUDE_HOME_SCOPE,
    ) -> None:
        self._hub = hub
        self._capabilities = capabilities
        self._session_mgr = session_mgr
        self._model_router = model_router
        self._claude_runtime_home = Path(claude_runtime_home).expanduser().resolve()
        self._claude_home_scope = claude_home_scope

    def list_agents(self) -> list[dict]:
        rows: list[dict] = []
        for agent in self._hub.list_agents():
            runs = self._session_mgr.list_agent_runs(agent.name, limit=200) if self._session_mgr else []
            active_runs = [run for run in runs if run.get("status") in self._ACTIVE_STATUSES]
            runtime_status = "offline"
            if agent.enabled:
                runtime_status = "busy" if active_runs else "active"
            model_id = self._model_router.get_model(agent.name) if self._model_router else None
            rows.append(
                {
                    "id": agent.name,
                    "name": agent.name,
                    "label": agent.name.title(),
                    "description": agent.description,
                    "enabled": agent.enabled,
                    "complexity": agent.complexity,
                    "tool_modules": agent.tool_modules,
                    "memory_domain": agent.memory_domain,
                    "has_prompt": agent.has_prompt,
                    "runtime_status": runtime_status,
                    "current_model": model_id,
                    "queue_depth": len(active_runs),
                    "last_run_at": runs[0]["started_at"] if runs else None,
                }
            )
        return rows

    def get_agent(self, name: str) -> dict | None:
        spec = self._hub.get_agent(name)
        if not spec:
            return None
        data = spec.to_dict()
        if self._model_router:
            data["resolved_model"] = self._model_router.get_model(name)
        if self._session_mgr:
            data["recent_runs"] = self._session_mgr.list_agent_runs(name, limit=50)
        return data

    def get_agent_prompt_preview(
        self,
        name: str,
        *,
        include_workspace_context: bool = False,
        max_chars: int = 12000,
        clip_chars: int = 1200,
    ) -> dict:
        if self._hub.get_agent(name) is None:
            raise KeyError(name)
        return self._hub.build_prompt_preview(
            name,
            include_workspace_context=include_workspace_context,
            max_chars=max_chars,
            clip_chars=clip_chars,
        )

    def get_agent_policy(self, name: str) -> dict:
        spec = self._hub.get_agent(name)
        if spec is None:
            raise KeyError(name)

        rows = build_policy_entries(
            agent_name=name,
            spec=spec,
            capabilities=self._capabilities,
            allow_secret_access=False,
        )
        counts = {"allow": 0, "confirm": 0, "deny": 0}
        for row in rows:
            state = row["state"]
            if state in counts:
                counts[state] += 1

        metadata_mode = None
        if isinstance(spec.metadata, dict):
            raw = spec.metadata.get("permission_mode")
            if isinstance(raw, str) and raw.strip():
                metadata_mode = raw.strip()

        return {
            "agent": name,
            "runtime": {
                "permission_mode": normalize_permission_mode(metadata_mode, fallback="default"),
            },
            "entries": rows,
            "summary": {
                "total": len(rows),
                "allow": counts["allow"],
                "confirm": counts["confirm"],
                "deny": counts["deny"],
            },
        }

    def create_agent(self, spec: AgentSpec) -> AgentSpec:
        return self._hub.create_agent(spec)

    def update_agent(self, name: str, patch: dict) -> AgentSpec:
        return self._hub.update_agent(name, patch)

    def deactivate_agent(self, name: str) -> None:
        self._hub.deactivate_agent(name)

    def reload_agents(self) -> dict:
        result = self._hub.reload()
        return {
            "added": result.added,
            "removed": result.removed,
            "changed": result.changed,
            "errors": result.errors,
        }

    def list_agent_sessions(
        self,
        *,
        name: str,
        user: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if self._hub.get_agent(name) is None:
            raise KeyError(name)
        if not self._session_mgr:
            return []
        return self._session_mgr.list_agent_sessions(name, user=user, limit=limit, offset=offset)

    def list_agent_runs(
        self,
        *,
        name: str,
        user: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        if self._hub.get_agent(name) is None:
            raise KeyError(name)
        if not self._session_mgr:
            return []

        runs = self._session_mgr.list_agent_runs(name, status=status, limit=limit, offset=offset)
        filtered: list[dict] = []
        for run in runs:
            session = self._session_mgr.get(run["session_id"])
            if session and session.get("user") == user:
                filtered.append(run)
        return filtered

    def list_agent_todos(
        self,
        *,
        name: str,
        user: str,
        limit_files: int = 20,
        limit_items: int = 200,
    ) -> dict:
        if self._hub.get_agent(name) is None:
            raise KeyError(name)
        if limit_files < 1 or limit_files > 200:
            raise ValueError("limit_files must be between 1 and 200")
        if limit_items < 1 or limit_items > 5000:
            raise ValueError("limit_items must be between 1 and 5000")

        home = resolve_claude_runtime_home(
            base_home=self._claude_runtime_home,
            scope=self._claude_home_scope,
            user=user,
            agent_name=name,
        )
        todos_dir = home / ".claude" / "todos"
        if not todos_dir.is_dir():
            return {
                "agent": name,
                "scope": self._claude_home_scope,
                "files": [],
                "totals": {
                    "files": 0,
                    "items": 0,
                    "pending": 0,
                    "in_progress": 0,
                    "completed": 0,
                    "other": 0,
                },
            }

        todo_files = sorted(
            (path for path in todos_dir.glob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit_files]

        totals = {"files": 0, "items": 0, "pending": 0, "in_progress": 0, "completed": 0, "other": 0}
        files: list[dict] = []
        for path in todo_files:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, list):
                continue

            items: list[dict] = []
            summary = {"pending": 0, "in_progress": 0, "completed": 0, "other": 0}
            for index, entry in enumerate(raw):
                if len(items) >= limit_items:
                    break
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                status_raw = str(entry.get("status", "pending")).strip().lower()
                status = (
                    status_raw
                    if status_raw in {"pending", "in_progress", "completed"}
                    else "other"
                )
                summary[status] += 1
                items.append(
                    {
                        "id": f"{path.stem}:{index}",
                        "content": content,
                        "status": status,
                        "active_form": str(entry.get("activeForm", "")).strip() or None,
                    }
                )

            if len(items) == 0:
                continue

            session_id, _, _ = path.stem.partition("-agent-")
            totals["files"] += 1
            totals["items"] += len(items)
            totals["pending"] += summary["pending"]
            totals["in_progress"] += summary["in_progress"]
            totals["completed"] += summary["completed"]
            totals["other"] += summary["other"]
            files.append(
                {
                    "id": path.stem,
                    "session_id": session_id or None,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                    "item_count": len(items),
                    "summary": summary,
                    "items": items,
                }
            )

        return {
            "agent": name,
            "scope": self._claude_home_scope,
            "files": files,
            "totals": totals,
        }

    def list_capabilities(self) -> list[str]:
        return self._capabilities.list_available()

    def capability_health(self, name: str) -> dict:
        health = self._capabilities.health(name)
        return {
            "name": health.name,
            "status": health.status,
            "message": health.detail,
        }

    def agents_health(self) -> dict:
        all_agents = self._hub.list_agents()
        enabled = [agent for agent in all_agents if agent.enabled]
        modules = self._capabilities.list_available()

        module_health: dict[str, dict[str, str]] = {}
        for module_name in modules:
            try:
                health = self._capabilities.health(module_name)
                module_health[module_name] = {"status": health.status, "detail": health.detail}
            except Exception as exc:
                module_health[module_name] = {"status": "error", "detail": str(exc)}

        return {
            "status": "ok" if enabled else "degraded",
            "agents_total": len(all_agents),
            "agents_enabled": len(enabled),
            "capability_modules": module_health,
        }
