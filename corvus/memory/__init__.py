"""Corvus Memory Hub — plugin-based multi-agent memory system.

Usage:
    from corvus.memory import MemoryHub, MemoryConfig, create_memory_toolkit

    config = MemoryConfig(primary_db_path=Path("memory.sqlite"))
    hub = MemoryHub(config)
    tools = create_memory_toolkit(hub, agent_name="homelab")
"""

from corvus.memory.config import BackendConfig, MemoryConfig
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord
from corvus.memory.toolkit import create_memory_toolkit

__all__ = [
    "BackendConfig",
    "MemoryConfig",
    "MemoryHub",
    "MemoryRecord",
    "create_memory_toolkit",
]
