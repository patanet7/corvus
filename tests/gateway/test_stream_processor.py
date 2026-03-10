"""Behavioral tests for StreamProcessor — no mocks."""

from corvus.gateway.stream_processor import RunContext, RunResult


class TestRunContext:
    def test_create_with_all_fields(self):
        ctx = RunContext(
            dispatch_id="disp-1",
            run_id="run-1",
            task_id="task-run-1",
            session_id="sess-1",
            turn_id="turn-1",
            agent_name="work",
            model_id="claude-sonnet-4-5",
            route_payload={
                "task_type": "direct",
                "subtask_id": None,
                "skill": None,
                "instruction": "do work",
                "route_index": 0,
            },
        )
        assert ctx.agent_name == "work"
        assert ctx.route_payload["task_type"] == "direct"


class TestRunResult:
    def test_success_result(self):
        result = RunResult(
            status="success",
            tokens_used=1500,
            cost_usd=0.05,
            context_pct=12.5,
            response_text="Hello world",
            sdk_session_id="sdk-abc",
            checkpoints=["msg-1"],
        )
        assert result.status == "success"
        assert result.tokens_used == 1500

    def test_error_result(self):
        result = RunResult(
            status="error",
            tokens_used=0,
            cost_usd=0.0,
            context_pct=0.0,
            response_text="",
            sdk_session_id=None,
            checkpoints=[],
        )
        assert result.status == "error"


from claude_agent_sdk.types import StreamEvent

from corvus.gateway.stream_processor import StreamProcessor, _ToolUseState


class TestStreamEventHandling:
    """Test the event dispatch logic using pre-built StreamEvent dicts."""

    def _make_stream_event(self, event_dict: dict, parent_tool_use_id: str | None = None):
        """Build a StreamEvent-like object for testing."""
        return StreamEvent(
            uuid="test-uuid",
            session_id="test-session",
            event=event_dict,
            parent_tool_use_id=parent_tool_use_id,
        )

    def test_text_delta_accumulates(self):
        proc = StreamProcessor._create_for_test()
        event = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello "},
        })
        proc._buffer_stream_event(event)
        assert proc._text_buffer == "Hello "

        event2 = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "world"},
        })
        proc._buffer_stream_event(event2)
        assert proc._text_buffer == "Hello world"

    def test_tool_use_tracking(self):
        proc = StreamProcessor._create_for_test()
        start = self._make_stream_event({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Bash", "id": "tool-1"},
        })
        proc._buffer_stream_event(start)
        assert proc._tool_state is not None
        assert proc._tool_state.name == "Bash"

        delta = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"command":'},
        })
        proc._buffer_stream_event(delta)
        assert proc._tool_state.input_buffer == '{"command":'

        stop = self._make_stream_event({"type": "content_block_stop"})
        proc._buffer_stream_event(stop)
        assert proc._tool_state is None

    def test_thinking_delta_accumulates(self):
        proc = StreamProcessor._create_for_test()
        start = self._make_stream_event({
            "type": "content_block_start",
            "content_block": {"type": "thinking"},
        })
        proc._buffer_stream_event(start)

        delta = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "Let me think..."},
        })
        proc._buffer_stream_event(delta)
        assert proc._thinking_buffer == "Let me think..."

    def test_subagent_detection(self):
        proc = StreamProcessor._create_for_test()
        event = self._make_stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "sub"}},
            parent_tool_use_id="parent-tool-1",
        )
        is_sub = event.parent_tool_use_id is not None
        assert is_sub is True

    def test_finalize_result(self):
        proc = StreamProcessor._create_for_test()
        proc._text_buffer = "The answer is 42"
        result = proc._build_run_result(
            tokens_input=1000,
            tokens_output=500,
            cost_usd=0.04,
            sdk_session_id="sdk-xyz",
            context_limit=200000,
        )
        assert result.status == "success"
        assert result.tokens_used == 1500
        assert result.cost_usd == 0.04
        assert result.response_text == "The answer is 42"
        assert result.sdk_session_id == "sdk-xyz"
        assert result.context_pct == 0.8  # 1500/200000 * 100
