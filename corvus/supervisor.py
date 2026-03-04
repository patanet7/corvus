"""AgentSupervisor — heartbeat loop and MCP server lifecycle management.

Keeps the agent fleet alive: periodic health checks, auto-restart of failed
modules, degradation tracking, and status events via EventEmitter.

Usage:
    supervisor = AgentSupervisor(registry=registry, emitter=emitter)
    await supervisor.start()       # Begin heartbeat loop (background task)
    await supervisor.heartbeat()   # Single heartbeat check (for testing)
    await supervisor.graceful_shutdown()  # Stop all modules
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth
from corvus.events import EventEmitter

logger = logging.getLogger("corvus-gateway.supervisor")

HEARTBEAT_INTERVAL = 30  # seconds
MAX_RESTART_ATTEMPTS = 3


class AgentSupervisor:
    """Manages the lifecycle of tool modules via CapabilitiesRegistry.

    Attributes:
        registry: The capabilities registry to monitor.
        emitter: Event emitter for heartbeat events.
        heartbeat_interval: Seconds between heartbeat cycles.
    """

    def __init__(
        self,
        registry: CapabilitiesRegistry,
        emitter: EventEmitter,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
    ) -> None:
        self.registry = registry
        self.emitter = emitter
        self.heartbeat_interval = heartbeat_interval
        self._started_at = time.monotonic()
        self._task: asyncio.Task[None] | None = None
        self._restart_counts: dict[str, int] = {}

    async def start(self) -> None:
        """Start the heartbeat background loop."""
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        logger.info("AgentSupervisor started (interval=%ds)", self.heartbeat_interval)

    async def _loop(self) -> None:
        """Internal heartbeat loop — runs until cancelled."""
        while True:
            try:
                await self.heartbeat()
            except Exception:
                logger.exception("Heartbeat cycle failed")
            await asyncio.sleep(self.heartbeat_interval)

    async def heartbeat(self) -> dict[str, Any]:
        """Run one heartbeat cycle: check all modules, emit status event.

        Iterates registered modules via CapabilitiesRegistry, collects health
        from each, and attempts to restart any unhealthy module that has a
        ``restart`` callable configured. Restart failures are logged but never
        propagate — the heartbeat must always complete.

        Returns:
            Dict mapping module name to its status summary dict.
        """
        mcp_status: dict[str, dict[str, Any]] = {}
        for module_name in self.registry.list_available():
            health: ModuleHealth = self.registry.health(module_name)
            mcp_status[module_name] = {
                "status": health.status,
                "detail": health.detail,
            }
            if health.status == "healthy":
                self._restart_counts.pop(module_name, None)  # reset on recovery
            elif health.status == "unhealthy":
                await self._try_restart(module_name, mcp_status)

        uptime = time.monotonic() - self._started_at

        await self.emitter.emit(
            "heartbeat",
            uptime_seconds=round(uptime, 1),
            mcp_servers=mcp_status,
        )

        return mcp_status

    async def restart_provider(self, name: str) -> None:
        """Restart a specific module by name.

        Resets the restart counter and attempts a restart regardless of
        the current count. Raises KeyError if the module is not registered
        or has no restart callable.
        """
        entry = self.registry.get_module(name)
        if entry is None:
            raise KeyError(f"Module '{name}' not found")
        if entry.restart is None:
            raise KeyError(f"Module '{name}' has no restart callable")
        self._restart_counts.pop(name, None)
        await entry.restart()
        await self.emitter.emit("provider_restart", provider=name, source="manual")
        logger.info("Manually restarted module: %s", name)

    async def _try_restart(self, name: str, mcp_status: dict[str, dict[str, Any]]) -> None:
        """Attempt to restart an unhealthy module, respecting the retry cap."""
        count = self._restart_counts.get(name, 0)
        if count >= MAX_RESTART_ATTEMPTS:
            mcp_status[name]["status"] = "degraded"
            mcp_status[name]["detail"] = f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) exceeded"
            return
        entry = self.registry.get_module(name)
        if entry is None or entry.restart is None:
            return
        try:
            self._restart_counts[name] = count + 1
            await entry.restart()
            mcp_status[name]["status"] = "restarting"
            await self.emitter.emit(
                "provider_restart",
                provider=name,
                attempt=count + 1,
            )
            logger.info("Restarted module %s (attempt %d)", name, count + 1)
        except Exception:
            logger.exception("Failed to restart module %s (attempt %d)", name, count + 1)

    async def graceful_shutdown(self) -> None:
        """Cancel the heartbeat loop and wait for it to finish."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AgentSupervisor stopped")
