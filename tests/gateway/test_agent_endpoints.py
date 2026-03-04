"""Behavioral tests for agent management and capabilities REST endpoints.

Uses httpx.AsyncClient against a real FastAPI app with a real AgentsHub,
AgentRegistry, and CapabilitiesRegistry backed by real YAML files on disk.

NO MOCKS. All behavioral.
"""

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.api.agents import configure, router
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.memory import MemoryConfig, MemoryHub
from corvus.model_router import ModelRouter

# Auth header for test user — must match ALLOWED_USERS in config
_AUTH_HEADERS = {"X-Remote-User": "testuser"}


def _build_test_app(tmp_path: Path) -> FastAPI:
    """Build a real FastAPI app wired to a real AgentsHub backed by tmp_path YAML files."""
    agents_dir = tmp_path / "config" / "agents"
    agents_dir.mkdir(parents=True)

    for name in ["personal", "work"]:
        data = {
            "name": name,
            "description": f"{name} test agent",
            "enabled": True,
            "models": {"complexity": "medium"},
            "memory": {"own_domain": name},
            "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
        }
        (agents_dir / f"{name}.yaml").write_text(yaml.dump(data))

    registry = AgentRegistry(config_dir=agents_dir)
    registry.load()

    caps = CapabilitiesRegistry()

    db_path = tmp_path / "hub.sqlite"
    memory_hub = MemoryHub(MemoryConfig(primary_db_path=db_path))

    model_router = ModelRouter(config={"defaults": {"model": "sonnet"}})
    emitter = EventEmitter()

    hub = AgentsHub(
        registry=registry,
        capabilities=caps,
        memory_hub=memory_hub,
        model_router=model_router,
        emitter=emitter,
        config_dir=tmp_path,
    )

    claude_home = tmp_path / "claude-home"
    configure(
        hub,
        caps,
        claude_runtime_home=claude_home,
        claude_home_scope="per_agent",
    )

    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Auth enforcement tests — verify endpoints reject unauthenticated requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAgentEndpointsAuth:
    """Verify all agent endpoints require authentication."""

    async def test_list_agents_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents")
            assert resp.status_code in (401, 403)

    async def test_get_agent_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal")
            assert resp.status_code in (401, 403)

    async def test_get_agent_prompt_preview_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal/prompt-preview")
            assert resp.status_code in (401, 403)

    async def test_get_agent_policy_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal/policy")
            assert resp.status_code in (401, 403)

    async def test_get_agent_todos_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal/todos")
            assert resp.status_code in (401, 403)

    async def test_create_agent_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/agents", json={"name": "x", "description": "x"})
            assert resp.status_code in (401, 403)

    async def test_delete_agent_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/agents/personal")
            assert resp.status_code in (401, 403)

    async def test_reload_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/agents/reload")
            assert resp.status_code in (401, 403)

    async def test_capabilities_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/capabilities")
            assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Agent CRUD tests — with auth headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAgentEndpoints:
    """Tests for /api/agents/* endpoints."""

    async def test_list_agents(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            names = {a["name"] for a in data}
            assert names == {"personal", "work"}
            # Each item should have expected fields
            for agent in data:
                assert "name" in agent
                assert "description" in agent
                assert "enabled" in agent
                assert "complexity" in agent
                assert "tool_modules" in agent
                assert "memory_domain" in agent
                assert "has_prompt" in agent

    async def test_get_agent(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["name"] == "personal"
            assert body["description"] == "personal test agent"
            assert body["enabled"] is True

    async def test_get_agent_not_found(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/nonexistent", headers=_AUTH_HEADERS)
            assert resp.status_code == 404

    async def test_get_agent_prompt_preview(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal/prompt-preview", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["agent"] == "personal"
            assert body["safe_mode"] is True
            assert isinstance(body["layers"], list)
            assert len(body["layers"]) >= 2

    async def test_get_agent_policy(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.patch(
                "/api/agents/personal",
                json={
                    "tools": {
                        "builtin": ["Bash"],
                        "modules": {"paperless": {"base_url": "http://local"}},
                        "confirm_gated": ["paperless.tag"],
                    }
                },
                headers=_AUTH_HEADERS,
            )
            resp = await client.get("/api/agents/personal/policy", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["agent"] == "personal"
            assert "entries" in body and isinstance(body["entries"], list)
            assert "summary" in body
            states = {entry["state"] for entry in body["entries"]}
            assert "allow" in states
            assert "confirm" in states
            assert "deny" in states

    async def test_get_agent_todos(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        todos_dir = tmp_path / "claude-home" / "users" / "testuser" / "agents" / "personal" / ".claude" / "todos"
        todos_dir.mkdir(parents=True, exist_ok=True)
        todo_file = todos_dir / "sess-123-agent-abc.json"
        todo_file.write_text(
            """
[
  {"content": "Inspect queue depth", "status": "in_progress", "activeForm": "Inspecting queue depth"},
  {"content": "Validate module health", "status": "pending"}
]
            """.strip()
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/personal/todos", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["agent"] == "personal"
            assert body["scope"] == "per_agent"
            assert body["totals"]["files"] == 1
            assert body["totals"]["items"] == 2
            assert body["totals"]["in_progress"] == 1
            assert body["totals"]["pending"] == 1
            assert len(body["files"]) == 1
            assert body["files"][0]["session_id"] == "sess-123"
            assert body["files"][0]["items"][0]["content"] == "Inspect queue depth"
            assert body["files"][0]["items"][0]["status"] == "in_progress"

    async def test_create_agent(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/agents",
                json={
                    "name": "music",
                    "description": "Music agent",
                    "memory": {"own_domain": "music"},
                },
                headers=_AUTH_HEADERS,
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "music"

            # Verify it's now in the list
            resp2 = await client.get("/api/agents", headers=_AUTH_HEADERS)
            names = {a["name"] for a in resp2.json()}
            assert "music" in names

    async def test_create_agent_invalid_spec(self, tmp_path: Path):
        """POST /api/agents with invalid body returns 422."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/agents",
                json={"not_valid": True},
                headers=_AUTH_HEADERS,
            )
            assert resp.status_code == 422

    async def test_update_agent(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/agents/personal",
                json={"description": "Updated description"},
                headers=_AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.json()["description"] == "Updated description"

    async def test_update_agent_not_found(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/agents/nonexistent",
                json={"description": "nope"},
                headers=_AUTH_HEADERS,
            )
            assert resp.status_code == 404

    async def test_deactivate_agent(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/agents/work", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            assert resp.json()["status"] == "deactivated"

            # Verify it's disabled now
            resp2 = await client.get("/api/agents/work", headers=_AUTH_HEADERS)
            assert resp2.status_code == 200
            assert resp2.json()["enabled"] is False

    async def test_deactivate_agent_not_found(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/agents/nonexistent", headers=_AUTH_HEADERS)
            assert resp.status_code == 404

    async def test_reload_agents(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/agents/reload", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert "added" in body
            assert "removed" in body
            assert "changed" in body
            assert "errors" in body


@pytest.mark.asyncio
class TestCapabilityEndpoints:
    """Tests for /api/capabilities/* endpoints."""

    async def test_list_capabilities(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/capabilities", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert "modules" in body
            assert isinstance(body["modules"], list)

    async def test_get_capability_health_unknown(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/capabilities/nonexistent", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["name"] == "nonexistent"
            assert body["status"] == "unknown"
