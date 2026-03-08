# Corvus TUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a full-parity CLI chat experience using Rich + prompt_toolkit that replaces the Claude CLI wrapper and exercises the same WebSocket protocol as the SvelteKit frontend.

**Architecture:** prompt_toolkit owns the terminal layout and input handling. Rich renders output (markdown, syntax highlighting, panels). The TUI talks to the Corvus gateway via an abstract `GatewayProtocol` — in-process for v1, WebSocket for v2. Recursive `AgentStack` enables push/pop navigation into subagents.

**Tech Stack:** Python 3.11+, prompt_toolkit >=3.0, rich >=13.0, existing Corvus gateway (`corvus.gateway.runtime.GatewayRuntime`)

**Design doc:** `docs/plans/2026-03-08-corvus-tui-design.md`

---

## Phase 1: Core Chat Loop

Phase 1 delivers: launch TUI, pick an agent, send a message, see streaming output, `/quit` and `/help`.

---

### Task 1.1: Add Dependencies + Package Scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `corvus/tui/__init__.py`
- Create: `corvus/tui/__main__.py`
- Modify: `mise.toml`

**Step 1: Add `rich` dependency**

```bash
uv add rich
```

Verify `prompt-toolkit` is already in `pyproject.toml` (it is, line 30). Verify `rich` was added.

**Step 2: Create package scaffolding**

Create `corvus/tui/__init__.py`:
```python
"""Corvus TUI — Rich + prompt_toolkit CLI chat experience."""
```

Create `corvus/tui/__main__.py`:
```python
"""Entry point: python -m corvus.tui"""
from corvus.tui.app import main

main()
```

**Step 3: Add mise task**

Add to `mise.toml` after the `chat` task:
```toml
[tasks.tui]
description = "Launch Corvus TUI"
run = "uv run python -m corvus.tui"
```

**Step 4: Commit**

```bash
git add corvus/tui/__init__.py corvus/tui/__main__.py pyproject.toml mise.toml
git commit -m "feat(tui): add package scaffolding, rich dependency, mise task"
```

---

### Task 1.2: Protocol Events + Gateway Protocol Base

**Files:**
- Create: `corvus/tui/protocol/__init__.py`
- Create: `corvus/tui/protocol/events.py`
- Create: `corvus/tui/protocol/base.py`
- Test: `tests/unit/test_tui_protocol_events.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_protocol_events.py`:
```python
"""Tests for TUI protocol event types."""
from corvus.tui.protocol.events import (
    ProtocolEvent,
    DispatchStart,
    RunOutputChunk,
    ToolStart,
    ToolResult,
    ConfirmRequest,
    RunComplete,
    DispatchComplete,
    RunPhase,
    parse_event,
)


def test_parse_dispatch_start() -> None:
    raw = {"type": "dispatch_start", "dispatch_id": "d1", "session_id": "s1"}
    event = parse_event(raw)
    assert isinstance(event, DispatchStart)
    assert event.dispatch_id == "d1"


def test_parse_run_output_chunk() -> None:
    raw = {
        "type": "run_output_chunk",
        "run_id": "r1",
        "agent": "homelab",
        "chunk": "Hello ",
        "chunk_index": 0,
        "final": False,
    }
    event = parse_event(raw)
    assert isinstance(event, RunOutputChunk)
    assert event.agent == "homelab"
    assert event.chunk == "Hello "
    assert event.final is False


def test_parse_tool_start() -> None:
    raw = {
        "type": "tool_start",
        "run_id": "r1",
        "agent": "homelab",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    event = parse_event(raw)
    assert isinstance(event, ToolStart)
    assert event.tool_name == "Bash"
    assert event.tool_input == {"command": "ls"}


def test_parse_confirm_request() -> None:
    raw = {
        "type": "confirm_request",
        "run_id": "r1",
        "agent": "homelab",
        "confirm_id": "c1",
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
    }
    event = parse_event(raw)
    assert isinstance(event, ConfirmRequest)
    assert event.confirm_id == "c1"


def test_parse_unknown_event_returns_base() -> None:
    raw = {"type": "pong"}
    event = parse_event(raw)
    assert isinstance(event, ProtocolEvent)
    assert event.type == "pong"


def test_parse_run_phase() -> None:
    raw = {
        "type": "run_phase",
        "run_id": "r1",
        "agent": "homelab",
        "phase": "executing",
    }
    event = parse_event(raw)
    assert isinstance(event, RunPhase)
    assert event.phase == "executing"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_protocol_events.py -v
```
Expected: FAIL (module not found)

**Step 3: Write implementation**

Create `corvus/tui/protocol/__init__.py`:
```python
"""TUI protocol — gateway communication layer."""
```

Create `corvus/tui/protocol/events.py`:
```python
"""Protocol event types matching the WebSocket protocol in corvus.gateway.protocol.

These are the TUI-side representations of events emitted by the gateway.
The gateway emits dicts over WebSocket; parse_event() converts them to typed objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProtocolEvent:
    """Base event from gateway."""

    type: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# --- Dispatch lifecycle ---


@dataclass(slots=True)
class DispatchStart(ProtocolEvent):
    dispatch_id: str = ""
    session_id: str = ""


@dataclass(slots=True)
class DispatchPlan(ProtocolEvent):
    dispatch_id: str = ""
    routes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class DispatchComplete(ProtocolEvent):
    dispatch_id: str = ""


# --- Run lifecycle ---


@dataclass(slots=True)
class RunStart(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    model: str = ""


@dataclass(slots=True)
class RunPhase(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    phase: str = ""  # queued, routing, planning, executing, compacting, done, error


@dataclass(slots=True)
class RunOutputChunk(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    chunk: str = ""
    chunk_index: int = 0
    final: bool = False


@dataclass(slots=True)
class RunComplete(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    tokens_used: int = 0
    context_pct: float = 0.0


# --- Tool lifecycle ---


@dataclass(slots=True)
class ToolStart(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    tool_name: str = ""
    result: Any = None


# --- Confirmation ---


@dataclass(slots=True)
class ConfirmRequest(ProtocolEvent):
    run_id: str = ""
    agent: str = ""
    confirm_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConfirmResponse(ProtocolEvent):
    confirm_id: str = ""
    approved: bool = False


# --- Error ---


@dataclass(slots=True)
class ErrorEvent(ProtocolEvent):
    message: str = ""
    detail: str = ""


# --- Parse ---

_EVENT_TYPE_MAP: dict[str, type[ProtocolEvent]] = {
    "dispatch_start": DispatchStart,
    "dispatch_plan": DispatchPlan,
    "dispatch_complete": DispatchComplete,
    "run_start": RunStart,
    "run_phase": RunPhase,
    "run_output_chunk": RunOutputChunk,
    "run_complete": RunComplete,
    "tool_start": ToolStart,
    "tool_result": ToolResult,
    "confirm_request": ConfirmRequest,
    "confirm_response": ConfirmResponse,
    "error": ErrorEvent,
}


def parse_event(raw: dict[str, Any]) -> ProtocolEvent:
    """Parse a raw event dict into a typed ProtocolEvent.

    Unknown event types return a base ProtocolEvent with the raw type string.
    Fields not present in the dict default to their dataclass defaults.
    """
    event_type = raw.get("type", "unknown")
    cls = _EVENT_TYPE_MAP.get(event_type, ProtocolEvent)

    # Build kwargs from raw dict, filtering to fields the dataclass accepts
    field_names = {f.name for f in cls.__dataclass_fields__.values()} if hasattr(cls, "__dataclass_fields__") else set()
    kwargs: dict[str, Any] = {"type": event_type, "raw": raw}
    for key, value in raw.items():
        if key in field_names and key not in ("type", "raw"):
            kwargs[key] = value

    return cls(**kwargs)
```

Create `corvus/tui/protocol/base.py`:
```python
"""Abstract gateway protocol interface.

Both InProcessGateway and WebSocketGateway implement this interface.
The TUI code never knows which backend it's talking to.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from corvus.tui.protocol.events import ProtocolEvent


@dataclass(slots=True)
class SessionSummary:
    """Lightweight session info for listing."""

    session_id: str
    agent_name: str | None
    summary: str | None
    started_at: str
    message_count: int
    agents_used: list[str]


@dataclass(slots=True)
class SessionDetail(SessionSummary):
    """Full session info for resume."""

    messages: list[dict]


class GatewayProtocol(ABC):
    """Abstract interface to Corvus gateway."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_message(
        self,
        text: str,
        target_agent: str | None = None,
        target_agents: list[str] | None = None,
        dispatch_mode: str = "router",
        model: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def respond_confirm(self, confirm_id: str, approved: bool) -> None: ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> None: ...

    @abstractmethod
    async def list_sessions(self, limit: int = 20, agent: str | None = None) -> list[SessionSummary]: ...

    @abstractmethod
    async def resume_session(self, session_id: str) -> SessionDetail: ...

    @abstractmethod
    async def list_agents(self) -> list[dict]: ...

    @abstractmethod
    async def list_models(self) -> list[dict]: ...

    @abstractmethod
    def on_event(self, callback: Callable[[ProtocolEvent], Awaitable[None]]) -> None: ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_protocol_events.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/tui/protocol/ tests/unit/test_tui_protocol_events.py
git commit -m "feat(tui): add protocol event types and gateway protocol base"
```

---

### Task 1.3: Input Parser

**Files:**
- Create: `corvus/tui/input/__init__.py`
- Create: `corvus/tui/input/parser.py`
- Test: `tests/unit/test_tui_input_parser.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_input_parser.py`:
```python
"""Tests for TUI input parser."""
from corvus.tui.input.parser import InputParser, ParsedInput


def _parser() -> InputParser:
    return InputParser(known_agents=["homelab", "finance", "work", "personal"])


def test_plain_text() -> None:
    result = _parser().parse("hello world")
    assert result.kind == "chat"
    assert result.text == "hello world"
    assert result.mentions == []


def test_slash_command_no_args() -> None:
    result = _parser().parse("/help")
    assert result.kind == "command"
    assert result.command == "help"
    assert result.command_args is None


def test_slash_command_with_args() -> None:
    result = _parser().parse("/agent homelab")
    assert result.kind == "command"
    assert result.command == "agent"
    assert result.command_args == "homelab"


def test_slash_command_subcommand() -> None:
    result = _parser().parse('/memory search "corvus architecture"')
    assert result.kind == "command"
    assert result.command == "memory"
    assert result.command_args == 'search "corvus architecture"'


def test_tool_call() -> None:
    result = _parser().parse('!obsidian.search "query"')
    assert result.kind == "tool_call"
    assert result.tool_name == "obsidian.search"
    assert result.tool_args == '"query"'


def test_single_mention() -> None:
    result = _parser().parse("@homelab check nginx")
    assert result.kind == "mention"
    assert result.mentions == ["homelab"]
    assert result.text == "check nginx"


def test_multiple_mentions() -> None:
    result = _parser().parse("@homelab @finance status report")
    assert result.kind == "mention"
    assert result.mentions == ["homelab", "finance"]
    assert result.text == "status report"


def test_at_all() -> None:
    result = _parser().parse("@all how are things?")
    assert result.kind == "mention"
    assert result.mentions == ["all"]
    assert result.text == "how are things?"


def test_unknown_mention_treated_as_chat() -> None:
    result = _parser().parse("@nobody hello")
    assert result.kind == "chat"
    assert result.text == "@nobody hello"


def test_empty_input() -> None:
    result = _parser().parse("")
    assert result.kind == "chat"
    assert result.text == ""


def test_whitespace_stripped() -> None:
    result = _parser().parse("  hello  ")
    assert result.kind == "chat"
    assert result.text == "hello"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_input_parser.py -v
```
Expected: FAIL (module not found)

**Step 3: Write implementation**

Create `corvus/tui/input/__init__.py`:
```python
"""TUI input handling — editor, completions, parsing."""
```

Create `corvus/tui/input/parser.py`:
```python
"""Parse user input into structured commands, mentions, tool calls, or chat.

Parse rules (evaluated in order):
1. /command args... → kind="command"
2. !tool.name args... → kind="tool_call"
3. @agent message → kind="mention" (only if agent is known or "all")
4. Everything else → kind="chat"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedInput:
    """Result of parsing user input."""

    raw: str
    kind: str  # "command", "tool_call", "mention", "chat"
    text: str = ""
    command: str | None = None
    command_args: str | None = None
    tool_name: str | None = None
    tool_args: str | None = None
    mentions: list[str] = field(default_factory=list)


_MENTION_RE = re.compile(r"@(\w+)")


class InputParser:
    """Parses raw input text into ParsedInput."""

    def __init__(self, known_agents: list[str] | None = None) -> None:
        self._known_agents: set[str] = set(known_agents or [])
        self._known_agents.add("all")

    def update_agents(self, agents: list[str]) -> None:
        """Update the set of known agent names for @mention validation."""
        self._known_agents = set(agents)
        self._known_agents.add("all")

    def parse(self, raw: str) -> ParsedInput:
        """Parse raw input text into a structured ParsedInput."""
        stripped = raw.strip()

        # Rule 1: slash command
        if stripped.startswith("/"):
            return self._parse_command(raw, stripped)

        # Rule 2: tool call
        if stripped.startswith("!"):
            return self._parse_tool_call(raw, stripped)

        # Rule 3: @mention (only if first mention is a known agent)
        if stripped.startswith("@"):
            result = self._parse_mention(raw, stripped)
            if result is not None:
                return result

        # Rule 4: plain chat
        return ParsedInput(raw=raw, kind="chat", text=stripped)

    def _parse_command(self, raw: str, stripped: str) -> ParsedInput:
        without_slash = stripped[1:]
        parts = without_slash.split(None, 1)
        command = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else None
        return ParsedInput(
            raw=raw,
            kind="command",
            command=command,
            command_args=args,
            text=stripped,
        )

    def _parse_tool_call(self, raw: str, stripped: str) -> ParsedInput:
        without_bang = stripped[1:]
        parts = without_bang.split(None, 1)
        tool_name = parts[0] if parts else ""
        tool_args = parts[1] if len(parts) > 1 else None
        return ParsedInput(
            raw=raw,
            kind="tool_call",
            tool_name=tool_name,
            tool_args=tool_args,
            text=stripped,
        )

    def _parse_mention(self, raw: str, stripped: str) -> ParsedInput | None:
        mentions: list[str] = []
        remaining = stripped

        while remaining.startswith("@"):
            match = _MENTION_RE.match(remaining)
            if not match:
                break
            name = match.group(1)
            if name not in self._known_agents:
                return None  # unknown agent, treat as plain chat
            mentions.append(name)
            remaining = remaining[match.end():].lstrip()

        if not mentions:
            return None

        return ParsedInput(
            raw=raw,
            kind="mention",
            mentions=mentions,
            text=remaining,
        )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_input_parser.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/tui/input/ tests/unit/test_tui_input_parser.py
git commit -m "feat(tui): add input parser for /commands, @mentions, !tools, chat"
```

---

### Task 1.4: AgentStack (Core Agent Navigation)

**Files:**
- Create: `corvus/tui/core/__init__.py`
- Create: `corvus/tui/core/agent_stack.py`
- Test: `tests/unit/test_tui_agent_stack.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_agent_stack.py`:
```python
"""Tests for recursive agent stack navigation."""
import pytest

from corvus.tui.core.agent_stack import AgentStack, AgentContext, AgentStatus


def test_empty_stack_has_no_current() -> None:
    stack = AgentStack()
    assert stack.depth == 0
    with pytest.raises(IndexError):
        _ = stack.current


def test_push_sets_current() -> None:
    stack = AgentStack()
    ctx = stack.push("work", "session-1")
    assert stack.current is ctx
    assert ctx.agent_name == "work"
    assert ctx.session_id == "session-1"
    assert ctx.status == AgentStatus.IDLE
    assert stack.depth == 1


def test_push_pop_returns_to_parent() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    stack.push("codex", "s2")
    assert stack.depth == 2
    assert stack.current.agent_name == "codex"

    popped = stack.pop()
    assert popped.agent_name == "codex"
    assert stack.current.agent_name == "work"
    assert stack.depth == 1


def test_pop_at_root_raises() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    with pytest.raises(IndexError):
        stack.pop()


def test_pop_to_root() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    stack.push("codex", "s2")
    stack.push("researcher", "s3")
    assert stack.depth == 3

    root = stack.pop_to_root()
    assert root.agent_name == "work"
    assert stack.depth == 1


def test_breadcrumb() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    assert stack.breadcrumb == "work"

    stack.push("codex", "s2")
    assert stack.breadcrumb == "work > codex"

    stack.push("researcher", "s3")
    assert stack.breadcrumb == "work > codex > researcher"


def test_switch_clears_stack() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    stack.push("codex", "s2")

    stack.switch("homelab", "s3")
    assert stack.depth == 1
    assert stack.current.agent_name == "homelab"
    assert stack.breadcrumb == "homelab"


def test_push_sets_parent_child() -> None:
    stack = AgentStack()
    parent = stack.push("work", "s1")
    child = stack.push("codex", "s2")

    assert child.parent is parent
    assert child in parent.children


def test_spawn_adds_child_without_pushing() -> None:
    stack = AgentStack()
    parent = stack.push("work", "s1")
    child = stack.spawn("codex", "s2")

    assert stack.current is parent
    assert child in parent.children
    assert child.parent is parent
    assert stack.depth == 1


def test_enter_child_by_name() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    stack.spawn("codex", "s2")

    entered = stack.enter("codex")
    assert entered.agent_name == "codex"
    assert stack.depth == 2
    assert stack.current is entered


def test_enter_unknown_child_raises() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    with pytest.raises(KeyError):
        stack.enter("nonexistent")


def test_kill_removes_child() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    stack.spawn("codex", "s2")
    stack.spawn("researcher", "s3")

    stack.kill("codex")
    assert len(stack.current.children) == 1
    assert stack.current.children[0].agent_name == "researcher"


def test_kill_unknown_child_raises() -> None:
    stack = AgentStack()
    stack.push("work", "s1")
    with pytest.raises(KeyError):
        stack.kill("nonexistent")


def test_status_update() -> None:
    stack = AgentStack()
    ctx = stack.push("work", "s1")
    assert ctx.status == AgentStatus.IDLE

    ctx.status = AgentStatus.THINKING
    assert stack.current.status == AgentStatus.THINKING
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_agent_stack.py -v
```
Expected: FAIL

**Step 3: Write implementation**

Create `corvus/tui/core/__init__.py`:
```python
"""TUI core — agent stack, session management, command routing, event handling."""
```

Create `corvus/tui/core/agent_stack.py`:
```python
"""Recursive agent navigation stack.

Agents are a stack, not a flat selection. Push to enter a subagent,
pop to return to the parent. Like cd into directories.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentStatus(Enum):
    """Agent execution status."""

    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"


@dataclass
class AgentContext:
    """A single frame in the agent stack."""

    agent_name: str
    session_id: str
    parent: AgentContext | None = None
    children: list[AgentContext] = field(default_factory=list)
    token_count: int = 0
    status: AgentStatus = AgentStatus.IDLE
    status_detail: str = ""


class AgentStack:
    """Recursive agent navigation. Push to enter, pop to return."""

    def __init__(self) -> None:
        self._stack: list[AgentContext] = []

    @property
    def current(self) -> AgentContext:
        """The agent the user is currently talking to. Raises IndexError if empty."""
        return self._stack[-1]

    @property
    def depth(self) -> int:
        return len(self._stack)

    @property
    def root(self) -> AgentContext:
        """The root agent. Raises IndexError if empty."""
        return self._stack[0]

    @property
    def breadcrumb(self) -> str:
        """Breadcrumb path, e.g. 'work > codex > researcher'."""
        return " > ".join(ctx.agent_name for ctx in self._stack)

    def push(self, agent_name: str, session_id: str) -> AgentContext:
        """Enter a new agent context. If stack is non-empty, new context becomes child of current."""
        parent = self._stack[-1] if self._stack else None
        ctx = AgentContext(
            agent_name=agent_name,
            session_id=session_id,
            parent=parent,
        )
        if parent is not None:
            parent.children.append(ctx)
        self._stack.append(ctx)
        return ctx

    def pop(self) -> AgentContext:
        """Return to parent agent. Raises IndexError if at root."""
        if len(self._stack) <= 1:
            raise IndexError("Cannot pop: already at root agent")
        return self._stack.pop()

    def pop_to_root(self) -> AgentContext:
        """Return to the root agent, popping all subagent frames."""
        while len(self._stack) > 1:
            self._stack.pop()
        return self._stack[0]

    def switch(self, agent_name: str, session_id: str) -> AgentContext:
        """Switch root agent entirely. Clears the stack and pushes new root."""
        self._stack.clear()
        return self.push(agent_name, session_id)

    def spawn(self, agent_name: str, session_id: str) -> AgentContext:
        """Spawn a subagent as a child of current without entering it."""
        parent = self.current
        ctx = AgentContext(
            agent_name=agent_name,
            session_id=session_id,
            parent=parent,
        )
        parent.children.append(ctx)
        return ctx

    def enter(self, agent_name: str) -> AgentContext:
        """Enter an existing child subagent by name. Raises KeyError if not found."""
        for child in self.current.children:
            if child.agent_name == agent_name:
                self._stack.append(child)
                return child
        raise KeyError(f"No child agent named '{agent_name}'")

    def kill(self, agent_name: str) -> AgentContext:
        """Remove a child subagent by name. Raises KeyError if not found."""
        parent = self.current
        for i, child in enumerate(parent.children):
            if child.agent_name == agent_name:
                return parent.children.pop(i)
        raise KeyError(f"No child agent named '{agent_name}'")

    def find(self, agent_name: str) -> AgentContext | None:
        """Find an agent context anywhere in the stack by name."""
        for ctx in self._stack:
            if ctx.agent_name == agent_name:
                return ctx
            for child in ctx.children:
                if child.agent_name == agent_name:
                    return child
        return None
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_agent_stack.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/tui/core/ tests/unit/test_tui_agent_stack.py
git commit -m "feat(tui): add recursive AgentStack with push/pop/spawn/enter/kill"
```

---

### Task 1.5: Command Router + Registry

**Files:**
- Create: `corvus/tui/commands/__init__.py`
- Create: `corvus/tui/commands/registry.py`
- Create: `corvus/tui/core/command_router.py`
- Test: `tests/unit/test_tui_command_router.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_command_router.py`:
```python
"""Tests for command registry and tiered command routing."""
import asyncio

from corvus.tui.commands.registry import CommandRegistry, SlashCommand, InputTier
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.input.parser import InputParser, ParsedInput


def test_register_and_lookup() -> None:
    registry = CommandRegistry()
    cmd = SlashCommand(name="help", description="Show help", tier=InputTier.SYSTEM)
    registry.register(cmd)
    assert registry.lookup("help") is cmd


def test_lookup_missing_returns_none() -> None:
    registry = CommandRegistry()
    assert registry.lookup("nonexistent") is None


def test_completions() -> None:
    registry = CommandRegistry()
    registry.register(SlashCommand(name="help", description="Help", tier=InputTier.SYSTEM))
    registry.register(SlashCommand(name="history", description="History", tier=InputTier.SERVICE))
    registry.register(SlashCommand(name="quit", description="Quit", tier=InputTier.SYSTEM))

    assert registry.completions("h") == ["help", "history"]
    assert registry.completions("q") == ["quit"]
    assert registry.completions("x") == []
    assert len(registry.completions("")) == 3


def test_all_commands() -> None:
    registry = CommandRegistry()
    registry.register(SlashCommand(name="a", description="A", tier=InputTier.SYSTEM))
    registry.register(SlashCommand(name="b", description="B", tier=InputTier.SERVICE))
    assert len(registry.all_commands()) == 2


def test_router_classifies_system_command() -> None:
    registry = CommandRegistry()
    registry.register(SlashCommand(name="quit", description="Quit", tier=InputTier.SYSTEM))
    router = CommandRouter(registry=registry)
    parser = InputParser()

    parsed = parser.parse("/quit")
    tier = router.classify(parsed)
    assert tier == InputTier.SYSTEM


def test_router_classifies_unknown_command_as_agent() -> None:
    registry = CommandRegistry()
    router = CommandRouter(registry=registry)
    parser = InputParser()

    parsed = parser.parse("/unknown")
    tier = router.classify(parsed)
    assert tier == InputTier.AGENT


def test_router_classifies_chat_as_agent() -> None:
    registry = CommandRegistry()
    router = CommandRouter(registry=registry)
    parser = InputParser()

    parsed = parser.parse("hello world")
    tier = router.classify(parsed)
    assert tier == InputTier.AGENT


def test_router_classifies_mention_as_agent() -> None:
    registry = CommandRegistry()
    router = CommandRouter(registry=registry)
    parser = InputParser(known_agents=["homelab"])

    parsed = parser.parse("@homelab check logs")
    tier = router.classify(parsed)
    assert tier == InputTier.AGENT


def test_router_classifies_tool_call_as_agent() -> None:
    registry = CommandRegistry()
    router = CommandRouter(registry=registry)
    parser = InputParser()

    parsed = parser.parse("!obsidian.search query")
    tier = router.classify(parsed)
    assert tier == InputTier.AGENT
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_command_router.py -v
```

**Step 3: Write implementation**

Create `corvus/tui/commands/__init__.py`:
```python
"""TUI commands — slash command registry and built-in commands."""
```

Create `corvus/tui/commands/registry.py`:
```python
"""Slash command registry.

Commands are registered with a name, description, tier, and optional handler.
The registry provides lookup, completion, and listing.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InputTier(Enum):
    """Which layer handles this input."""

    SYSTEM = "system"    # TUI handles directly, no gateway
    SERVICE = "service"  # TUI calls a Corvus service (memory, sessions, etc.)
    AGENT = "agent"      # Routed to agent via gateway protocol


@dataclass(slots=True)
class SlashCommand:
    """A registered slash command."""

    name: str
    description: str
    tier: InputTier
    handler: Callable[..., Awaitable[None]] | None = None
    args_spec: str | None = None
    agent_scoped: bool = False


class CommandRegistry:
    """Central registry for all slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        """Register a slash command."""
        self._commands[command.name] = command

    def lookup(self, name: str) -> SlashCommand | None:
        """Look up a command by name."""
        return self._commands.get(name)

    def completions(self, partial: str) -> list[str]:
        """Return command names matching a partial string."""
        return sorted(
            name for name in self._commands
            if name.startswith(partial)
        )

    def all_commands(self) -> list[SlashCommand]:
        """Return all registered commands."""
        return list(self._commands.values())

    def commands_for_tier(self, tier: InputTier) -> list[SlashCommand]:
        """Return commands for a specific tier."""
        return [cmd for cmd in self._commands.values() if cmd.tier == tier]
```

Create `corvus/tui/core/command_router.py`:
```python
"""Three-tier input dispatch.

System commands → handled by TUI directly (no gateway, no tokens).
Service commands → TUI calls a Corvus service (memory, sessions, etc.).
Agent commands → routed to agent via gateway protocol.
"""
from __future__ import annotations

from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.input.parser import ParsedInput


class CommandRouter:
    """Routes parsed input to the correct handler tier."""

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def classify(self, parsed: ParsedInput) -> InputTier:
        """Determine which tier handles this input."""
        if parsed.kind == "command" and parsed.command:
            cmd = self._registry.lookup(parsed.command)
            if cmd is not None:
                return cmd.tier
        # Everything else (chat, mentions, tool calls, unknown commands) → agent
        return InputTier.AGENT
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_command_router.py -v
```

**Step 5: Commit**

```bash
git add corvus/tui/commands/ corvus/tui/core/command_router.py tests/unit/test_tui_command_router.py
git commit -m "feat(tui): add command registry and three-tier command router"
```

---

### Task 1.6: Theme + Output Renderer

**Files:**
- Create: `corvus/tui/theme.py`
- Create: `corvus/tui/output/__init__.py`
- Create: `corvus/tui/output/renderer.py`
- Test: `tests/unit/test_tui_renderer.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_renderer.py`:
```python
"""Tests for chat renderer — verifies Rich output generation."""
import io

from rich.console import Console

from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.theme import AGENT_COLORS, TuiTheme


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    renderer = ChatRenderer(console=console, theme=TuiTheme())
    return renderer, buf


def test_render_user_message_contains_text() -> None:
    renderer, buf = _make_renderer()
    renderer.render_user_message("hello world", agent="homelab")
    output = buf.getvalue()
    assert "hello world" in output


def test_render_agent_message_contains_agent_name() -> None:
    renderer, buf = _make_renderer()
    renderer.render_agent_message(agent="homelab", text="Checking nginx...", tokens=150)
    output = buf.getvalue()
    assert "homelab" in output
    assert "Checking nginx" in output


def test_render_system_message() -> None:
    renderer, buf = _make_renderer()
    renderer.render_system("Connected to gateway")
    output = buf.getvalue()
    assert "Connected" in output


def test_render_error_message() -> None:
    renderer, buf = _make_renderer()
    renderer.render_error("Connection failed")
    output = buf.getvalue()
    assert "Connection failed" in output


def test_render_tool_start() -> None:
    renderer, buf = _make_renderer()
    renderer.render_tool_start(tool_name="Bash", params={"command": "ls -la"}, agent="homelab")
    output = buf.getvalue()
    assert "Bash" in output


def test_render_breadcrumb() -> None:
    renderer, buf = _make_renderer()
    renderer.render_breadcrumb("work > codex > researcher")
    output = buf.getvalue()
    assert "work" in output
    assert "codex" in output


def test_agent_colors_defined() -> None:
    assert "homelab" in AGENT_COLORS
    assert "work" in AGENT_COLORS
    assert "finance" in AGENT_COLORS


def test_theme_has_defaults() -> None:
    theme = TuiTheme()
    assert theme.agent_color("homelab") == AGENT_COLORS["homelab"]
    assert theme.agent_color("unknown_agent") is not None  # fallback color
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_renderer.py -v
```

**Step 3: Write implementation**

Create `corvus/tui/theme.py`:
```python
"""TUI theme — colors, styles, agent color assignments."""
from __future__ import annotations

AGENT_COLORS: dict[str, str] = {
    "huginn": "bright_magenta",
    "work": "bright_blue",
    "homelab": "bright_green",
    "finance": "bright_yellow",
    "personal": "bright_cyan",
    "music": "bright_red",
    "docs": "bright_white",
    "inbox": "orange1",
    "email": "orange1",
    "home": "cyan",
    "general": "white",
}

_FALLBACK_COLORS = [
    "turquoise2", "deep_pink1", "spring_green1", "gold1",
    "medium_purple1", "salmon1", "sky_blue1",
]


class TuiTheme:
    """Theme configuration for the TUI."""

    def __init__(self) -> None:
        self._dynamic_assignments: dict[str, str] = {}
        self._next_fallback = 0

    def agent_color(self, agent_name: str) -> str:
        """Get the color for an agent. Assigns a fallback color for unknown agents."""
        if agent_name in AGENT_COLORS:
            return AGENT_COLORS[agent_name]
        if agent_name in self._dynamic_assignments:
            return self._dynamic_assignments[agent_name]
        color = _FALLBACK_COLORS[self._next_fallback % len(_FALLBACK_COLORS)]
        self._dynamic_assignments[agent_name] = color
        self._next_fallback += 1
        return color

    # UI chrome colors
    border: str = "dim"
    muted: str = "dim"
    error: str = "bold red"
    warning: str = "bold yellow"
    success: str = "bold green"
    system: str = "dim italic"
    user_label: str = "bold"
    status_bar: str = "reverse"
```

Create `corvus/tui/output/__init__.py`:
```python
"""TUI output — rendering, streaming, tool display."""
```

Create `corvus/tui/output/renderer.py`:
```python
"""Chat renderer — converts protocol events into Rich console output.

All terminal output goes through this class. The renderer owns a Rich Console
and formats messages, tool calls, system notifications, and errors.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from corvus.tui.theme import TuiTheme


class ChatRenderer:
    """Renders chat content to a Rich Console."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        self._console = console
        self._theme = theme

    def render_user_message(self, text: str, agent: str) -> None:
        """Render a user message."""
        label = Text("You", style="bold")
        self._console.print(label, ":", text)
        self._console.print()

    def render_agent_message(self, agent: str, text: str, tokens: int = 0) -> None:
        """Render a complete agent response with markdown."""
        color = self._theme.agent_color(agent)
        label = Text(agent, style=f"bold {color}")
        token_info = Text(f" ({tokens} tok)", style=self._theme.muted) if tokens else Text("")
        self._console.print(label, token_info, ":")
        self._console.print(Markdown(text))
        self._console.print()

    def render_stream_start(self, agent: str) -> None:
        """Render the start of a streaming response."""
        color = self._theme.agent_color(agent)
        label = Text(agent, style=f"bold {color}")
        self._console.print(label, ":", end=" ")

    def render_stream_chunk(self, chunk: str) -> None:
        """Render a streaming chunk (raw text, no markdown yet)."""
        self._console.print(chunk, end="", highlight=False)

    def render_stream_end(self, tokens: int = 0) -> None:
        """Render the end of a streaming response."""
        if tokens:
            self._console.print()
            self._console.print(Text(f"  ({tokens} tok)", style="dim"))
        self._console.print()

    def render_tool_start(self, tool_name: str, params: dict[str, Any], agent: str) -> None:
        """Render a tool call starting."""
        color = self._theme.agent_color(agent)
        param_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
        header = f"{tool_name}({param_str})"
        self._console.print(Panel(
            header,
            title=f"[{color}]tool call[/{color}]",
            border_style="dim",
            expand=False,
        ))

    def render_tool_result(self, tool_name: str, result: Any, agent: str) -> None:
        """Render a tool call result."""
        result_str = str(result) if not isinstance(result, str) else result
        if len(result_str) > 500:
            result_str = result_str[:500] + "..."
        self._console.print(Panel(
            result_str,
            title=f"[dim]{tool_name} result[/dim]",
            border_style="dim",
            expand=False,
        ))

    def render_confirm_prompt(self, confirm_id: str, tool_name: str, params: dict[str, Any], agent: str) -> None:
        """Render a confirmation prompt for a tool call."""
        color = self._theme.agent_color(agent)
        param_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
        self._console.print(Panel(
            f"{tool_name}({param_str})",
            title=f"[{color}]{agent}[/{color}] wants to run:",
            subtitle="[bold][y]es / [n]o / [a]lways[/bold]",
            border_style="yellow",
        ))

    def render_error(self, error: str) -> None:
        """Render an error message."""
        self._console.print(Text(f"Error: {error}", style=self._theme.error))

    def render_system(self, text: str) -> None:
        """Render a system notification."""
        self._console.print(Text(text, style=self._theme.system))

    def render_breadcrumb(self, breadcrumb: str) -> None:
        """Render the agent stack breadcrumb."""
        self._console.print(Text(breadcrumb, style="bold"))

    def render_status_bar(
        self,
        agent: str,
        model: str,
        tokens: int,
        workers: int = 0,
    ) -> None:
        """Render the status bar."""
        color = self._theme.agent_color(agent)
        parts = [
            f"[@{agent}]",
            f"│ {model}",
        ]
        if workers:
            parts.append(f"│ ⚡{workers} workers")
        parts.append(f"│ {tokens:,} tok")
        self._console.print(Text(" ".join(parts), style=self._theme.status_bar))
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_renderer.py -v
```

**Step 5: Commit**

```bash
git add corvus/tui/theme.py corvus/tui/output/ tests/unit/test_tui_renderer.py
git commit -m "feat(tui): add theme system and Rich chat renderer"
```

---

### Task 1.7: In-Process Gateway Protocol

**Files:**
- Create: `corvus/tui/protocol/in_process.py`
- Test: `tests/unit/test_tui_gateway_protocol.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_gateway_protocol.py`:
```python
"""Tests for in-process gateway protocol.

These tests verify the protocol adapter works with a real GatewayRuntime.
Uses a minimal runtime built from build_runtime() — no mocks.
"""
from corvus.tui.protocol.base import GatewayProtocol, SessionSummary
from corvus.tui.protocol.in_process import InProcessGateway


def test_in_process_implements_protocol() -> None:
    """InProcessGateway must implement all abstract methods."""
    assert issubclass(InProcessGateway, GatewayProtocol)


def test_in_process_instantiates() -> None:
    """Can create an InProcessGateway without a runtime (deferred connect)."""
    gateway = InProcessGateway()
    assert gateway is not None
```

Note: Full integration tests for InProcessGateway sending messages require a running GatewayRuntime with LiteLLM. Those belong in `tests/integration/`. These unit tests verify the class structure.

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_gateway_protocol.py -v
```

**Step 3: Write implementation**

Create `corvus/tui/protocol/in_process.py`:
```python
"""In-process gateway protocol adapter.

Drives the Corvus gateway directly via Python imports.
No WebSocket, no HTTP — the TUI and gateway share the same process.
Used for development and single-machine deployments.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event

logger = logging.getLogger("corvus.tui")


class InProcessGateway(GatewayProtocol):
    """Gateway protocol that drives the Corvus runtime in-process."""

    def __init__(self) -> None:
        self._runtime = None
        self._session = None
        self._event_callback: Callable[[ProtocolEvent], Awaitable[None]] | None = None
        self._connected = False

    async def connect(self) -> None:
        """Initialize the gateway runtime in-process."""
        from corvus.gateway.runtime import build_runtime

        self._runtime = build_runtime()
        self._connected = True

    async def disconnect(self) -> None:
        """Shut down the gateway runtime."""
        self._runtime = None
        self._session = None
        self._connected = False

    async def send_message(
        self,
        text: str,
        target_agent: str | None = None,
        target_agents: list[str] | None = None,
        dispatch_mode: str = "router",
        model: str | None = None,
    ) -> str:
        """Send a message through the gateway, emitting events via callback."""
        if not self._runtime:
            raise RuntimeError("Gateway not connected")

        from corvus.gateway.chat_session import ChatSession

        dispatch_id = str(uuid.uuid4())

        # Create or reuse session
        if self._session is None:
            session_id = str(uuid.uuid4())
            self._session = ChatSession(
                runtime=self._runtime,
                websocket=None,  # No WebSocket — we intercept events
                user="local",
                session_id=session_id,
            )

        # Wire event emission to our callback
        original_send = self._session.emitter._ws_send

        async def intercept_send(payload: dict) -> None:
            if self._event_callback:
                event = parse_event(payload)
                await self._event_callback(event)

        self._session.emitter._ws_send = intercept_send

        # Build the message payload matching the WebSocket protocol
        msg = {
            "type": "chat",
            "message": text,
            "dispatch_mode": dispatch_mode,
        }
        if target_agent:
            msg["target_agent"] = target_agent
        if target_agents:
            msg["target_agents"] = target_agents
        if model:
            msg["model"] = model

        # Drive the session's handle_message
        await self._session.handle_message(msg)

        return dispatch_id

    async def respond_confirm(self, confirm_id: str, approved: bool) -> None:
        """Respond to a tool confirmation prompt."""
        if self._session:
            await self._session.confirm_queue.respond(confirm_id, approved)

    async def cancel_run(self, run_id: str) -> None:
        """Cancel an active run."""
        if self._session and self._session._current_turn:
            self._session._current_turn.dispatch_interrupted.set()

    async def list_sessions(self, limit: int = 20, agent: str | None = None) -> list[SessionSummary]:
        """List sessions from the session manager."""
        if not self._runtime:
            return []
        rows = self._runtime.session_mgr.list(limit=limit, agent_filter=agent)
        return [
            SessionSummary(
                session_id=r["id"],
                agent_name=r.get("agent_name"),
                summary=r.get("summary"),
                started_at=r.get("started_at", ""),
                message_count=r.get("message_count", 0),
                agents_used=json.loads(r["agents_used"]) if isinstance(r.get("agents_used"), str) else r.get("agents_used", []),
            )
            for r in rows
        ]

    async def resume_session(self, session_id: str) -> SessionDetail:
        """Resume an existing session."""
        if not self._runtime:
            raise RuntimeError("Gateway not connected")
        session_data = self._runtime.session_mgr.get(session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")
        messages = self._runtime.session_mgr.list_messages(session_id)
        agents_used = session_data.get("agents_used", [])
        if isinstance(agents_used, str):
            agents_used = json.loads(agents_used)
        return SessionDetail(
            session_id=session_id,
            agent_name=session_data.get("agent_name"),
            summary=session_data.get("summary"),
            started_at=session_data.get("started_at", ""),
            message_count=session_data.get("message_count", 0),
            agents_used=agents_used,
            messages=messages,
        )

    async def list_agents(self) -> list[dict]:
        """List available agents."""
        if not self._runtime:
            return []
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "enabled": agent.enabled,
            }
            for agent in self._runtime.agent_registry.list_enabled()
        ]

    async def list_models(self) -> list[dict]:
        """List available models."""
        if not self._runtime:
            return []
        return [m.to_dict() for m in self._runtime.model_router.list_available_models()]

    def on_event(self, callback: Callable[[ProtocolEvent], Awaitable[None]]) -> None:
        """Register event callback."""
        self._event_callback = callback
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_gateway_protocol.py -v
```

**Step 5: Commit**

```bash
git add corvus/tui/protocol/in_process.py tests/unit/test_tui_gateway_protocol.py
git commit -m "feat(tui): add in-process gateway protocol adapter"
```

---

### Task 1.8: TUI App — Main Entry Point + Chat Loop

**Files:**
- Create: `corvus/tui/app.py`
- Create: `corvus/tui/core/event_handler.py`
- Test: `tests/unit/test_tui_app.py`

**Step 1: Write the failing test**

Create `tests/unit/test_tui_app.py`:
```python
"""Tests for TuiApp structure and initialization."""
from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.commands.registry import CommandRegistry
from corvus.tui.input.parser import InputParser


def test_app_instantiates() -> None:
    app = TuiApp()
    assert app is not None


def test_app_has_agent_stack() -> None:
    app = TuiApp()
    assert isinstance(app.agent_stack, AgentStack)


def test_app_has_command_registry() -> None:
    app = TuiApp()
    assert isinstance(app.command_registry, CommandRegistry)


def test_app_has_parser() -> None:
    app = TuiApp()
    assert isinstance(app.parser, InputParser)


def test_app_registers_builtin_commands() -> None:
    app = TuiApp()
    assert app.command_registry.lookup("help") is not None
    assert app.command_registry.lookup("quit") is not None
    assert app.command_registry.lookup("agents") is not None
    assert app.command_registry.lookup("agent") is not None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_tui_app.py -v
```

**Step 3: Write implementation**

Create `corvus/tui/core/event_handler.py`:
```python
"""Maps protocol events to renderer calls.

Sits between the GatewayProtocol (which emits events) and the ChatRenderer
(which renders to the terminal). Maintains streaming state.
"""
from __future__ import annotations

from corvus.tui.core.agent_stack import AgentStack, AgentStatus
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.events import (
    ConfirmRequest,
    DispatchComplete,
    DispatchStart,
    ErrorEvent,
    ProtocolEvent,
    RunComplete,
    RunOutputChunk,
    RunPhase,
    RunStart,
    ToolResult,
    ToolStart,
)


class EventHandler:
    """Handles protocol events and drives the renderer."""

    def __init__(self, renderer: ChatRenderer, agent_stack: AgentStack) -> None:
        self._renderer = renderer
        self._agent_stack = agent_stack
        self._streaming_agent: str | None = None
        self._pending_confirm: ConfirmRequest | None = None

    @property
    def pending_confirm(self) -> ConfirmRequest | None:
        return self._pending_confirm

    def clear_confirm(self) -> None:
        self._pending_confirm = None

    async def handle(self, event: ProtocolEvent) -> None:
        """Dispatch a protocol event to the appropriate render method."""
        if isinstance(event, RunStart):
            ctx = self._agent_stack.find(event.agent)
            if ctx:
                ctx.status = AgentStatus.THINKING
            self._renderer.render_system(f"{event.agent} is thinking...")

        elif isinstance(event, RunPhase):
            ctx = self._agent_stack.find(event.agent)
            if ctx:
                if event.phase == "executing":
                    ctx.status = AgentStatus.EXECUTING
                elif event.phase in ("done", "error"):
                    ctx.status = AgentStatus.IDLE
                ctx.status_detail = event.phase

        elif isinstance(event, RunOutputChunk):
            if not event.final:
                if self._streaming_agent != event.agent:
                    if self._streaming_agent:
                        self._renderer.render_stream_end()
                    self._streaming_agent = event.agent
                    self._renderer.render_stream_start(event.agent)
                self._renderer.render_stream_chunk(event.chunk)
            else:
                self._streaming_agent = None
                self._renderer.render_stream_end()

        elif isinstance(event, RunComplete):
            self._streaming_agent = None
            ctx = self._agent_stack.find(event.agent)
            if ctx:
                ctx.status = AgentStatus.IDLE
                ctx.token_count += event.tokens_used

        elif isinstance(event, ToolStart):
            if self._streaming_agent:
                self._renderer.render_stream_end()
                self._streaming_agent = None
            self._renderer.render_tool_start(
                tool_name=event.tool_name,
                params=event.tool_input,
                agent=event.agent,
            )

        elif isinstance(event, ToolResult):
            self._renderer.render_tool_result(
                tool_name=event.tool_name,
                result=event.result,
                agent=event.agent,
            )

        elif isinstance(event, ConfirmRequest):
            if self._streaming_agent:
                self._renderer.render_stream_end()
                self._streaming_agent = None
            self._pending_confirm = event
            self._renderer.render_confirm_prompt(
                confirm_id=event.confirm_id,
                tool_name=event.tool_name,
                params=event.tool_input,
                agent=event.agent,
            )

        elif isinstance(event, ErrorEvent):
            self._renderer.render_error(event.message)

        elif isinstance(event, DispatchComplete):
            if self._streaming_agent:
                self._renderer.render_stream_end()
                self._streaming_agent = None
```

Create `corvus/tui/app.py`:
```python
"""TuiApp — main entry point for the Corvus TUI.

Wires together all components: layout, input, output, protocol, commands.
Runs the prompt_toolkit event loop with async support.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console

from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.theme import TuiTheme

logger = logging.getLogger("corvus.tui")


class TuiApp:
    """Main TUI application."""

    def __init__(self) -> None:
        self.theme = TuiTheme()
        self.console = Console()
        self.renderer = ChatRenderer(console=self.console, theme=self.theme)
        self.agent_stack = AgentStack()
        self.command_registry = CommandRegistry()
        self.command_router = CommandRouter(registry=self.command_registry)
        self.parser = InputParser()
        self.event_handler = EventHandler(renderer=self.renderer, agent_stack=self.agent_stack)
        self.gateway: GatewayProtocol = InProcessGateway()
        self._running = False

        self._register_builtin_commands()

    def _register_builtin_commands(self) -> None:
        """Register all built-in slash commands."""
        builtins = [
            SlashCommand(name="help", description="Show all commands", tier=InputTier.SYSTEM),
            SlashCommand(name="quit", description="Exit TUI", tier=InputTier.SYSTEM),
            SlashCommand(name="agents", description="List all agents", tier=InputTier.SYSTEM),
            SlashCommand(name="agent", description="Switch to agent", tier=InputTier.SYSTEM, args_spec="<name>"),
            SlashCommand(name="models", description="List available models", tier=InputTier.SYSTEM),
            SlashCommand(name="model", description="Switch model", tier=InputTier.SYSTEM, args_spec="<name>"),
            SlashCommand(name="reload", description="Hot-reload configs", tier=InputTier.SYSTEM),
            SlashCommand(name="setup", description="Run setup wizard", tier=InputTier.SYSTEM),
            SlashCommand(name="breakglass", description="Elevate permissions", tier=InputTier.SYSTEM),
            SlashCommand(name="focus", description="Toggle focus mode", tier=InputTier.SYSTEM),
            SlashCommand(name="split", description="Toggle split mode", tier=InputTier.SYSTEM),
            SlashCommand(name="theme", description="Switch color theme", tier=InputTier.SYSTEM, args_spec="<name>"),
            SlashCommand(name="sessions", description="Browse session history", tier=InputTier.SERVICE),
            SlashCommand(name="session", description="Session management", tier=InputTier.SERVICE, args_spec="new|resume <id>"),
            SlashCommand(name="memory", description="Memory hub", tier=InputTier.SERVICE, args_spec="search|list|add"),
            SlashCommand(name="tools", description="List tools", tier=InputTier.SERVICE),
            SlashCommand(name="tool", description="Tool detail", tier=InputTier.SERVICE, args_spec="<name>"),
            SlashCommand(name="tool-history", description="Recent tool calls", tier=InputTier.SERVICE),
            SlashCommand(name="view", description="View file", tier=InputTier.SERVICE, args_spec="<path>"),
            SlashCommand(name="edit", description="Edit file in $EDITOR", tier=InputTier.SERVICE, args_spec="<path>"),
            SlashCommand(name="diff", description="Show file diff", tier=InputTier.SERVICE, args_spec="<path>"),
            SlashCommand(name="workers", description="Toggle worker panel", tier=InputTier.SERVICE),
            SlashCommand(name="tokens", description="Token usage details", tier=InputTier.SERVICE),
            SlashCommand(name="status", description="System status", tier=InputTier.SERVICE),
            SlashCommand(name="export", description="Export session to markdown", tier=InputTier.SERVICE),
            SlashCommand(name="spawn", description="Spawn subagent", tier=InputTier.AGENT, args_spec='<name> "task"'),
            SlashCommand(name="enter", description="Enter subagent context", tier=InputTier.AGENT, args_spec="<name>"),
            SlashCommand(name="back", description="Return to parent agent", tier=InputTier.AGENT),
            SlashCommand(name="top", description="Return to root agent", tier=InputTier.AGENT),
            SlashCommand(name="summon", description="Temporary coworker", tier=InputTier.AGENT, args_spec="<name>"),
            SlashCommand(name="kill", description="Kill subagent", tier=InputTier.AGENT, args_spec="<name>"),
        ]
        for cmd in builtins:
            self.command_registry.register(cmd)

    def _build_prompt(self) -> HTML:
        """Build the prompt string showing current agent context."""
        if self.agent_stack.depth == 0:
            return HTML("<b>> </b>")
        agent = self.agent_stack.current.agent_name
        color = self.theme.agent_color(agent)
        if self.agent_stack.depth > 1:
            breadcrumb = self.agent_stack.breadcrumb
            return HTML(f"<b>{breadcrumb} > </b>")
        return HTML(f"<b>@{agent} > </b>")

    async def _handle_system_command(self, parsed) -> bool:
        """Handle system-tier commands. Returns True if handled."""
        cmd = parsed.command

        if cmd == "quit":
            self._running = False
            return True

        if cmd == "help":
            self.console.print()
            self.console.print("[bold]Available commands:[/bold]")
            for c in sorted(self.command_registry.all_commands(), key=lambda x: x.name):
                args = f" {c.args_spec}" if c.args_spec else ""
                self.console.print(f"  /{c.name}{args}  — {c.description}")
            self.console.print()
            return True

        if cmd == "agents":
            agents = await self.gateway.list_agents()
            self.console.print()
            for a in agents:
                color = self.theme.agent_color(a["name"])
                self.console.print(f"  [{color}]@{a['name']}[/{color}]  {a['description']}")
            self.console.print()
            return True

        if cmd == "agent" and parsed.command_args:
            agent_name = parsed.command_args.strip()
            self.agent_stack.switch(agent_name, f"session-{agent_name}")
            self.renderer.render_system(f"Switched to @{agent_name}")
            return True

        if cmd == "models":
            models = await self.gateway.list_models()
            self.console.print()
            for m in models:
                self.console.print(f"  {m.get('id', m.get('label', '?'))}  {m.get('description', '')}")
            self.console.print()
            return True

        # Unhandled system command
        self.renderer.render_system(f"Command /{cmd} not yet implemented")
        return True

    async def _handle_agent_input(self, parsed) -> None:
        """Handle agent-tier input (chat, mentions, tool calls, agent commands)."""
        if self.agent_stack.depth == 0:
            self.renderer.render_error("No agent selected. Use /agent <name> or /agents to list.")
            return

        cmd = parsed.command

        # Agent navigation commands
        if parsed.kind == "command":
            if cmd == "back":
                try:
                    popped = self.agent_stack.pop()
                    self.renderer.render_system(f"Left @{popped.agent_name}, now at @{self.agent_stack.current.agent_name}")
                except IndexError:
                    self.renderer.render_error("Already at root agent")
                return
            if cmd == "top":
                root = self.agent_stack.pop_to_root()
                self.renderer.render_system(f"Returned to root @{root.agent_name}")
                return
            if cmd == "enter" and parsed.command_args:
                name = parsed.command_args.strip()
                try:
                    entered = self.agent_stack.enter(name)
                    self.renderer.render_system(f"Entered @{entered.agent_name}")
                except KeyError as e:
                    self.renderer.render_error(str(e))
                return
            if cmd == "kill" and parsed.command_args:
                name = parsed.command_args.strip()
                try:
                    killed = self.agent_stack.kill(name)
                    self.renderer.render_system(f"Killed @{killed.agent_name}")
                except KeyError as e:
                    self.renderer.render_error(str(e))
                return

        # Determine target agent and dispatch mode
        target_agent = None
        target_agents = None
        dispatch_mode = "direct"
        text = parsed.text

        if parsed.kind == "mention":
            if parsed.mentions == ["all"]:
                dispatch_mode = "parallel"
            elif len(parsed.mentions) == 1:
                target_agent = parsed.mentions[0]
            else:
                target_agents = parsed.mentions
                dispatch_mode = "parallel"
        else:
            target_agent = self.agent_stack.current.agent_name

        # Render user message
        self.renderer.render_user_message(text, agent=target_agent or "all")

        # Send to gateway
        await self.gateway.send_message(
            text=text,
            target_agent=target_agent,
            target_agents=target_agents,
            dispatch_mode=dispatch_mode,
        )

    async def run(self) -> None:
        """Run the main TUI event loop."""
        self.console.print()
        self.console.print("[bold]Corvus TUI[/bold]")
        self.console.print("[dim]Type /help for commands, /quit to exit[/dim]")
        self.console.print()

        # Connect to gateway
        self.renderer.render_system("Connecting to gateway...")
        try:
            await self.gateway.connect()
        except Exception as e:
            self.renderer.render_error(f"Failed to connect: {e}")
            return

        # Wire event handler
        self.gateway.on_event(self.event_handler.handle)

        # Load agents and update parser
        agents = await self.gateway.list_agents()
        agent_names = [a["name"] for a in agents]
        self.parser.update_agents(agent_names)

        # Show available agents
        self.console.print("[bold]Available agents:[/bold]")
        for a in agents:
            color = self.theme.agent_color(a["name"])
            self.console.print(f"  [{color}]@{a['name']}[/{color}]  {a['description']}")
        self.console.print()
        self.console.print("[dim]Use /agent <name> to start, or @agent <message> to chat directly[/dim]")
        self.console.print()

        # Main loop
        session: PromptSession = PromptSession(history=InMemoryHistory())
        self._running = True

        with patch_stdout():
            while self._running:
                try:
                    raw = await session.prompt_async(self._build_prompt)
                    if not raw.strip():
                        continue

                    parsed = self.parser.parse(raw)
                    tier = self.command_router.classify(parsed)

                    if tier == InputTier.SYSTEM:
                        await self._handle_system_command(parsed)
                    elif tier == InputTier.SERVICE:
                        self.renderer.render_system(f"/{parsed.command} not yet implemented")
                    else:
                        await self._handle_agent_input(parsed)

                except KeyboardInterrupt:
                    # Ctrl+C cancels current run or is ignored at prompt
                    continue
                except EOFError:
                    # Ctrl+D exits
                    break

        # Cleanup
        await self.gateway.disconnect()
        self.console.print("[dim]Goodbye.[/dim]")


def main() -> None:
    """CLI entry point."""
    app = TuiApp()
    asyncio.run(app.run())
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_tui_app.py -v
```

**Step 5: Commit**

```bash
git add corvus/tui/app.py corvus/tui/core/event_handler.py tests/unit/test_tui_app.py
git commit -m "feat(tui): add TuiApp main entry point with chat loop and event handling"
```

---

### Task 1.9: Integration Smoke Test

**Files:**
- Test: `tests/unit/test_tui_smoke.py`

**Step 1: Write a smoke test that wires everything together**

Create `tests/unit/test_tui_smoke.py`:
```python
"""Smoke test — verifies all TUI components wire together without errors."""
from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.input.parser import InputParser
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.events import parse_event, RunOutputChunk
from corvus.tui.protocol.base import GatewayProtocol
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.theme import TuiTheme


def test_full_wiring() -> None:
    """All TUI modules import and instantiate without error."""
    app = TuiApp()

    # Parser works
    parsed = app.parser.parse("/help")
    assert parsed.kind == "command"
    assert parsed.command == "help"

    # Router classifies correctly
    tier = app.command_router.classify(parsed)
    assert tier == InputTier.SYSTEM

    # Agent stack works
    app.agent_stack.push("work", "s1")
    assert app.agent_stack.current.agent_name == "work"

    # Event parsing works
    event = parse_event({
        "type": "run_output_chunk",
        "run_id": "r1",
        "agent": "work",
        "chunk": "hello",
        "chunk_index": 0,
        "final": False,
    })
    assert isinstance(event, RunOutputChunk)
    assert event.chunk == "hello"


def test_parser_with_agents_from_registry() -> None:
    """Parser updates known agents and validates mentions."""
    app = TuiApp()
    app.parser.update_agents(["homelab", "finance", "work"])

    # Valid mention
    parsed = app.parser.parse("@homelab check nginx")
    assert parsed.kind == "mention"

    # Invalid mention falls through to chat
    parsed = app.parser.parse("@nonexistent hello")
    assert parsed.kind == "chat"
```

**Step 2: Run test**

```bash
uv run pytest tests/unit/test_tui_smoke.py -v
```
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_tui_smoke.py
git commit -m "test(tui): add integration smoke test for full TUI wiring"
```

---

## Phase 2: Multi-Agent & Sessions

Phase 2 delivers: @mentions dispatching, session create/resume/list, token counter, agent status in prompt.

---

### Task 2.1: Session Manager TUI Integration

**Files:**
- Create: `corvus/tui/core/session.py`
- Test: `tests/unit/test_tui_session.py`

Wraps `GatewayProtocol.list_sessions()` / `resume_session()` and manages the local agent stack state on resume. Implementation depends on the protocol base from Task 1.2 and agent stack from Task 1.4. Write tests that verify session create/resume updates the agent stack correctly. Use a stub gateway (a real class implementing `GatewayProtocol`, NOT a mock) that returns canned data.

---

### Task 2.2: Token Counter

**Files:**
- Create: `corvus/tui/output/token_counter.py`
- Test: `tests/unit/test_tui_token_counter.py`

Tracks per-agent and session-total token counts. Updated by `EventHandler` when `RunComplete` events arrive. Used by the status bar renderer. Write tests that verify counts accumulate correctly across multiple runs and agents.

---

### Task 2.3: Completions

**Files:**
- Create: `corvus/tui/input/completer.py`
- Test: `tests/unit/test_tui_completer.py`

A prompt_toolkit `Completer` subclass that triggers on `@` (agents), `/` (commands), `!` (tools). Uses `CommandRegistry.completions()` for slash commands. Uses agent list for @-mentions. Write tests using prompt_toolkit's `CompleteEvent` testing utilities.

---

### Task 2.4: @mention Dispatch + Multi-Agent Chat

Wire the `InputParser`'s mention detection to `GatewayProtocol.send_message()` with correct `target_agent`/`target_agents`/`dispatch_mode`. Add `@all` expansion to parallel mode. Write integration test with stub gateway verifying correct dispatch parameters.

---

### Task 2.5: Status Bar

Render persistent status bar at top of terminal showing: current agent (with color), model, worker count, total tokens. Use prompt_toolkit's `FormattedTextToolbar` in the layout. Write tests verifying status bar content updates when agent stack changes.

---

## Phase 3: Tools & Service Commands

Phase 3 delivers: tool call display, confirm/deny, `/memory`, `/tools`, `/view`, `/edit`, `/diff`, `!tool` direct invocation.

---

### Task 3.1: Tool Call View + Confirm/Deny Flow

Wire `EventHandler.handle(ConfirmRequest)` to prompt the user with `[y/n/a]` and call `gateway.respond_confirm()`. Add "always allow" tracking per tool name per session.

---

### Task 3.2: /memory Commands

Implement `/memory search "query"`, `/memory list`, `/memory add "fact"`. For in-process gateway, call `MemoryHub` directly. Render results as Rich tables.

---

### Task 3.3: /tools + !tool Direct Invocation

Implement `/tools` (list for current agent), `/tool <name>` (detail), `!tool.name args` (direct invoke). Parse tool args from input, call through gateway.

---

### Task 3.4: /view, /edit, /diff

`/view <path>` — render file with Rich `Syntax`. `/edit <path>` — open in `$EDITOR` via `subprocess`, return to TUI. `/diff <path>` — show git diff with Rich.

---

## Phase 4: System Screens

Phase 4 delivers: setup wizard, agent create/edit, session browser, memory browser.

---

### Task 4.1: Setup Screen

Replace current setup wizard (`corvus/cli/setup.py` flows) with Rich-rendered prompt_toolkit forms. Credential dashboard renders as Rich table.

---

### Task 4.2: Agent Management

`/agent new` — guided wizard: name, description, model, tools, memory config. Writes `config/agents/<name>/agent.yaml`. `/agent edit <name>` — opens in `$EDITOR`. `/reload` — hot-reloads agent registry.

---

### Task 4.3: Session Browser

`/sessions` — Rich table of recent sessions. `/sessions search "query"` — FTS5 search. `/session resume <id>` — restore conversation with agent stack replay. Arrow-key navigation through session list.

---

## Phase 5: Polish & Production

Phase 5 delivers: WebSocket gateway, split mode, themes, breakglass, export, domain commands.

---

### Task 5.1: WebSocket Gateway Protocol

Implement `corvus/tui/protocol/websocket.py`. Connects to `ws://localhost:8000/ws`. Same `GatewayProtocol` interface as in-process. Add `--mode inprocess|websocket` CLI flag.

---

### Task 5.2: Split Mode

`/split` toggles side-by-side agent panes. Use prompt_toolkit's `HSplit`/`VSplit` layout containers. Route messages to the left or right pane based on agent.

---

### Task 5.3: Theme System

`/theme <name>` switches between `default`, `light`, `minimal`. Persist selection to `~/.config/corvus/tui.yaml`.

---

### Task 5.4: Break-Glass Mode

`/breakglass` — elevates permissions for current session. Calls `GatewayRuntime.break_glass.create_session()`. Visual indicator in status bar (red border).

---

### Task 5.5: Domain Slash Commands

Load per-agent slash commands from `agent.yaml` `metadata.tui_commands` section. Register dynamically when agent is switched. Unregister when switching away.

---

### Task 5.6: Export + Polish

`/export` — dump current session to markdown file. Add `--session` CLI flag to resume directly. Man page / `--help` for all CLI flags. Final pass on visual consistency.

---

## Test Output

All test runs MUST output to log files per CLAUDE.md policy:

```bash
uv run pytest tests/unit/test_tui_*.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_tui_results.log
```

## Dependencies Summary

**Add:** `rich >=13.0` (via `uv add rich`)
**Already present:** `prompt-toolkit`, `textual` (can remove textual later if unused elsewhere)
**No new dependencies beyond rich**
