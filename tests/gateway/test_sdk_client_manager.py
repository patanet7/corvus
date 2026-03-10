"""Behavioral tests for SDKClientManager — no mocks."""

import time

import pytest

from corvus.gateway.sdk_client_manager import AgentClientPool, ManagedClient


class TestManagedClient:
    def test_initial_metrics_are_zero(self):
        mc = ManagedClient.create_stub(
            session_id="sess-1",
            agent_name="work",
        )
        assert mc.total_tokens == 0
        assert mc.total_cost_usd == 0.0
        assert mc.turn_count == 0
        assert mc.checkpoints == []
        assert mc.sdk_session_id is None
        assert mc.active_run is False
        assert mc.immediate_teardown is False

    def test_accumulate_metrics(self):
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc.accumulate(tokens=1500, cost_usd=0.05, sdk_session_id="sdk-abc")
        assert mc.total_tokens == 1500
        assert mc.total_cost_usd == pytest.approx(0.05)
        assert mc.turn_count == 1
        assert mc.sdk_session_id == "sdk-abc"

        mc.accumulate(tokens=800, cost_usd=0.03, sdk_session_id="sdk-abc")
        assert mc.total_tokens == 2300
        assert mc.total_cost_usd == pytest.approx(0.08)
        assert mc.turn_count == 2

    def test_track_checkpoint(self):
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc.track_checkpoint("msg-uuid-1")
        mc.track_checkpoint("msg-uuid-2")
        assert mc.checkpoints == ["msg-uuid-1", "msg-uuid-2"]


class TestAgentClientPool:
    def test_add_and_get(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        pool.add(mc)
        assert pool.get("work") is mc
        assert pool.get("nonexistent") is None

    def test_remove(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        pool.add(mc)
        removed = pool.remove("work")
        assert removed is mc
        assert pool.get("work") is None

    def test_list_all(self):
        pool = AgentClientPool()
        mc1 = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc2 = ManagedClient.create_stub(session_id="sess-1", agent_name="codex")
        pool.add(mc1)
        pool.add(mc2)
        all_clients = pool.list_all()
        assert len(all_clients) == 2
        names = {c.agent_name for c in all_clients}
        assert names == {"work", "codex"}

    def test_idle_eviction(self):
        pool = AgentClientPool()
        mc_idle = ManagedClient.create_stub(session_id="sess-1", agent_name="idle-agent")
        mc_idle.last_activity = time.monotonic() - 700  # 700s ago
        mc_idle.active_run = False

        mc_active = ManagedClient.create_stub(session_id="sess-1", agent_name="active-agent")
        mc_active.active_run = True
        mc_active.last_activity = time.monotonic() - 700  # old but active

        mc_recent = ManagedClient.create_stub(session_id="sess-1", agent_name="recent-agent")
        mc_recent.last_activity = time.monotonic()  # just used

        pool.add(mc_idle)
        pool.add(mc_active)
        pool.add(mc_recent)

        evicted = pool.collect_idle(timeout=600)
        assert len(evicted) == 1
        assert evicted[0].agent_name == "idle-agent"
        # idle agent removed from pool
        assert pool.get("idle-agent") is None
        # active and recent still there
        assert pool.get("active-agent") is not None
        assert pool.get("recent-agent") is not None

    def test_immediate_teardown_eviction(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="cron-agent")
        mc.immediate_teardown = True
        mc.active_run = False  # run complete
        pool.add(mc)

        evicted = pool.collect_idle(timeout=600)
        assert len(evicted) == 1
        assert evicted[0].agent_name == "cron-agent"
