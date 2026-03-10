---
title: "Posting Design Reference Patterns"
type: spec
status: implemented
date: 2026-03-08
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Posting — Design Reference Patterns

Source: https://github.com/darrenburns/posting (Apache-2.0 License)

## SCSS Theme System

Posting has the most sophisticated theme system of any Python TUI — 12 built-in themes with full SCSS:

```scss
/* posting/themes/galaxy.scss (simplified) */
$primary: #7aa2f7;
$secondary: #bb9af7;
$background: #1a1b26;
$surface: #24283b;
$foreground: #c0caf5;
$accent: #ff9e64;
$error: #f7768e;
$warning: #e0af68;
$success: #9ece6a;
$muted: #565f89;

/* Component-specific tokens */
$url-bar-background: $surface;
$method-selector-color: $primary;
$response-status-success: $success;
$response-status-error: $error;
$tab-active-background: $primary;
$tab-active-foreground: $background;
```

Themes: galaxy, catppuccin-mocha, catppuccin-latte, dracula, gruvbox-dark,
        monokai, nord, solarized-dark, solarized-light, tokyo-night,
        flexoki-dark, flexoki-light

## Jump-Mode Navigation

Posting implements "jump mode" — press a key to overlay labels on all interactive elements:

```python
# posting/jump_mode.py (simplified)
class JumpMode:
    """Overlay key labels on interactive elements for quick navigation."""

    def activate(self):
        """Show jump labels on all focusable widgets."""
        targets = self._collect_focusable()
        for i, target in enumerate(targets):
            label = self._index_to_key(i)  # a, b, c, ..., aa, ab, ...
            target.overlay_label(label)

    def handle_key(self, key: str):
        """Navigate to the target matching the typed key(s)."""
        target = self._find_target(key)
        if target:
            target.focus()
            self.deactivate()
```

## Compact Mode

Toggleable compact mode that reduces padding/chrome:

```python
# posting/app.py (simplified)
class PostingApp:
    compact_mode: reactive[bool] = reactive(False)

    def toggle_compact(self):
        self.compact_mode = not self.compact_mode
        # All widgets react to compact_mode change
        # Reduces padding, hides labels, shrinks borders
```

## Command Palette

Full command palette with fuzzy matching:

```python
# posting/commands.py (simplified)
class CommandPalette:
    """Fuzzy-match command palette like VS Code."""

    def __init__(self, commands: list[Command]):
        self.commands = commands

    def search(self, query: str) -> list[Command]:
        """Fuzzy match against command names and descriptions."""
        return sorted(
            [c for c in self.commands if self._fuzzy_match(query, c.name)],
            key=lambda c: self._score(query, c.name),
            reverse=True,
        )
```

## Focus-Within Border Highlighting

```python
# posting/widgets/request.py (simplified)
# When a container has focus within, its border changes color
class RequestPanel:
    def on_focus(self):
        self.border_style = "accent"

    def on_blur(self):
        self.border_style = "muted"
```

## Key Takeaway for Corvus TUI

- **Theme tokens**: Define component-specific tokens (not just base colors)
- **Jump mode**: Great for keyboard-first navigation in panel-heavy layouts
- **Compact mode**: Useful for smaller terminals — toggle chrome
- **Command palette**: Fuzzy-match command launcher complements slash commands
- **Focus borders**: Visual indicator of which panel has focus
