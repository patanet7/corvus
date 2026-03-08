"""Tests for inbox.py CLI interface.

Verifies the CLI contract (JSON output shapes, error handling, argument parsing)
and behavioral correctness (triage categorization, age parsing, header decoding)
by running the script as a subprocess — the same way agents invoke it via Bash.

Note: The script is named inbox.py (not email.py) to avoid shadowing Python's
stdlib email module.

NO MOCKS. No MagicMock, no monkeypatch, no @patch.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = str(WORKTREE_ROOT / "scripts" / "inbox.py")
_PYTHON_DIR = str(Path(sys.executable).parent)


def _run_cli(
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the email CLI as a subprocess."""
    import os

    env = {
        "PATH": f"{_PYTHON_DIR}:/usr/bin:/usr/local/bin",
        "PYTHONPATH": str(WORKTREE_ROOT),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, CLI_SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Contract: CLI help and argument parsing
# ---------------------------------------------------------------------------


class TestCLIContract:
    """Verify the CLI responds correctly to argument parsing scenarios."""

    def test_no_args_exits_nonzero(self) -> None:
        """CLI with no arguments should exit with error."""
        result = _run_cli([])
        assert result.returncode != 0

    def test_help_flag(self) -> None:
        """CLI --help should print usage and exit 0."""
        result = _run_cli(["--help"])
        assert result.returncode == 0
        assert "Email inbox management CLI" in result.stdout

    def test_gmail_search_help(self) -> None:
        """gmail-search --help should print subcommand usage."""
        result = _run_cli(["gmail-search", "--help"])
        assert result.returncode == 0
        assert "query" in result.stdout.lower()

    def test_gmail_labels_help(self) -> None:
        result = _run_cli(["gmail-labels", "--help"])
        assert result.returncode == 0

    def test_gmail_unread_help(self) -> None:
        result = _run_cli(["gmail-unread", "--help"])
        assert result.returncode == 0

    def test_gmail_bulk_label_help(self) -> None:
        result = _run_cli(["gmail-bulk-label", "--help"])
        assert result.returncode == 0
        assert "label" in result.stdout.lower()

    def test_yahoo_search_help(self) -> None:
        result = _run_cli(["yahoo-search", "--help"])
        assert result.returncode == 0

    def test_yahoo_unread_help(self) -> None:
        result = _run_cli(["yahoo-unread", "--help"])
        assert result.returncode == 0

    def test_yahoo_folders_help(self) -> None:
        result = _run_cli(["yahoo-folders", "--help"])
        assert result.returncode == 0

    def test_triage_help(self) -> None:
        result = _run_cli(["triage", "--help"])
        assert result.returncode == 0
        assert "provider" in result.stdout.lower()

    def test_cleanup_help(self) -> None:
        result = _run_cli(["cleanup", "--help"])
        assert result.returncode == 0
        assert "older-than" in result.stdout.lower()

    def test_invalid_subcommand(self) -> None:
        """Unknown subcommand should fail."""
        result = _run_cli(["not-a-command"])
        assert result.returncode != 0

    def test_cleanup_requires_provider(self) -> None:
        """cleanup without --provider should fail."""
        result = _run_cli(["cleanup", "--older-than", "30d"])
        assert result.returncode != 0

    def test_cleanup_requires_older_than(self) -> None:
        """cleanup without --older-than should fail."""
        result = _run_cli(["cleanup", "--provider", "gmail"])
        assert result.returncode != 0

    def test_triage_accepts_provider_choices(self) -> None:
        """triage --provider accepts gmail, yahoo, all."""
        for provider in ["gmail", "yahoo", "all"]:
            result = _run_cli(["triage", "--help"])
            assert provider in result.stdout


# ---------------------------------------------------------------------------
# Contract: Gmail commands fail gracefully without credentials
# ---------------------------------------------------------------------------


class TestGmailMissingCredentials:
    """Gmail commands without GMAIL_CREDENTIALS should produce JSON error on stderr."""

    def test_gmail_search_no_creds(self) -> None:
        result = _run_cli(["gmail-search", "test query"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "GMAIL_CREDENTIALS" in error["error"]

    def test_gmail_labels_no_creds(self) -> None:
        result = _run_cli(["gmail-labels"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "GMAIL_CREDENTIALS" in error["error"]

    def test_gmail_unread_no_creds(self) -> None:
        result = _run_cli(["gmail-unread"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "GMAIL_CREDENTIALS" in error["error"]

    def test_gmail_bulk_label_no_creds(self) -> None:
        result = _run_cli(["gmail-bulk-label", "test-label", "--query", "test"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "GMAIL_CREDENTIALS" in error["error"]

    def test_gmail_search_nonexistent_creds_file(self) -> None:
        """GMAIL_CREDENTIALS pointing to nonexistent file should produce JSON error."""
        result = _run_cli(
            ["gmail-search", "test"],
            extra_env={"GMAIL_CREDENTIALS": "/tmp/nonexistent_creds.json"},
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "not found" in error["error"]


# ---------------------------------------------------------------------------
# Contract: Yahoo commands fail gracefully without credentials
# ---------------------------------------------------------------------------


class TestYahooMissingCredentials:
    """Yahoo commands without env vars should produce JSON error on stderr."""

    def test_yahoo_search_no_email(self) -> None:
        result = _run_cli(["yahoo-search", "test query"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "YAHOO_EMAIL" in error["error"]

    def test_yahoo_unread_no_email(self) -> None:
        result = _run_cli(["yahoo-unread"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "YAHOO_EMAIL" in error["error"]

    def test_yahoo_folders_no_email(self) -> None:
        result = _run_cli(["yahoo-folders"])
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "YAHOO_EMAIL" in error["error"]

    def test_yahoo_search_no_password(self) -> None:
        """YAHOO_EMAIL set but no YAHOO_APP_PASSWORD should error about password."""
        result = _run_cli(
            ["yahoo-search", "test"],
            extra_env={"YAHOO_EMAIL": "test@yahoo.com"},
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "YAHOO_APP_PASSWORD" in error["error"]


# ---------------------------------------------------------------------------
# Behavioral: triage categorization logic
# ---------------------------------------------------------------------------


class TestTriageCategorization:
    """Test the _categorize_message function via direct import.

    These tests exercise the real categorization function with real message
    structures — no mocks, no patches.
    """

    @pytest.fixture(autouse=True)
    def _import_module(self) -> None:
        """Import the categorization function from the inbox module."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("inbox_cli", CLI_SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.categorize = mod._categorize_message

    def test_action_required_subject(self) -> None:
        result = self.categorize("Action Required: Review Q1 budget", "boss@work.com")
        assert result == "action"

    def test_please_respond(self) -> None:
        result = self.categorize("Please respond by Friday", "colleague@work.com")
        assert result == "action"

    def test_deadline_in_subject(self) -> None:
        result = self.categorize("Deadline: Project submission", "pm@work.com")
        assert result == "action"

    def test_rsvp_request(self) -> None:
        result = self.categorize("RSVP: Team dinner next week", "hr@work.com")
        assert result == "action"

    def test_fyi_is_delegate(self) -> None:
        result = self.categorize("FYI: Updated policy docs", "admin@work.com")
        assert result == "delegate"

    def test_newsletter_is_archive(self) -> None:
        result = self.categorize("Weekly Newsletter: Tech Digest", "newsletter@example.com")
        assert result == "archive"

    def test_receipt_is_archive(self) -> None:
        result = self.categorize("Your receipt from Amazon", "no-reply@amazon.com")
        assert result == "archive"

    def test_notification_is_archive(self) -> None:
        result = self.categorize("Notification: Your order shipped", "noreply@ups.com")
        assert result == "archive"

    def test_unsubscribe_is_delete(self) -> None:
        result = self.categorize("Special sale! Unsubscribe here", "spam@promo.com")
        assert result == "delete"

    def test_promotion_is_delete(self) -> None:
        result = self.categorize("Promotion: 50% off everything", "store@example.com")
        assert result == "delete"

    def test_free_trial_is_delete(self) -> None:
        result = self.categorize("Start your free trial today", "saas@example.com")
        assert result == "delete"

    def test_unknown_defaults_to_review(self) -> None:
        result = self.categorize("Hey, how's it going?", "friend@personal.com")
        assert result == "review"

    def test_plain_subject_is_review(self) -> None:
        result = self.categorize("Meeting notes from yesterday", "team@work.com")
        assert result == "review"

    def test_categorize_uses_sender_too(self) -> None:
        """Sender field with noreply pattern should trigger archive."""
        result = self.categorize("Your order update", "no-reply@store.com")
        assert result == "archive"

    def test_categorize_uses_snippet(self) -> None:
        """Snippet content should be considered for categorization."""
        result = self.categorize(
            "Important update",
            "boss@work.com",
            snippet="Please confirm your attendance at the meeting",
        )
        assert result == "action"


# ---------------------------------------------------------------------------
# Behavioral: age parsing
# ---------------------------------------------------------------------------


class TestAgeParsing:
    """Test the _parse_age function via direct import."""

    @pytest.fixture(autouse=True)
    def _import_module(self) -> None:
        import importlib.util
        from datetime import timedelta

        spec = importlib.util.spec_from_file_location("inbox_cli", CLI_SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.parse_age = mod._parse_age
        self.timedelta = timedelta

    def test_parse_days(self) -> None:
        result = self.parse_age("30d")
        assert result == self.timedelta(days=30)

    def test_parse_hours(self) -> None:
        result = self.parse_age("24h")
        assert result == self.timedelta(hours=24)

    def test_parse_weeks(self) -> None:
        result = self.parse_age("2w")
        assert result == self.timedelta(weeks=2)

    def test_parse_months(self) -> None:
        result = self.parse_age("6m")
        assert result == self.timedelta(days=180)

    def test_parse_single_day(self) -> None:
        result = self.parse_age("1d")
        assert result == self.timedelta(days=1)


# ---------------------------------------------------------------------------
# Behavioral: header decoding
# ---------------------------------------------------------------------------


class TestHeaderDecoding:
    """Test MIME header decoding with real encoded headers."""

    @pytest.fixture(autouse=True)
    def _import_module(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("inbox_cli", CLI_SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.decode_header = mod._decode_header

    def test_plain_ascii_header(self) -> None:
        result = self.decode_header("Hello World")
        assert result == "Hello World"

    def test_none_header(self) -> None:
        result = self.decode_header(None)
        assert result == ""

    def test_empty_header(self) -> None:
        result = self.decode_header("")
        assert result == ""

    def test_utf8_encoded_header(self) -> None:
        """RFC 2047 encoded header should decode properly."""
        encoded = "=?UTF-8?B?SGVsbG8gV29ybGQ=?="
        result = self.decode_header(encoded)
        assert result == "Hello World"

    def test_iso_encoded_header(self) -> None:
        """ISO-8859-1 encoded header."""
        encoded = "=?iso-8859-1?Q?Caf=E9?="
        result = self.decode_header(encoded)
        assert "Caf" in result


# ---------------------------------------------------------------------------
# Behavioral: IMAP message parsing
# ---------------------------------------------------------------------------


class TestIMAPMessageParsing:
    """Test IMAP message parsing with real email bytes."""

    @pytest.fixture(autouse=True)
    def _import_module(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("inbox_cli", CLI_SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.parse_imap_message = mod._parse_imap_message

    def test_parse_basic_email(self) -> None:
        """Parse a basic RFC822 email header."""
        raw = (
            b"From: sender@example.com\r\n"
            b"To: recipient@example.com\r\n"
            b"Subject: Test Email\r\n"
            b"Date: Thu, 26 Feb 2026 10:00:00 +0000\r\n"
            b"Message-ID: <test123@example.com>\r\n"
            b"\r\n"
        )
        result = self.parse_imap_message(raw)
        assert result["subject"] == "Test Email"
        assert result["from"] == "sender@example.com"
        assert result["to"] == "recipient@example.com"
        assert "2026" in result["date"]
        assert "test123" in result["message_id"]

    def test_parse_email_with_display_name(self) -> None:
        raw = (
            b"From: John Doe <john@example.com>\r\n"
            b"To: Jane Doe <jane@example.com>\r\n"
            b"Subject: Meeting tomorrow\r\n"
            b"Date: Thu, 26 Feb 2026 10:00:00 +0000\r\n"
            b"\r\n"
        )
        result = self.parse_imap_message(raw)
        assert "John Doe" in result["from"]
        assert result["subject"] == "Meeting tomorrow"

    def test_parse_email_missing_fields(self) -> None:
        """Email with minimal headers should still parse."""
        raw = b"Subject: Minimal\r\n\r\n"
        result = self.parse_imap_message(raw)
        assert result["subject"] == "Minimal"
        assert result["from"] == ""  # Missing header returns empty


# ---------------------------------------------------------------------------
# Contract: error output shape
# ---------------------------------------------------------------------------


class TestErrorOutputShape:
    """All errors should be JSON on stderr with an 'error' key."""

    def test_gmail_error_is_json(self) -> None:
        result = _run_cli(["gmail-search", "test"])
        assert result.returncode != 0
        data = json.loads(result.stderr)
        assert isinstance(data, dict)
        assert "error" in data
        assert isinstance(data["error"], str)
        assert len(data["error"]) > 0

    def test_yahoo_error_is_json(self) -> None:
        result = _run_cli(["yahoo-search", "test"])
        assert result.returncode != 0
        data = json.loads(result.stderr)
        assert isinstance(data, dict)
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_error_json_has_no_extra_keys(self) -> None:
        """Error output should be a simple {"error": "..."} object."""
        result = _run_cli(["gmail-labels"])
        assert result.returncode != 0
        data = json.loads(result.stderr)
        assert set(data.keys()) == {"error"}


# ---------------------------------------------------------------------------
# Contract: email agent YAML config has correct tool and prompt setup
# ---------------------------------------------------------------------------


class TestAgentDefinition:
    """Verify email agent definition in YAML config and prompt file.

    Agent definitions moved from agents_legacy.py to config/agents/*.yaml.
    These tests read the YAML config and prompt file directly.
    """

    def test_email_agent_has_bash_in_tools(self) -> None:
        """The email agent must have Bash in its builtin tools."""
        import yaml

        config = yaml.safe_load((WORKTREE_ROOT / "config" / "agents" / "email" / "agent.yaml").read_text())
        assert "Bash" in config["tools"]["builtin"]

    def test_email_agent_has_email_tools(self) -> None:
        """The email agent must have the email module enabled."""
        import yaml

        config = yaml.safe_load((WORKTREE_ROOT / "config" / "agents" / "email" / "agent.yaml").read_text())
        assert "email" in config["tools"]["modules"]
        assert config["tools"]["modules"]["email"]["enabled"] is True

    def test_email_agent_description_mentions_yahoo(self) -> None:
        """The email agent description should mention Yahoo or inbox."""
        import yaml

        config = yaml.safe_load((WORKTREE_ROOT / "config" / "agents" / "email" / "agent.yaml").read_text())
        desc = config["description"].lower()
        assert "yahoo" in desc or "inbox" in desc

    def test_email_prompt_has_triage_and_inbox_zero(self) -> None:
        """The email prompt should be a full prompt (not a stub)."""
        prompt = (WORKTREE_ROOT / "corvus" / "prompts" / "email.md").read_text()
        assert "triage" in prompt.lower()
        assert "inbox zero" in prompt.lower()
        assert "archive" in prompt.lower()
        assert "action" in prompt.lower()
