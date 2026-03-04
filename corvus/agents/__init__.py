"""Agents Hub — config-driven agent definitions, registry, and lifecycle.

Public API:
    from corvus.agents import AgentSpec, AgentModelConfig, AgentToolConfig, AgentMemoryConfig
    from corvus.agents import AgentRegistry, ReloadResult
    from corvus.agents import AgentsHub, AgentSummary

Agent definitions are loaded from YAML specs in config/agents/*.yaml.
"""

from corvus.agents.hub import AgentsHub, AgentSummary
from corvus.agents.registry import AgentRegistry, ReloadResult
from corvus.agents.spec import (
    AgentMemoryConfig,
    AgentModelConfig,
    AgentSpec,
    AgentToolConfig,
)

__all__ = [
    "AgentMemoryConfig",
    "AgentModelConfig",
    "AgentRegistry",
    "AgentsHub",
    "AgentSpec",
    "AgentSummary",
    "AgentToolConfig",
    "ReloadResult",
]
