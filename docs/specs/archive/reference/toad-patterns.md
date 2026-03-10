---
title: "Toad Design Reference Patterns"
type: spec
status: implemented
date: 2026-03-08
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Toad — Design Reference Patterns

Source: https://github.com/toolhouse-community/toad (MIT License)

## Agent Switching Modal

Toad uses a modal dialog for selecting/switching agents:

```python
# toad/screens/agent_selector.py (simplified)
class AgentSelectorModal:
    """Modal for switching between agents."""

    def compose(self):
        """
        ┌─ Select Agent ──────────┐
        │                         │
        │  > work      [active]   │
        │    homelab              │
        │    finance              │
        │    personal             │
        │    docs                 │
        │                         │
        │  ↑↓ Navigate  Enter Ok  │
        └─────────────────────────┘
        """
        for agent in self.agents:
            yield AgentOption(
                name=agent.name,
                active=agent == self.current,
            )

    def on_select(self, agent_name: str):
        self.dismiss(agent_name)
```

## Mode-Based Session Management

Toad separates "modes" — each mode has its own session context:

```python
# toad/session.py (simplified)
class SessionMode(Enum):
    CHAT = "chat"        # Normal conversation
    EDIT = "edit"         # File editing mode
    REVIEW = "review"     # Code review mode
    EXPLORE = "explore"   # Codebase exploration

class SessionManager:
    """Mode-aware session management."""

    def __init__(self):
        self._sessions: dict[SessionMode, Session] = {}
        self._current_mode: SessionMode = SessionMode.CHAT

    def switch_mode(self, mode: SessionMode):
        """Switch to a different session mode."""
        self._current_mode = mode
        if mode not in self._sessions:
            self._sessions[mode] = Session(mode=mode)

    @property
    def current_session(self) -> Session:
        return self._sessions[self._current_mode]
```

## Split/Unified Diff Viewer

Toad implements a diff viewer using `difflib.SequenceMatcher`:

```python
# toad/components/diff_view.py (simplified)
import difflib

class DiffView:
    """Render file diffs with syntax highlighting."""

    def render_unified(self, old: str, new: str, filename: str) -> str:
        """Unified diff format."""
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
        return "".join(diff)

    def render_side_by_side(self, old: str, new: str) -> Table:
        """Side-by-side diff as Rich Table."""
        matcher = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines())
        table = Table(show_header=True)
        table.add_column("Old", style="red")
        table.add_column("New", style="green")

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            old_lines = old.splitlines()[i1:i2]
            new_lines = new.splitlines()[j1:j2]
            # Pad shorter side
            max_len = max(len(old_lines), len(new_lines))
            old_lines.extend([""] * (max_len - len(old_lines)))
            new_lines.extend([""] * (max_len - len(new_lines)))
            for o, n in zip(old_lines, new_lines):
                style = "dim" if tag == "equal" else ""
                table.add_row(
                    f"[red]{o}" if tag in ("delete", "replace") else o,
                    f"[green]{n}" if tag in ("insert", "replace") else n,
                )
        return table
```

## Dock-Left Sidebar

Toad's sidebar pattern with fixed width:

```python
# toad/layout.py (simplified)
class AppLayout:
    """Sidebar + main content layout."""

    SIDEBAR_WIDTH = 40          # characters
    SIDEBAR_MAX_RATIO = 0.45    # never more than 45% of terminal

    def compose(self):
        width = min(self.SIDEBAR_WIDTH, int(self.terminal_width * self.SIDEBAR_MAX_RATIO))
        yield Sidebar(width=width)
        yield MainContent()
```

## Sidebar with Tree + Collapsible Sections

```python
# toad/components/sidebar.py (simplified)
class Sidebar:
    """Left sidebar with collapsible sections."""

    def compose(self):
        """
        ┌─ Sidebar ──────────┐
        │ ▼ Agents           │
        │   work [active]    │
        │   homelab          │
        │   finance          │
        │                    │
        │ ▶ Sessions (5)     │
        │                    │
        │ ▼ Workers (2)      │
        │   codex [running]  │
        │   researcher [done]│
        │                    │
        │ ▶ Memory           │
        └────────────────────┘
        """
        yield CollapsibleSection(
            "Agents",
            AgentTree(self.agents),
            expanded=True,
        )
        yield CollapsibleSection(
            "Sessions",
            SessionList(self.sessions),
            expanded=False,
        )
        yield CollapsibleSection(
            "Workers",
            WorkerList(self.workers),
            expanded=True,
        )
        yield CollapsibleSection(
            "Memory",
            MemoryList(self.memories),
            expanded=False,
        )

class CollapsibleSection:
    """A section with toggle header."""

    def __init__(self, title: str, content, expanded: bool = True):
        self.title = title
        self.content = content
        self.expanded = expanded

    def toggle(self):
        self.expanded = not self.expanded

    def render(self):
        icon = "▼" if self.expanded else "▶"
        header = f"{icon} {self.title}"
        if self.expanded:
            return Panel(Group(header, self.content), border_style="dim")
        return Text(header, style="dim")
```

## Key Takeaway for Corvus TUI

- **Agent modal**: Quick-select modal for agent switching
- **Mode-based sessions**: Different contexts for different activities
- **Diff viewer**: `difflib.SequenceMatcher` for side-by-side diffs (use for /diff command)
- **Fixed-width sidebar**: 40 chars, max 45% — adapts to terminal size
- **Collapsible sections**: ▼/▶ headers for sidebar sections (agents, sessions, workers, memory)
- **This is our primary reference for the tree view / collapsible sidebar pattern**
