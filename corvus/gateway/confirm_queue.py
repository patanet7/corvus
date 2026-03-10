"""Async confirmation queue for gated tool calls.

When a tool is confirm-gated, the runtime blocks execution and sends a
confirm_request to the frontend via WebSocket. The frontend shows a
confirmation dialog. When the user responds, the response is fed into
this queue, unblocking the waiting coroutine.
"""

import asyncio
import structlog

logger = structlog.get_logger(__name__)


class ConfirmQueue:
    """Manages pending confirmation requests keyed by tool call ID."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def wait_for_confirmation(
        self,
        call_id: str,
        *,
        timeout_s: float = 60.0,
    ) -> bool:
        """Block until user responds or timeout expires.

        Returns True if approved, False if denied or timed out.
        """
        if call_id in self._pending:
            logger.warning("duplicate_confirm_request", call_id=call_id)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[call_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("confirm_gate_timed_out", call_id=call_id)
            return False
        finally:
            self._pending.pop(call_id, None)

    def respond(self, call_id: str, *, approved: bool) -> None:
        """Deliver user's confirm/deny response to the waiting coroutine."""
        future = self._pending.get(call_id)
        if future is None:
            logger.warning("confirm_response_unknown", call_id=call_id)
            return
        if future.done():
            logger.warning("confirm_response_already_resolved", call_id=call_id)
            return
        future.set_result(approved)

    def cancel_all(self) -> None:
        """Cancel all pending confirmations (e.g., on session close)."""
        for call_id, future in self._pending.items():
            if not future.done():
                future.set_result(False)
                logger.info("cancelled_pending_confirm", call_id=call_id)
        self._pending.clear()
