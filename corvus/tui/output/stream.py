"""Stream handler for live-updating agent output in the Corvus TUI.

Owns the Rich Live display, stream buffer, and thinking spinner so that
the ChatRenderer can delegate all streaming concerns to this class.
"""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from corvus.tui.theme import TuiTheme


class StreamHandler:
    """Manages live-streaming output and thinking spinners for agent responses.

    Encapsulates the Rich Live display lifecycle, the text buffer that
    accumulates streamed chunks, and the transient thinking spinner shown
    while an agent is processing.

    Args:
        console: The Rich Console instance used for all output.
        theme: The TuiTheme providing color and style configuration.
    """

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        self._console = console
        self._theme = theme
        self._live: Live | None = None
        self._stream_buffer: list[str] = []
        self._stream_agent: str = ""
        self._thinking_live: Live | None = None

    # -- Thinking spinner --

    def render_thinking_start(self, agent: str) -> None:
        """Show a spinner while the agent is thinking.

        Stops any previously active thinking spinner before starting a new one.

        Args:
            agent: The name of the agent that is thinking.
        """
        self.stop_thinking()
        color = self._theme.agent_color(agent)
        spinner = Spinner("dots", text=Text(f" @{agent} thinking\u2026", style=f"bold {color}"))
        self._thinking_live = Live(spinner, console=self._console, transient=True)
        self._thinking_live.start()

    def stop_thinking(self) -> None:
        """Stop the thinking spinner if active."""
        if self._thinking_live is not None:
            self._thinking_live.stop()
            self._thinking_live = None

    # -- Streaming --

    def _build_stream_panel(self, agent: str, color: str, content: str) -> Panel:
        """Build a panel for the current streaming state.

        Args:
            agent: The agent name for the panel title.
            color: The Rich color string for the agent.
            content: The accumulated streamed text so far.

        Returns:
            A Rich Panel displaying the current stream content.
        """
        return Panel(
            Markdown(content) if content else Text("\u2026"),
            title=f"[bold {color}]@{agent}[/]",
            border_style=color,
            expand=False,
        )

    def render_stream_start(self, agent: str) -> None:
        """Start a Live streaming panel for agent output.

        Stops the thinking spinner and initializes a new Live display with
        an empty panel that will be updated as chunks arrive.

        Args:
            agent: The agent whose output is being streamed.
        """
        self.stop_thinking()
        color = self._theme.agent_color(agent)
        self._stream_agent = agent
        self._stream_buffer = []
        self._live = Live(
            self._build_stream_panel(agent, color, ""),
            console=self._console,
            refresh_per_second=8,
            transient=True,
            vertical_overflow="visible",
        )
        self._live.start()

    def render_stream_chunk(self, chunk: str) -> None:
        """Append a chunk to the streaming buffer and update the Live display.

        Args:
            chunk: The text chunk to append to the stream.
        """
        self._stream_buffer.append(chunk)
        if self._live is not None:
            color = self._theme.agent_color(self._stream_agent)
            content = "".join(self._stream_buffer)
            self._live.update(self._build_stream_panel(self._stream_agent, color, content))

    def render_stream_end(self, tokens: int = 0) -> None:
        """Finish a streamed response and render the final panel.

        Stops the Live display, joins the buffer into final content, and
        prints the complete agent response with optional token count.

        Args:
            tokens: Optional token count to display after the response.
        """
        if self._live is not None:
            self._live.stop()
            self._live = None

        content = "".join(self._stream_buffer).strip()
        agent = self._stream_agent

        # Reset state
        self._stream_buffer = []
        self._stream_agent = ""

        if not content:
            return

        color = self._theme.agent_color(agent)
        header = Text(f"@{agent}: ", style=f"bold {color}")
        self._console.print(header)
        self._console.print(Markdown(content))
        if tokens:
            self._console.print(
                Text(f"  [{tokens:,} tokens]", style=self._theme.muted)
            )
