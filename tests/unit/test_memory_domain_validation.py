"""Behavioral tests for cross-domain memory write validation (F-011 / SEC-009).

Validates that the API layer rejects memory writes when the requested domain
does not match the agent's own_domain.  No mocks -- real FastAPI app, real
AgentsHub, real MemoryHub backed by a real SQLite database.
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
    """Build a real FastAPI app with real hubs backed by temp SQLite."""
    agents_dir = tmp_path / "config" / "agents"
    agents_dir.mkdir(parents=True)

    personal = {
        "name": "personal",
        "description": "personal domain agent",
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
        "description": "work domain agent",
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
    finance = {
        "name": "finance",
        "description": "finance domain agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "memory": {
            "own_domain": "finance",
            "can_read_shared": True,
            "can_write": True,
            "readable_domains": [],
        },
        "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
    }
    # Agent without memory config -- defaults to shared domain, no write
    readonly = {
        "name": "readonly",
        "description": "read-only agent without memory config",
        "enabled": True,
        "models": {"complexity": "medium"},
        "tools": {"builtin": [], "modules": {}, "confirm_gated": []},
    }

    (agents_dir / "personal.yaml").write_text(yaml.dump(personal))
    (agents_dir / "work.yaml").write_text(yaml.dump(work))
    (agents_dir / "finance.yaml").write_text(yaml.dump(finance))
    (agents_dir / "readonly.yaml").write_text(yaml.dump(readonly))

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
class TestMemoryDomainValidation:
    """SEC-009: Cross-domain memory write validation at the API layer."""

    async def test_write_to_own_domain_succeeds(self, tmp_path: Path):
        """An agent writing to its own domain should succeed (201)."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "domain": "personal",
                    "content": "a valid personal memory",
                },
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["domain"] == "personal"

    async def test_write_without_domain_uses_own_domain(self, tmp_path: Path):
        """Omitting domain should default to the agent's own_domain."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "work",
                    "content": "work memory without explicit domain",
                },
            )
            assert resp.status_code == 201
            assert resp.json()["domain"] == "work"

    async def test_cross_domain_write_rejected(self, tmp_path: Path):
        """Personal agent trying to write to work domain must be rejected (403)."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "domain": "work",
                    "content": "cross-domain write attempt",
                },
            )
            assert resp.status_code == 403
            body = resp.json()
            assert "Domain mismatch" in body["error"]
            assert "personal" in body["error"]
            assert "work" in body["error"]

    async def test_cross_domain_write_rejected_finance_to_personal(self, tmp_path: Path):
        """Finance agent targeting personal domain must be rejected."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "finance",
                    "domain": "personal",
                    "content": "sneaky cross-domain write",
                },
            )
            assert resp.status_code == 403
            assert "Domain mismatch" in resp.json()["error"]

    async def test_no_agent_allows_any_domain_backward_compat(self, tmp_path: Path):
        """When no agent is specified, domain override is allowed (backward compat).

        The system picks a default agent.  Since the caller didn't claim
        to be a specific agent, no cross-domain validation applies.
        """
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "domain": "personal",
                    "content": "no agent specified, domain override allowed",
                },
            )
            # Should not be rejected with 403 -- backward compat path
            # May succeed (201) or fail for other reasons (e.g. write perms)
            # but NOT a domain mismatch error
            if resp.status_code == 403:
                assert "Domain mismatch" not in resp.json().get("error", "")

    async def test_cross_domain_write_does_not_create_record(self, tmp_path: Path):
        """Rejected cross-domain write must not persist any record."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Attempt the cross-domain write
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "domain": "work",
                    "content": "should never be persisted sentinel-xdomain",
                },
            )
            assert resp.status_code == 403

            # Verify nothing was written to the work domain
            work_records = await client.get(
                "/api/memory/records?agent=work",
                headers=_AUTH_HEADERS,
            )
            assert work_records.status_code == 200
            for record in work_records.json():
                assert "sentinel-xdomain" not in record.get("content", "")

            # Also verify nothing leaked into personal domain
            personal_records = await client.get(
                "/api/memory/records?agent=personal",
                headers=_AUTH_HEADERS,
            )
            assert personal_records.status_code == 200
            for record in personal_records.json():
                assert "sentinel-xdomain" not in record.get("content", "")

    async def test_empty_domain_string_uses_own_domain(self, tmp_path: Path):
        """An empty-string domain should fall through to own_domain, not trigger mismatch."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "work",
                    "domain": "   ",
                    "content": "whitespace-only domain field",
                },
            )
            assert resp.status_code == 201
            assert resp.json()["domain"] == "work"

    async def test_agent_matching_domain_case_sensitive(self, tmp_path: Path):
        """Domain validation is case-sensitive -- 'Personal' != 'personal'."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "domain": "Personal",
                    "content": "case mismatch attempt",
                },
            )
            assert resp.status_code == 403
            assert "Domain mismatch" in resp.json()["error"]

    async def test_valid_write_then_cross_domain_read_blocked(self, tmp_path: Path):
        """Valid write to own domain succeeds; cross-domain read is blocked."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Write to personal domain -- should succeed
            create = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "personal",
                    "content": "private personal note for read isolation test",
                    "visibility": "private",
                },
            )
            assert create.status_code == 201
            record_id = create.json()["id"]

            # Work agent should not be able to read it
            cross_read = await client.get(
                f"/api/memory/records/{record_id}?agent=work",
                headers=_AUTH_HEADERS,
            )
            assert cross_read.status_code == 403

    async def test_error_message_includes_agent_and_domains(self, tmp_path: Path):
        """The 403 error message must name the agent, own domain, and target domain."""
        app = _build_test_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/records",
                headers=_AUTH_HEADERS,
                json={
                    "agent": "work",
                    "domain": "finance",
                    "content": "cross-domain write for error message check",
                },
            )
            assert resp.status_code == 403
            error = resp.json()["error"]
            assert "work" in error
            assert "finance" in error
            assert "Domain mismatch" in error
