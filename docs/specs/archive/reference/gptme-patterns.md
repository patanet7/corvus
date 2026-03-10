---
title: "gptme Design Reference Patterns"
type: spec
status: implemented
date: 2026-03-08
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# gptme — Design Reference Patterns

Source: https://github.com/ErikBjare/gptme (MIT License)

## prompt_toolkit Integration

gptme uses prompt_toolkit PromptSession with FileHistory and custom completions:

```python
# gptme/chat.py (simplified)
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

def get_prompt_session() -> PromptSession:
    return PromptSession(
        history=FileHistory(str(get_history_file())),
        auto_suggest=AutoSuggestFromHistory(),
        completer=GptmeCompleter(),
        multiline=False,
        vi_mode=False,  # configurable
    )
```

## Custom Completer

```python
# gptme/tabcomplete.py (simplified)
from prompt_toolkit.completion import Completer, Completion

class GptmeCompleter(Completer):
    """Completes slash commands and file paths."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()

        if text.startswith("/"):
            # Slash command completion
            cmd = words[0] if words else "/"
            for name, desc in COMMANDS.items():
                if name.startswith(cmd):
                    yield Completion(
                        name,
                        start_position=-len(cmd),
                        display_meta=desc,
                    )
        elif any(c in text for c in "/\\~."):
            # File path completion
            for path in _complete_path(text):
                yield Completion(path, start_position=-len(words[-1]))
```

## PathLexer — Syntax-Aware Input

```python
# gptme/chat.py (simplified)
from prompt_toolkit.lexers import PygmentsLexer

class PathLexer:
    """Highlights file paths in input."""

    def lex_document(self, document):
        # Returns styled tokens for paths, commands, etc.
        ...
```

## Rich-to-prompt_toolkit Bridge

This is the key pattern — bridging Rich output into prompt_toolkit's display:

```python
# gptme/util/rich.py
from io import StringIO
from rich.console import Console

def rich_to_str(renderable) -> str:
    """Render a Rich object to a plain string for prompt_toolkit."""
    console = Console(file=StringIO(), force_terminal=True, width=120)
    console.print(renderable)
    return console.file.getvalue()
```

## Streaming Generator Pattern

```python
# gptme/llm.py (simplified)
async def stream_response(messages: list[dict]) -> AsyncIterator[str]:
    """Yields response tokens one at a time."""
    async for chunk in client.chat.completions.create(
        messages=messages,
        stream=True,
    ):
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

## Tool Formatting

```python
# gptme/tools/base.py (simplified)
def format_tool_result(tool_name: str, result: str, success: bool) -> str:
    """Format tool output for display."""
    status = "✓" if success else "✗"
    return f"[{status}] {tool_name}\n{result}"
```

## Key Takeaway for Corvus TUI

- **PromptSession**: FileHistory + AutoSuggestFromHistory is the standard pattern
- **Completer**: Yield Completion objects with start_position for proper replacement
- **Rich bridge**: `rich_to_str()` for converting Rich renderables to prompt_toolkit strings
- **Streaming**: AsyncIterator pattern for token-by-token output
- **Multi-line**: Toggle with config, use alt+enter for newline
