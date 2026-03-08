"""Tests for corvus chat CLI argument parsing."""

from corvus.cli.chat import parse_args


def test_default_args() -> None:
    args = parse_args([])
    assert args.agent is None
    assert args.model is None
    assert args.resume is None
    assert args.budget is None
    assert args.max_turns is None
    assert args.list_agents is False
    assert args.list_models is False


def test_agent_flag() -> None:
    args = parse_args(["--agent", "homelab"])
    assert args.agent == "homelab"


def test_model_override() -> None:
    args = parse_args(["--agent", "homelab", "--model", "ollama/qwen3:8b"])
    assert args.model == "ollama/qwen3:8b"


def test_resume_flag() -> None:
    args = parse_args(["--resume", "sess-abc123"])
    assert args.resume == "sess-abc123"


def test_budget_flag() -> None:
    args = parse_args(["--budget", "0.50"])
    assert args.budget == 0.50


def test_max_turns_flag() -> None:
    args = parse_args(["--max-turns", "10"])
    assert args.max_turns == 10


def test_list_agents_flag() -> None:
    args = parse_args(["--list-agents"])
    assert args.list_agents is True


def test_list_models_flag() -> None:
    args = parse_args(["--list-models"])
    assert args.list_models is True



def test_permission_flag() -> None:
    args = parse_args(["--permission", "default"])
    assert args.permission == "default"
