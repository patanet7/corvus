"""Event handler for the Corvus TUI.

Maps incoming ProtocolEvent objects to renderer calls and agent stack
state transitions. Tracks streaming state and pending confirmations.
"""

from corvus.tui.core.agent_stack import AgentStack, AgentStatus
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.events import (
    ConfirmRequest,
    DispatchComplete,
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
    """Processes gateway protocol events, updating UI and agent state.

    Responsibilities:
    - Translate lifecycle events into renderer calls
    - Track which agent is currently streaming
    - Store pending confirmation requests for the input loop
    - Accumulate token counts on agent contexts
    """

    def __init__(
        self,
        renderer: ChatRenderer,
        agent_stack: AgentStack,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._renderer = renderer
        self._agent_stack = agent_stack
        self._token_counter = token_counter
        self._pending_confirm: ConfirmRequest | None = None
        self._streaming_agent: str | None = None

    @property
    def pending_confirm(self) -> ConfirmRequest | None:
        """Return the current pending confirmation request, if any."""
        return self._pending_confirm

    def clear_confirm(self) -> None:
        """Clear the pending confirmation request."""
        self._pending_confirm = None

    def _end_stream(self) -> None:
        """End any active stream and reset streaming state."""
        if self._streaming_agent is not None:
            self._renderer.render_stream_end()
            self._streaming_agent = None

    async def handle(self, event: ProtocolEvent) -> None:
        """Dispatch a protocol event to the appropriate handler method."""
        if isinstance(event, RunStart):
            self._handle_run_start(event)
        elif isinstance(event, RunPhase):
            self._handle_run_phase(event)
        elif isinstance(event, RunOutputChunk):
            self._handle_output_chunk(event)
        elif isinstance(event, RunComplete):
            self._handle_run_complete(event)
        elif isinstance(event, ToolStart):
            self._handle_tool_start(event)
        elif isinstance(event, ToolResult):
            self._handle_tool_result(event)
        elif isinstance(event, ConfirmRequest):
            self._handle_confirm_request(event)
        elif isinstance(event, ErrorEvent):
            self._handle_error(event)
        elif isinstance(event, DispatchComplete):
            self._handle_dispatch_complete(event)

    def _handle_run_start(self, event: RunStart) -> None:
        """Set agent to THINKING and render a system message."""
        ctx = self._agent_stack.find(event.agent)
        if ctx is not None:
            ctx.status = AgentStatus.THINKING
        self._renderer.render_system(f"{event.agent} is thinking...")

    def _handle_run_phase(self, event: RunPhase) -> None:
        """Update agent status based on phase string."""
        ctx = self._agent_stack.find(event.agent)
        if ctx is not None:
            phase_map = {
                "thinking": AgentStatus.THINKING,
                "executing": AgentStatus.EXECUTING,
                "waiting": AgentStatus.WAITING,
            }
            ctx.status = phase_map.get(event.phase, AgentStatus.THINKING)
            ctx.status_detail = event.summary

    def _handle_output_chunk(self, event: RunOutputChunk) -> None:
        """Stream output chunks, starting a new stream header if needed."""
        if self._streaming_agent != event.agent:
            self._end_stream()
            self._streaming_agent = event.agent
            self._renderer.render_stream_start(event.agent)
        self._renderer.render_stream_chunk(event.content)

    def _handle_run_complete(self, event: RunComplete) -> None:
        """End stream, set agent IDLE, accumulate tokens."""
        self._end_stream()
        ctx = self._agent_stack.find(event.agent)
        if ctx is not None:
            ctx.status = AgentStatus.IDLE
            ctx.token_count += event.tokens_used
        if self._token_counter is not None:
            self._token_counter.add(event.agent, event.tokens_used)

    def _handle_tool_start(self, event: ToolStart) -> None:
        """End any stream and render tool start panel."""
        self._end_stream()
        self._renderer.render_tool_start(event.tool, event.input, event.agent)

    def _handle_tool_result(self, event: ToolResult) -> None:
        """Render tool result panel."""
        output_str = str(event.output) if event.output is not None else ""
        self._renderer.render_tool_result(event.tool, output_str, event.agent)

    def _handle_confirm_request(self, event: ConfirmRequest) -> None:
        """End stream, store pending confirm, render prompt."""
        self._end_stream()
        self._pending_confirm = event
        self._renderer.render_confirm_prompt(
            confirm_id=event.tool_id,
            tool_name=event.tool,
            params=event.input,
            agent=event.agent,
        )

    def _handle_error(self, event: ErrorEvent) -> None:
        """Render error message."""
        self._renderer.render_error(event.message)

    def _handle_dispatch_complete(self, event: DispatchComplete) -> None:
        """End any active stream."""
        self._end_stream()
