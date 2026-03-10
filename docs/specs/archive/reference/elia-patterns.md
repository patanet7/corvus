---
title: "Elia Design Reference Patterns"
type: spec
status: implemented
date: 2026-03-08
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Elia — Design Reference Patterns

Source: https://github.com/darrenburns/elia (MIT License)

## Theme System (Pydantic + YAML)

Elia uses a Pydantic-based theme model with 9 builtin themes, loaded from YAML:

```python
# elia/config/theme.py (simplified)
from pydantic import BaseModel

class EliaChatTheme(BaseModel):
    name: str = "default"
    # Syntax highlighting
    syntax_theme: str = "monokai"
    # Chat colors
    user_color: str = "#e1e1e1"
    assistant_color: str = "#46B1C9"
    # UI chrome
    border_color: str = "#444444"
    background: str = "#1e1e2e"
    foreground: str = "#cdd6f4"
    accent: str = "#cba6f7"
    muted: str = "#6c7086"
    error: str = "#f38ba8"
    warning: str = "#fab387"
    success: str = "#a6e3a1"

# Builtin themes: monokai, catppuccin-mocha, catppuccin-latte,
#   dracula, galaxy, gruvbox, nord, solarized-dark, tokyo-night
```

## Chatbox Widget — Streaming Chunks

Elia's core chat display uses a widget with `append_chunk()` for streaming:

```python
# elia/widgets/chatbox.py (simplified)
class Chatbox:
    """Streaming chat display widget."""

    def __init__(self):
        self._buffer: list[str] = []
        self._current_agent: str | None = None

    def append_chunk(self, chunk: str) -> None:
        """Append a streaming token. Re-renders the last message."""
        self._buffer.append(chunk)
        self._refresh_last_message()

    def _refresh_last_message(self) -> None:
        """Re-render the accumulated buffer as markdown."""
        full_text = "".join(self._buffer)
        # Rich Markdown rendering of accumulated text
        ...

    def complete_message(self) -> None:
        """Finalize current message, clear buffer."""
        self._buffer.clear()
        self._current_agent = None
```

## SelectionTextArea — Vim Bindings

```python
# Custom text input with vim-style bindings
class SelectionTextArea:
    """Multi-line input with vim normal/insert mode."""

    BINDINGS = {
        "escape": "enter_normal_mode",
        "i": "enter_insert_mode",
        "v": "visual_select",
        "y": "yank",
        "p": "paste",
        "dd": "delete_line",
        "/": "search",
    }
```

## SQLAlchemy Async DB Layer

```python
# elia/database/converters.py (simplified)
class ChatDAO:
    """Data access for chat sessions."""

    async def list_chats(self, limit: int = 50) -> list[ChatSummary]:
        async with self.session() as s:
            result = await s.execute(
                select(ChatModel)
                .order_by(ChatModel.updated_at.desc())
                .limit(limit)
            )
            return [self._to_summary(row) for row in result.scalars()]

    async def get_chat(self, chat_id: str) -> ChatDetail:
        async with self.session() as s:
            chat = await s.get(ChatModel, chat_id)
            messages = await s.execute(
                select(MessageModel)
                .where(MessageModel.chat_id == chat_id)
                .order_by(MessageModel.created_at)
            )
            return ChatDetail(
                chat=self._to_summary(chat),
                messages=[self._to_message(m) for m in messages.scalars()],
            )
```

## Key Takeaway for Corvus TUI

- **Theme model**: Use Pydantic dataclass for theme, support YAML overrides
- **Streaming**: Buffer chunks, re-render accumulated markdown on each chunk
- **DB pattern**: DAO + converter pattern for session persistence
- **Vim bindings**: vi_mode in prompt_toolkit covers this natively
