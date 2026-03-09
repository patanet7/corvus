"""StatusBar — bottom toolbar content for the prompt_toolkit prompt."""

import time

from prompt_toolkit.formatted_text import HTML

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.theme import TuiTheme


class StatusBar:
    """Generates the bottom toolbar content for the prompt.

    Shows: current agent | model | worker count | token usage

    Usage with PromptSession:
        status_bar = StatusBar(agent_stack, token_counter, theme)
        raw = await session.prompt_async(prompt, bottom_toolbar=status_bar)
    """

    def __init__(
        self,
        agent_stack: AgentStack,
        token_counter: TokenCounter,
        theme: TuiTheme,
    ) -> None:
        self._agent_stack = agent_stack
        self._token_counter = token_counter
        self._theme = theme
        self._model: str = "default"
        self._tier: str | None = None
        self._breakglass_expiry: float | None = None

    @property
    def model(self) -> str:
        """Return the current model name."""
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        """Set the current model name."""
        self._model = value

    @property
    def tier(self) -> str | None:
        """Return the current permission tier, or None if not set."""
        return self._tier

    @tier.setter
    def tier(self, value: str | None) -> None:
        """Set the current permission tier."""
        self._tier = value

    def set_breakglass_expiry(self, expiry: float | None) -> None:
        """Store the break-glass expiry timestamp (epoch seconds).

        When set and the tier is BREAK-GLASS, the toolbar will show
        remaining minutes.
        """
        self._breakglass_expiry = expiry

    def __call__(self) -> HTML:
        """Called by prompt_toolkit to render the toolbar."""
        parts: list[str] = []

        # Current agent
        if self._agent_stack.depth > 0:
            agent = self._agent_stack.current.agent_name
            parts.append(f"@{agent}")
        else:
            parts.append("corvus")

        # Model
        parts.append(self._model)

        # Worker count
        if self._agent_stack.depth > 0:
            workers = len(self._agent_stack.current.children)
            if workers:
                parts.append(f"workers: {workers}" if workers != 1 else "workers: 1")

        # Permission tier (with break-glass countdown)
        if self._tier is not None:
            if self._tier == "BREAK-GLASS" and self._breakglass_expiry is not None:
                remaining = max(0, self._breakglass_expiry - time.time())
                mins = int(remaining // 60)
                parts.append(f"BREAK-GLASS [{mins}m remaining]")
            else:
                parts.append(self._tier)

        # Token count
        parts.append(self._token_counter.format_display())

        bar_text = " | ".join(parts)
        return HTML(f"<b> {bar_text} </b>")
