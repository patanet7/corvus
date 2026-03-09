"""AgentStack — recursive agent navigation for the Corvus TUI.

Manages a stack of AgentContext frames representing the user's current
navigation path through nested agents (e.g. work > codex > researcher).
Supports push/pop navigation, spawning background children, entering
existing children, and killing child agents.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class AgentStatus(enum.Enum):
    """Lifecycle status of an agent context."""

    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"


@dataclass
class AgentContext:
    """A single frame in the agent navigation stack."""

    agent_name: str
    session_id: str
    parent: Optional[AgentContext] = field(default=None, repr=False)
    children: list[AgentContext] = field(default_factory=list)
    token_count: int = 0
    status: AgentStatus = AgentStatus.IDLE
    status_detail: str = ""
    display_name: str = ""


class AgentStack:
    """Recursive agent navigation stack.

    The stack tracks the user's current path through nested agents.
    The bottom of the stack is the root agent; the top is the current agent.
    Children can be spawned (background) or entered (pushed onto stack).
    """

    def __init__(self) -> None:
        self._stack: list[AgentContext] = []

    @property
    def current(self) -> AgentContext:
        """Return the current (topmost) agent context.

        Raises IndexError if the stack is empty.
        """
        if not self._stack:
            raise IndexError("AgentStack is empty — no current agent")
        return self._stack[-1]

    @property
    def depth(self) -> int:
        """Return the number of agents on the stack."""
        return len(self._stack)

    @property
    def root(self) -> AgentContext:
        """Return the root (bottom) agent context.

        Raises IndexError if the stack is empty.
        """
        if not self._stack:
            raise IndexError("AgentStack is empty — no root agent")
        return self._stack[0]

    @property
    def breadcrumb(self) -> str:
        """Return a breadcrumb string like 'work > codex > researcher'."""
        return " > ".join(ctx.agent_name for ctx in self._stack)

    def push(self, agent_name: str, session_id: str) -> AgentContext:
        """Push a new agent onto the stack, setting parent/child links."""
        parent = self._stack[-1] if self._stack else None
        ctx = AgentContext(agent_name=agent_name, session_id=session_id, parent=parent)
        if parent is not None:
            parent.children.append(ctx)
        self._stack.append(ctx)
        return ctx

    def pop(self) -> AgentContext:
        """Pop the current agent off the stack and return it.

        Raises IndexError if popping would leave the stack empty (at root).
        """
        if len(self._stack) <= 1:
            raise IndexError("Cannot pop the root agent")
        return self._stack.pop()

    def pop_to_root(self) -> AgentContext:
        """Pop all agents except the root and return the root.

        Raises IndexError if the stack is empty.
        """
        if not self._stack:
            raise IndexError("AgentStack is empty — cannot pop to root")
        del self._stack[1:]
        return self._stack[0]

    def switch(self, agent_name: str, session_id: str) -> AgentContext:
        """Clear the entire stack and push a new root agent."""
        self._stack.clear()
        return self.push(agent_name, session_id)

    def spawn(self, agent_name: str, session_id: str) -> AgentContext:
        """Add a child agent to the current context WITHOUT pushing onto the stack."""
        parent = self.current
        ctx = AgentContext(agent_name=agent_name, session_id=session_id, parent=parent)
        parent.children.append(ctx)
        return ctx

    def enter(self, agent_name: str) -> AgentContext:
        """Enter an existing child of the current agent by name.

        Raises KeyError if no child with that name exists.
        """
        parent = self.current
        for child in parent.children:
            if child.agent_name == agent_name:
                self._stack.append(child)
                return child
        raise KeyError(f"No child agent named '{agent_name}'")

    def kill(self, agent_name: str) -> AgentContext:
        """Remove a child of the current agent by name and return it.

        Clears the killed context's parent link.
        Raises KeyError if no child with that name exists.
        """
        parent = self.current
        for i, child in enumerate(parent.children):
            if child.agent_name == agent_name:
                removed = parent.children.pop(i)
                removed.parent = None
                return removed
        raise KeyError(f"No child agent named '{agent_name}'")

    def find(self, agent_name: str) -> AgentContext | None:
        """Search the stack and all children for an agent by name.

        Returns None if not found.
        """
        for ctx in self._stack:
            if ctx.agent_name == agent_name:
                return ctx
            for child in ctx.children:
                if child.agent_name == agent_name:
                    return child
        return None
