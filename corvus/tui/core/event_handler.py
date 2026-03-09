"""Event handler for the Corvus TUI.

Maps incoming ProtocolEvent objects to renderer calls and agent stack
state transitions. Tracks streaming state and pending confirmations.
"""

from collections.abc import Callable

from corvus.security.sanitizer import sanitize_tool_result
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
        self._tool_names: dict[str, str] = {}  # tool_id → tool_name
        self._auto_approve_check: Callable[[str], bool] | None = None
        self._auto_approve_confirm: Callable[[str, str], None] | None = None

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
        """Set agent to THINKING and start the thinking spinner."""
        ctx = self._agent_stack.find(event.agent)
        if ctx is not None:
            ctx.status = AgentStatus.THINKING
        self._renderer.render_thinking_start(event.agent)

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
        if event.tool_id and event.tool:
            self._tool_names[event.tool_id] = event.tool
        self._renderer.render_tool_start(event.tool, event.input, event.agent)

    def _handle_tool_result(self, event: ToolResult) -> None:
        """Render tool result panel, recovering tool name from start event if needed.

        The output is sanitized to scrub credential patterns before display.
        """
        tool_name = event.tool or self._tool_names.pop(event.tool_id, "")
        output_str = str(event.output) if event.output is not None else ""
        sanitized = sanitize_tool_result(output_str)
        self._renderer.render_tool_result(tool_name, sanitized, event.agent)

    def set_auto_approve(
        self,
        check_fn: Callable[[str], bool],
        confirm_fn: Callable[[str, str], None],
    ) -> None:
        """Set callbacks for auto-approval of tool confirmations.

        Parameters
        ----------
        check_fn:
            Called with tool_name, returns True if the tool is always-allowed.
        confirm_fn:
            Called with (tool_id, approved=True) to auto-approve without
            user interaction. Takes tool_id and a literal "approve" string.
        """
        self._auto_approve_check = check_fn
        self._auto_approve_confirm = confirm_fn

    def _handle_confirm_request(self, event: ConfirmRequest) -> None:
        """End stream, check auto-approve, then store pending confirm and render prompt."""
        self._end_stream()

        # Auto-approve if tool is in always-allow set
        if self._auto_approve_check is not None and self._auto_approve_check(event.tool):
            if self._auto_approve_confirm is not None:
                self._auto_approve_confirm(event.tool_id, "approve")
            return

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
