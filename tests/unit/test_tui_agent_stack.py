"""Behavioral tests for AgentStack — recursive agent navigation."""

import pytest

from corvus.tui.core.agent_stack import AgentContext, AgentStack, AgentStatus


class TestAgentStackEmpty:
    """An empty stack has no current agent."""

    def test_current_raises_on_empty(self) -> None:
        stack = AgentStack()
        with pytest.raises(IndexError):
            _ = stack.current

    def test_root_raises_on_empty(self) -> None:
        stack = AgentStack()
        with pytest.raises(IndexError):
            _ = stack.root

    def test_depth_is_zero(self) -> None:
        stack = AgentStack()
        assert stack.depth == 0

    def test_breadcrumb_is_empty(self) -> None:
        stack = AgentStack()
        assert stack.breadcrumb == ""


class TestAgentStackPushPop:
    """Push and pop navigate the agent hierarchy."""

    def test_push_sets_current(self) -> None:
        stack = AgentStack()
        ctx = stack.push("work", "sess-1")
        assert stack.current is ctx
        assert ctx.agent_name == "work"
        assert ctx.session_id == "sess-1"

    def test_push_pop_returns_to_parent(self) -> None:
        stack = AgentStack()
        root = stack.push("work", "sess-1")
        stack.push("codex", "sess-2")
        popped = stack.pop()
        assert popped.agent_name == "codex"
        assert stack.current is root

    def test_pop_at_root_raises(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        with pytest.raises(IndexError):
            stack.pop()

    def test_pop_to_root_from_depth_3(self) -> None:
        stack = AgentStack()
        root = stack.push("work", "sess-1")
        stack.push("codex", "sess-2")
        stack.push("researcher", "sess-3")
        assert stack.depth == 3
        result = stack.pop_to_root()
        assert result is root
        assert stack.depth == 1
        assert stack.current is root


class TestAgentStackBreadcrumb:
    """Breadcrumb shows the full navigation path."""

    def test_single_agent(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        assert stack.breadcrumb == "work"

    def test_nested_agents(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        stack.push("codex", "sess-2")
        stack.push("researcher", "sess-3")
        assert stack.breadcrumb == "work > codex > researcher"


class TestAgentStackSwitch:
    """Switch clears the stack and starts a new root."""

    def test_switch_clears_stack(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        stack.push("codex", "sess-2")
        new_root = stack.switch("personal", "sess-3")
        assert stack.depth == 1
        assert stack.current is new_root
        assert new_root.agent_name == "personal"
        assert stack.root is new_root


class TestAgentStackParentChildLinks:
    """Push establishes parent/child relationships."""

    def test_push_sets_parent_link(self) -> None:
        stack = AgentStack()
        parent = stack.push("work", "sess-1")
        child = stack.push("codex", "sess-2")
        assert child.parent is parent

    def test_push_sets_child_link(self) -> None:
        stack = AgentStack()
        parent = stack.push("work", "sess-1")
        child = stack.push("codex", "sess-2")
        assert child in parent.children

    def test_root_has_no_parent(self) -> None:
        stack = AgentStack()
        root = stack.push("work", "sess-1")
        assert root.parent is None


class TestAgentStackSpawn:
    """Spawn adds a child without pushing onto the stack."""

    def test_spawn_adds_child(self) -> None:
        stack = AgentStack()
        parent = stack.push("work", "sess-1")
        spawned = stack.spawn("background-task", "sess-bg")
        assert spawned in parent.children
        assert spawned.parent is parent
        assert stack.current is parent  # did NOT push

    def test_spawn_child_has_correct_name(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        spawned = stack.spawn("indexer", "sess-idx")
        assert spawned.agent_name == "indexer"
        assert spawned.session_id == "sess-idx"


class TestAgentStackEnter:
    """Enter navigates into an existing child by name."""

    def test_enter_existing_child(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        stack.spawn("codex", "sess-2")
        entered = stack.enter("codex")
        assert stack.current is entered
        assert entered.agent_name == "codex"

    def test_enter_unknown_child_raises(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        with pytest.raises(KeyError):
            stack.enter("nonexistent")


class TestAgentStackKill:
    """Kill removes a child by name."""

    def test_kill_removes_child(self) -> None:
        stack = AgentStack()
        parent = stack.push("work", "sess-1")
        stack.spawn("codex", "sess-2")
        killed = stack.kill("codex")
        assert killed.agent_name == "codex"
        assert killed not in parent.children
        assert killed.parent is None

    def test_kill_unknown_raises(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        with pytest.raises(KeyError):
            stack.kill("nonexistent")


class TestAgentStackFind:
    """Find searches the stack and children."""

    def test_find_on_stack(self) -> None:
        stack = AgentStack()
        root = stack.push("work", "sess-1")
        stack.push("codex", "sess-2")
        found = stack.find("work")
        assert found is root

    def test_find_spawned_child(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        spawned = stack.spawn("indexer", "sess-idx")
        found = stack.find("indexer")
        assert found is spawned

    def test_find_returns_none_for_missing(self) -> None:
        stack = AgentStack()
        stack.push("work", "sess-1")
        assert stack.find("nonexistent") is None


class TestAgentStatus:
    """Status updates on AgentContext."""

    def test_default_status_is_idle(self) -> None:
        stack = AgentStack()
        ctx = stack.push("work", "sess-1")
        assert ctx.status is AgentStatus.IDLE
        assert ctx.status_detail == ""

    def test_status_update(self) -> None:
        stack = AgentStack()
        ctx = stack.push("work", "sess-1")
        ctx.status = AgentStatus.THINKING
        ctx.status_detail = "Processing query"
        assert ctx.status is AgentStatus.THINKING
        assert ctx.status_detail == "Processing query"

    def test_all_status_values_exist(self) -> None:
        assert AgentStatus.IDLE is not None
        assert AgentStatus.THINKING is not None
        assert AgentStatus.EXECUTING is not None
        assert AgentStatus.WAITING is not None
