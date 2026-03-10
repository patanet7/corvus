"""Verify SDK option fields exist for new features — no mocks."""

import pytest

from claude_agent_sdk import ClaudeAgentOptions


class TestSDKFeatureFlags:
    """Confirm ClaudeAgentOptions exposes every field the SDK integration needs."""

    def test_include_partial_messages_flag_exists(self):
        """Verify ClaudeAgentOptions has include_partial_messages field."""
        opts = ClaudeAgentOptions()
        assert hasattr(opts, "include_partial_messages")
        assert opts.include_partial_messages is False
        opts.include_partial_messages = True
        assert opts.include_partial_messages is True

    def test_enable_file_checkpointing_flag_exists(self):
        opts = ClaudeAgentOptions()
        assert hasattr(opts, "enable_file_checkpointing")
        assert opts.enable_file_checkpointing is False
        opts.enable_file_checkpointing = True
        assert opts.enable_file_checkpointing is True

    def test_max_turns_field_exists(self):
        opts = ClaudeAgentOptions(max_turns=50)
        assert opts.max_turns == 50

    def test_max_turns_default_is_none(self):
        opts = ClaudeAgentOptions()
        assert opts.max_turns is None

    def test_max_budget_field_exists(self):
        opts = ClaudeAgentOptions(max_budget_usd=5.0)
        assert opts.max_budget_usd == 5.0

    def test_max_budget_default_is_none(self):
        opts = ClaudeAgentOptions()
        assert opts.max_budget_usd is None

    def test_resume_field_exists(self):
        opts = ClaudeAgentOptions(resume="session-xyz")
        assert opts.resume == "session-xyz"

    def test_resume_default_is_none(self):
        opts = ClaudeAgentOptions()
        assert opts.resume is None

    def test_fallback_model_field_exists(self):
        opts = ClaudeAgentOptions(fallback_model="claude-3-haiku-20240307")
        assert opts.fallback_model == "claude-3-haiku-20240307"

    def test_fallback_model_default_is_none(self):
        opts = ClaudeAgentOptions()
        assert opts.fallback_model is None

    def test_effort_field_exists(self):
        opts = ClaudeAgentOptions(effort="high")
        assert opts.effort == "high"

    def test_effort_default_is_none(self):
        opts = ClaudeAgentOptions()
        assert opts.effort is None

    def test_fork_session_field_exists(self):
        opts = ClaudeAgentOptions(fork_session=True)
        assert opts.fork_session is True

    def test_fork_session_default_is_false(self):
        opts = ClaudeAgentOptions()
        assert opts.fork_session is False
