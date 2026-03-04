"""Behavioral tests for agent domain application service."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.agents.service import AgentsService
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.model_router import ModelRouter
from corvus.session_manager import SessionManager
from tests.conftest import make_hub


def _write_agent_spec(config_dir: Path, name: str) -> None:
    data = {
        "name": name,
        "description": f"{name} service test agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
        "memory": {"own_domain": name},
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / f"{name}.yaml").write_text(yaml.dump(data))


def _build_service(tmp_path: Path) -> tuple[AgentsService, SessionManager]:
    agents_dir = tmp_path / "config" / "agents"
    _write_agent_spec(agents_dir, "personal")
    _write_agent_spec(agents_dir, "work")

    registry = AgentRegistry(config_dir=agents_dir)
    registry.load()
    caps = CapabilitiesRegistry()
    model_router = ModelRouter(config={"defaults": {"model": "sonnet"}})
    emitter = EventEmitter()
    hub = AgentsHub(
        registry=registry,
        capabilities=caps,
        memory_hub=make_hub(tmp_path),
        model_router=model_router,
        emitter=emitter,
        config_dir=tmp_path,
    )

    session_mgr = SessionManager(db_path=tmp_path / "sessions.sqlite")
    service = AgentsService(
        hub=hub,
        capabilities=caps,
        session_mgr=session_mgr,
        model_router=model_router,
        claude_runtime_home=tmp_path / "claude-home",
        claude_home_scope="per_agent",
    )
    return service, session_mgr


class TestAgentsService:
    def test_list_agents_includes_runtime_fields(self, tmp_path: Path) -> None:
        service, session_mgr = _build_service(tmp_path)

        session_mgr.start("sess-a", user="alice")
        session_mgr.create_dispatch(
            "disp-a",
            session_id="sess-a",
            user="alice",
            prompt="test",
            dispatch_mode="direct",
            target_agents=["personal"],
            status="running",
        )
        session_mgr.start_agent_run(
            "run-a",
            dispatch_id="disp-a",
            session_id="sess-a",
            agent="personal",
            status="executing",
        )

        rows = service.list_agents()
        personal = next(row for row in rows if row["name"] == "personal")
        assert personal["runtime_status"] == "busy"
        assert personal["queue_depth"] >= 1
        assert personal["current_model"] == "sonnet"

    def test_agent_runs_are_user_scoped(self, tmp_path: Path) -> None:
        service, session_mgr = _build_service(tmp_path)

        session_mgr.start("sess-alice", user="alice")
        session_mgr.create_dispatch(
            "disp-alice",
            session_id="sess-alice",
            user="alice",
            prompt="a",
            dispatch_mode="direct",
            target_agents=["work"],
        )
        session_mgr.start_agent_run(
            "run-alice",
            dispatch_id="disp-alice",
            session_id="sess-alice",
            agent="work",
            status="done",
        )

        session_mgr.start("sess-bob", user="bob")
        session_mgr.create_dispatch(
            "disp-bob",
            session_id="sess-bob",
            user="bob",
            prompt="b",
            dispatch_mode="direct",
            target_agents=["work"],
        )
        session_mgr.start_agent_run(
            "run-bob",
            dispatch_id="disp-bob",
            session_id="sess-bob",
            agent="work",
            status="done",
        )

        alice_runs = service.list_agent_runs(name="work", user="alice")
        bob_runs = service.list_agent_runs(name="work", user="bob")

        assert len(alice_runs) == 1
        assert len(bob_runs) == 1
        assert alice_runs[0]["id"] == "run-alice"
        assert bob_runs[0]["id"] == "run-bob"

    def test_unknown_agent_raises_key_error(self, tmp_path: Path) -> None:
        service, _session_mgr = _build_service(tmp_path)
        with pytest.raises(KeyError):
            service.list_agent_sessions(name="nonexistent", user="alice")

    def test_get_agent_prompt_preview_safe_mode(self, tmp_path: Path) -> None:
        service, _session_mgr = _build_service(tmp_path)
        preview = service.get_agent_prompt_preview("personal")
        assert preview["agent"] == "personal"
        assert preview["safe_mode"] is True
        assert preview["total_layers"] >= 2
        assert any(layer["id"] == "agent_identity" for layer in preview["layers"])
        for layer in preview["layers"]:
            assert len(layer["content_preview"]) <= 1201

    def test_get_agent_policy_matrix_states(self, tmp_path: Path) -> None:
        service, _session_mgr = _build_service(tmp_path)
        service.update_agent(
            "personal",
            {
                "tools": {
                    "builtin": ["Bash"],
                    "modules": {"paperless": {"base_url": "http://local"}},
                    "confirm_gated": ["paperless.tag"],
                }
            },
        )
        payload = service.get_agent_policy("personal")
        assert payload["agent"] == "personal"
        assert payload["summary"]["total"] >= 3
        entries = {entry["key"]: entry for entry in payload["entries"]}
        assert entries["builtin:Bash"]["state"] == "allow"
        assert entries["confirm:paperless.tag"]["state"] == "confirm"
        # CapabilitiesRegistry in this test has no module registrations -> deny.
        assert entries["module:paperless"]["state"] == "deny"

    def test_list_agent_todos_reads_scoped_runtime_files(self, tmp_path: Path) -> None:
        service, _session_mgr = _build_service(tmp_path)
        todos_dir = tmp_path / "claude-home" / "users" / "alice" / "agents" / "personal" / ".claude" / "todos"
        todos_dir.mkdir(parents=True, exist_ok=True)
        (todos_dir / "sess-1-agent-aaa.json").write_text(
            """
[
  {"content": "Investigate trace lag", "status": "in_progress", "activeForm": "Investigating trace lag"},
  {"content": "Patch websocket fanout", "status": "pending"}
]
            """.strip()
        )

        payload = service.list_agent_todos(name="personal", user="alice")
        assert payload["agent"] == "personal"
        assert payload["scope"] == "per_agent"
        assert payload["totals"]["files"] == 1
        assert payload["totals"]["items"] == 2
        assert payload["totals"]["in_progress"] == 1
        assert payload["totals"]["pending"] == 1
        assert payload["files"][0]["session_id"] == "sess-1"
        assert payload["files"][0]["items"][0]["content"] == "Investigate trace lag"
