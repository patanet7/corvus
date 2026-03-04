"""Tests for routing_decision event emission in WebSocket path."""

import re
from pathlib import Path

CHAT_SRC_PATH = Path(__file__).parent.parent.parent / "corvus" / "gateway" / "chat_session.py"


def _find_ws_routing_block(source: str) -> str:
    """Find the emitter.emit block for routing_decision in ChatSession.

    Returns the text block from 'self.runtime.emitter.emit' through the closing ')'.
    ChatSession uses 'await self.runtime.emitter.emit(...)' directly,
    while webhooks.py uses a fire-and-forget helper.
    """
    # Match self.runtime.emitter.emit( <optional newline+whitespace> "routing_decision" ... )
    # across multiple lines (the call is formatted with line breaks)
    pattern = r'self\.runtime\.emitter\.emit\(\s*["\']routing_decision["\'].*?\)'
    match = re.search(pattern, source, re.DOTALL)
    assert match is not None, "routing_decision emit block not found in chat_session.py"
    return match.group(0)


class TestRoutingDecisionEmit:
    """Verify that the WebSocket chat path emits routing_decision events."""

    def test_routing_decision_emitted_in_websocket_path(self):
        """ChatSession contains a self.runtime.emitter.emit('routing_decision', ...) call."""
        source = CHAT_SRC_PATH.read_text()
        block = _find_ws_routing_block(source)
        assert "routing_decision" in block

    def test_routing_decision_includes_source_websocket(self):
        """The routing_decision emit specifies source='websocket'."""
        source = CHAT_SRC_PATH.read_text()
        assert 'source="websocket"' in source or "source='websocket'" in source

    def test_routing_decision_includes_agent_and_backend(self):
        """The routing_decision emit includes agent and backend fields."""
        source = CHAT_SRC_PATH.read_text()
        block = _find_ws_routing_block(source)
        assert "agent=" in block, "routing_decision emit missing agent= kwarg"
        assert "backend=" in block, "routing_decision emit missing backend= kwarg"

    def test_routing_decision_includes_query_preview(self):
        """The routing_decision emit includes a query_preview field."""
        source = CHAT_SRC_PATH.read_text()
        block = _find_ws_routing_block(source)
        assert "query_preview=" in block, "routing_decision emit missing query_preview= kwarg"

    def test_routing_decision_truncates_query_preview(self):
        """The query_preview is truncated to 200 chars (matching webhook pattern)."""
        source = CHAT_SRC_PATH.read_text()
        block = _find_ws_routing_block(source)
        assert "[:200]" in block, "query_preview should be truncated to 200 chars"

    def test_websocket_emit_is_awaited(self):
        """The emitter.emit call in ChatSession is awaited (async context)."""
        source = CHAT_SRC_PATH.read_text()
        # Find the await keyword immediately before the emitter.emit call
        pattern = r'await\s+self\.runtime\.emitter\.emit\(\s*["\']routing_decision["\']'
        match = re.search(pattern, source, re.DOTALL)
        assert match is not None, "routing_decision emit should be awaited in ChatSession"

    def test_both_webhook_and_websocket_emit_routing_decision(self):
        """Both webhook and WebSocket paths emit routing_decision events."""
        chat_src = CHAT_SRC_PATH.read_text()
        webhooks_src = (CHAT_SRC_PATH.parent.parent / "webhooks.py").read_text()

        # WebSocket path: direct await runtime.emitter.emit
        block = _find_ws_routing_block(chat_src)
        assert "routing_decision" in block, "chat.py missing routing_decision emit"

        # Webhook path: _emit_routing_decision helper
        assert "_emit_routing_decision" in webhooks_src, "webhooks.py missing _emit_routing_decision helper"
