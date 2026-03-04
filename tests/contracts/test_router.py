"""Behavioral tests for the Router Agent intent classifier.

Tests the prompt construction and response parsing.
Does NOT call Claude API -- tests the routing logic, not the LLM.
"""

from corvus.router import VALID_AGENTS, RouterAgent, build_routing_prompt


def test_valid_agents_contains_all_nine():
    assert len(VALID_AGENTS) == 9
    assert "personal" in VALID_AGENTS
    assert "general" in VALID_AGENTS
    assert "homelab" in VALID_AGENTS


def test_build_routing_prompt_contains_all_agents():
    prompt = build_routing_prompt()
    for agent in VALID_AGENTS:
        assert agent in prompt


def test_parse_response_extracts_agent_name():
    router = RouterAgent(api_key="test")  # Won't call API in parse
    assert router.parse_response("personal") == "personal"
    assert router.parse_response("  homelab  ") == "homelab"
    assert router.parse_response("FINANCE") == "finance"


def test_parse_response_falls_back_to_general():
    router = RouterAgent(api_key="test")
    assert router.parse_response("unknown_agent") == "general"
    assert router.parse_response("") == "general"
    assert router.parse_response("I'm not sure what to do") == "general"


def test_parse_response_handles_multiword():
    """If LLM returns 'personal agent', extract just 'personal'."""
    router = RouterAgent(api_key="test")
    assert router.parse_response("personal agent") == "personal"
    assert router.parse_response("the homelab agent should handle this") == "homelab"
    assert router.parse_response("I think the personal agent") == "personal"
