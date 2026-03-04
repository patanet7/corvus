"""Behavioral tests for memory REST endpoints.

NO MOCKS. Uses real FastAPI app + real AgentsHub + real MemoryHub + real SQLite.
"""

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.api.memory import configure, router
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.memory import MemoryConfig, MemoryHub
from corvus.model_router import ModelRouter

_AUTH_HEADERS = {"X-Remote-User": "testuser"}


def _build_test_app(tmp_path: Path) -> FastAPI:
    agents_dir = tmp_path / "config" / "agents"
    agents_dir.mkdir(parents=True)

    personal = {
        "name": "personal",
        "description": "personal memory agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "memory": {
            "own_domain": "personal",
            "can_read_shared": True,
            "can_write": True,
            "readable_domains": [],
        },
        "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
    }
    work = {
        "name": "work",
        "description": "work memory agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "memory": {
            "own_domain": "work",
            "can_read_shared": True,
            "can_write": True,
            "readable_domains": [],
        },
        "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
    }
    (agents_dir / "personal.yaml").write_text(yaml.dump(personal))
    (agents_dir / "work.yaml").write_text(yaml.dump(work))

    registry = AgentRegistry(config_dir=agents_dir)
    registry.load()
    capabilities = CapabilitiesRegistry()
    memory_hub = MemoryHub(MemoryConfig(primary_db_path=tmp_path / "memory.sqlite"))
    model_router = ModelRouter(config={"defaults": {"model": "sonnet"}})
    emitter = EventEmitter()

    hub = AgentsHub(
        registry=registry,
        capabilities=capabilities,
        memory_hub=memory_hub,
        model_router=model_router,
        emitter=emitter,
        config_dir=tmp_path,
    )
    memory_hub.set_resolvers(
        get_memory_access_fn=hub.get_memory_access,
        get_readable_domains_fn=hub.get_readable_private_domains,
    )

    configure(memory_hub, hub)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.asyncio
class TestMemoryEndpoints:
    async def test_requires_auth(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/memory/agents")
            assert resp.status_code in (401, 403)

    async def test_list_memory_agents(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/memory/agents", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            rows = resp.json()
            ids = {row["id"] for row in rows}
            assert "personal" in ids
            assert "work" in ids
            personal = next(row for row in rows if row["id"] == "personal")
            assert personal["memory_domain"] == "personal"
            assert personal["can_write"] is True
            assert isinstance(personal["readable_private_domains"], list)

    async def test_list_memory_backends(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/memory/backends", headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert "primary" in body
            assert body["primary"]["name"] == "fts5-primary"
            assert "status" in body["primary"]
            assert "overlays" in body
            assert isinstance(body["overlays"], list)
            assert "configured_overlays" in body
            assert isinstance(body["configured_overlays"], list)

    async def test_create_search_get_forget_record(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "content": "alpha memory token for endpoint contract",
                    "visibility": "private",
                    "importance": 0.7,
                    "tags": ["alpha", "contract"],
                },
            )
            assert create.status_code == 201
            created = create.json()
            record_id = created["id"]
            assert created["domain"] == "personal"
            assert created["visibility"] == "private"

            listed = await client.get("/api/memory/records?agent=personal", headers=_AUTH_HEADERS)
            assert listed.status_code == 200
            assert any(row["id"] == record_id for row in listed.json())

            searched = await client.get(
                "/api/memory/records/search",
                params={"agent": "personal", "q": "alpha memory token"},
                headers=_AUTH_HEADERS,
            )
            assert searched.status_code == 200
            assert any(row["id"] == record_id for row in searched.json())

            fetched = await client.get(f"/api/memory/records/{record_id}?agent=personal", headers=_AUTH_HEADERS)
            assert fetched.status_code == 200
            assert fetched.json()["content"].startswith("alpha memory token")

            forgotten = await client.delete(
                f"/api/memory/records/{record_id}?agent=personal",
                headers=_AUTH_HEADERS,
            )
            assert forgotten.status_code == 200
            assert forgotten.json()["status"] == "forgotten"

            missing = await client.get(f"/api/memory/records/{record_id}?agent=personal", headers=_AUTH_HEADERS)
            assert missing.status_code == 404

    async def test_update_record(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "content": "draft memory before update",
                    "visibility": "private",
                    "importance": 0.4,
                    "tags": ["draft"],
                },
            )
            assert create.status_code == 201
            record_id = create.json()["id"]

            patch = await client.patch(
                f"/api/memory/records/{record_id}",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "content": "updated memory payload",
                    "importance": 0.82,
                    "tags": ["updated", "contract"],
                    "metadata": {"source": "test-update"},
                },
            )
            assert patch.status_code == 200
            body = patch.json()
            assert body["content"] == "updated memory payload"
            assert body["importance"] == pytest.approx(0.82)
            assert body["tags"] == ["updated", "contract"]
            assert body["metadata"]["source"] == "test-update"
            assert body["updated_at"] is not None

            fetched = await client.get(f"/api/memory/records/{record_id}?agent=personal", headers=_AUTH_HEADERS)
            assert fetched.status_code == 200
            assert fetched.json()["content"] == "updated memory payload"

            forbidden = await client.patch(
                f"/api/memory/records/{record_id}",
                headers=_AUTH_HEADERS,
                json={"agent": "work", "content": "cross-domain update attempt"},
            )
            assert forbidden.status_code == 403

    async def test_private_memory_isolation_and_forget_permissions(self, tmp_path: Path):
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "content": "private personal memory for isolation check",
                    "visibility": "private",
                },
            )
            assert created.status_code == 201
            record_id = created.json()["id"]

            work_list = await client.get("/api/memory/records?agent=work", headers=_AUTH_HEADERS)
            assert work_list.status_code == 200
            assert all(row["id"] != record_id for row in work_list.json())

            work_get = await client.get(f"/api/memory/records/{record_id}?agent=work", headers=_AUTH_HEADERS)
            assert work_get.status_code == 403

            work_forget = await client.delete(
                f"/api/memory/records/{record_id}?agent=work",
                headers=_AUTH_HEADERS,
            )
            assert work_forget.status_code == 403
