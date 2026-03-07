"""Tests for CLI confirm-gated tool prompts."""

from corvus.cli.chat_confirm import parse_confirm_response


def test_parse_y_returns_allow() -> None:
    result = parse_confirm_response("y")
    assert result.action == "allow"
    assert result.note is None


def test_parse_n_returns_deny() -> None:
    result = parse_confirm_response("n")
    assert result.action == "deny"
    assert result.note is None


def test_parse_plus_note() -> None:
    result = parse_confirm_response("+this is important")
    assert result.action == "note"
    assert result.note == "this is important"


def test_parse_c_returns_converse() -> None:
    result = parse_confirm_response("c")
    assert result.action == "converse"


def test_parse_yes_returns_allow() -> None:
    result = parse_confirm_response("yes")
    assert result.action == "allow"


def test_parse_no_returns_deny() -> None:
    result = parse_confirm_response("no")
    assert result.action == "deny"


def test_parse_unknown_returns_deny() -> None:
    result = parse_confirm_response("blah")
    assert result.action == "deny"
