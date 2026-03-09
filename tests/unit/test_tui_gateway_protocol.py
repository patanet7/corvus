"""Unit tests for the in-process gateway protocol adapter.

These tests verify structural contracts only — no full integration
(which would require a running LiteLLM proxy + API keys).
"""

from collections.abc import Callable, Coroutine
from typing import Any

from corvus.tui.protocol.base import GatewayProtocol
from corvus.tui.protocol.events import ProtocolEvent
from corvus.tui.protocol.in_process import InProcessGateway


def test_in_process_implements_protocol() -> None:
    """InProcessGateway must be a subclass of GatewayProtocol."""
    assert issubclass(InProcessGateway, GatewayProtocol)


def test_in_process_instantiates() -> None:
    """No-arg construction must succeed and set expected defaults."""
    gw = InProcessGateway()
    assert gw._runtime is None
    assert gw._session is None
    assert gw._event_callback is None
    assert gw._connected is False


def test_event_callback_registration() -> None:
    """on_event() must store the callback for later use."""
    gw = InProcessGateway()

    events_received: list[ProtocolEvent] = []

    async def callback(event: ProtocolEvent) -> None:
        events_received.append(event)

    gw.on_event(callback)
    assert gw._event_callback is callback


def test_on_event_type_signature() -> None:
    """on_event must accept an async callback matching the protocol type."""
    gw = InProcessGateway()

    async def typed_callback(event: ProtocolEvent) -> None:
        pass

    # Should not raise
    gw.on_event(typed_callback)

    # Verify it was stored
    assert gw._event_callback is typed_callback


def test_initial_state_attributes() -> None:
    """Verify all expected instance attributes exist with correct initial values."""
    gw = InProcessGateway()

    # All required attributes should exist
    assert hasattr(gw, "_runtime")
    assert hasattr(gw, "_session")
    assert hasattr(gw, "_event_callback")
    assert hasattr(gw, "_connected")

    # Check types
    assert isinstance(gw._connected, bool)
    assert gw._runtime is None
    assert gw._session is None


def test_multiple_callback_registrations() -> None:
    """Registering a new callback should replace the previous one."""
    gw = InProcessGateway()

    async def callback_a(event: ProtocolEvent) -> None:
        pass

    async def callback_b(event: ProtocolEvent) -> None:
        pass

    gw.on_event(callback_a)
    assert gw._event_callback is callback_a

    gw.on_event(callback_b)
    assert gw._event_callback is callback_b
