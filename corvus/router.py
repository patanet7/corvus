"""Router Agent -- lightweight intent classifier for domain dispatch.

Uses Claude Haiku (always SDK-native, always fast) to classify user intent
and pick the right domain agent. The router runs BEFORE any backend routing
so we know which agent (and therefore which model backend) to use.
"""

from __future__ import annotations

import os
import re
from typing import Protocol

import anthropic
import structlog

logger = structlog.get_logger(__name__)

# Fallback agent set used when no AgentRegistry is provided.
# Production always uses registry.list_enabled() via get_valid_agents().
VALID_AGENTS = _FALLBACK_AGENTS = {
    "personal",
    "work",
    "homelab",
    "finance",
    "email",
    "docs",
    "music",
    "home",
    "general",
}

# Fallback prompt when no AgentRegistry is provided — production builds
# prompts dynamically from registry specs via _build_routing_prompt().
_FALLBACK_ROUTING_PROMPT = """You are a message router. Given a user message, determine which domain agent should handle it. Reply with ONLY the agent name, nothing else.

Available agents:
- personal: daily planning, ADHD support, journaling, health tracking, self-care
- work: work projects, meeting notes, career, professional tasks
- homelab: servers, Docker, Komodo, infrastructure, networking
- finance: Firefly transactions, budgets, spending, accounts
- email: Gmail/Yahoo inbox triage, compose, cleanup, labels
- docs: Paperless-ngx documents, Google Drive files
- music: practice planning, repertoire, technique coaching
- home: Home Assistant smart home control, lights, sensors
- general: cross-domain, multi-topic, conversation, anything spanning domains"""


class _AgentRegistryProtocol(Protocol):
    def list_enabled(self) -> list: ...


ROUTER_MODEL_DEFAULT = "claude-haiku-4-5-20251001"


class RouterAgent:
    """Classifies user intent and returns the target agent name.

    Uses Claude Haiku via direct API call (not the SDK) for speed.
    Falls back to 'general' if classification fails.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        registry: _AgentRegistryProtocol | None = None,
    ) -> None:
        # Store explicit overrides; env vars are read lazily at classify()
        # time because ANTHROPIC_BASE_URL may not be set yet (LiteLLM starts
        # after build_runtime).
        self._explicit_api_key = api_key
        self._explicit_model = model
        self._explicit_base_url = base_url
        self._registry = registry

    @property
    def _api_key(self) -> str:
        return (
            self._explicit_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
            or ""
        )

    @property
    def _model(self) -> str:
        return self._explicit_model or os.environ.get("ROUTER_MODEL", ROUTER_MODEL_DEFAULT)

    @property
    def _base_url(self) -> str | None:
        return self._explicit_base_url or os.environ.get("ANTHROPIC_BASE_URL") or None

    def get_valid_agents(self) -> set[str]:
        """Return the set of valid agent names.

        When an AgentRegistry is attached, reads enabled agents from config.
        Otherwise falls back to the hardcoded VALID_AGENTS set.
        """
        if self._registry is not None:
            return {s.name for s in self._registry.list_enabled()}
        return _FALLBACK_AGENTS

    def parse_response(self, response: str) -> str:
        """Parse the LLM's response into a valid agent name.

        Handles edge cases: extra whitespace, casing, multi-word responses.
        Falls back to 'general' if no valid agent found.
        """
        text = response.strip().lower()
        valid = self.get_valid_agents()

        # Direct match
        if text in valid:
            return text

        # Check if any valid agent name appears in the response
        # Sort by length descending so "homelab" matches before "home"
        for agent in sorted(valid, key=len, reverse=True):
            if re.search(rf"\b{re.escape(agent)}\b", text):
                return agent

        return "general"

    def _build_routing_prompt(self) -> str:
        """Build the routing prompt, using registry descriptions when available."""
        if self._registry is not None:
            lines = [
                "You are a message router. Given a user message, determine which "
                "domain agent should handle it. Reply with ONLY the agent name, "
                "nothing else.\n\nAvailable agents:"
            ]
            for spec in self._registry.list_enabled():
                lines.append(f"- {spec.name}: {spec.description}")
            return "\n".join(lines)
        return _FALLBACK_ROUTING_PROMPT

    async def classify(self, user_message: str) -> str:
        """Classify user intent and return agent name.

        Makes a real Claude Haiku API call. Falls back to 'general' on
        transient errors; re-raises permanent errors like auth failures.
        """
        try:
            client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                base_url=self._base_url,
            )
            response = await client.messages.create(
                model=self._model,
                max_tokens=20,
                system=self._build_routing_prompt(),
                messages=[{"role": "user", "content": user_message}],
            )
            block = response.content[0] if response.content else None
            result_text = block.text if block is not None and hasattr(block, "text") else ""
            agent = self.parse_response(result_text)
            logger.info("router_classified", agent=agent, raw=result_text)
            return agent
        except anthropic.AuthenticationError:
            logger.error(
                "router_auth_failed",
                hint="check ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN (OAuth tokens require LiteLLM proxy via ANTHROPIC_BASE_URL)",
            )
            return "general"
        except anthropic.RateLimitError:
            logger.warning("router_rate_limited", fallback="general")
            return "general"
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            logger.warning("router_connection_error", fallback="general")
            return "general"
        except Exception:
            logger.exception("router_classification_failed", fallback="general")
            return "general"
