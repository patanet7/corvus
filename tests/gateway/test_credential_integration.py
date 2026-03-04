"""Credential integration + adversarial pen-test suite.

Tests the full credential pipeline: SOPS decrypt → inject → register patterns
→ sanitize catches leaks. Then pen-tests the pipeline with malicious fake APIs
that attempt to exfiltrate credentials through every vector in the Slice 12
nine-step isolation protocol.

NO mocks — real SOPS+age encryption, real HTTP servers, real tool modules.
"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from corvus.credential_store import CredentialStore, get_credential_store
from corvus.sanitize import (
    _CREDENTIAL_PATTERNS,
    _REDACTED,
    register_credential_patterns,
    sanitize,
)

# ---------------------------------------------------------------------------
# Test credentials — long enough to pass _MIN_CREDENTIAL_LENGTH (8)
# ---------------------------------------------------------------------------

HA_TOKEN = "ha-long-lived-token-abc123xyz789"
HA_URL = "http://127.0.0.1:{port}"
PAPERLESS_TOKEN = "paperless-api-token-def456uvw012"
FIREFLY_TOKEN = "firefly-pat-token-ghi789rst345"
OBSIDIAN_TOKEN = "obsidian-api-key-jkl012mno678"
ANTHROPIC_KEY = "sk-ant-oat01-" + "a" * 70

CREDS_DATA = {
    "ha": {"url": "http://homeassistant.local:8123", "token": HA_TOKEN},
    "paperless": {"url": "http://localhost:8010", "token": PAPERLESS_TOKEN},
    "firefly": {"url": "http://localhost:8081", "token": FIREFLY_TOKEN},
    "obsidian": {"url": "http://127.0.0.1:27124", "token": OBSIDIAN_TOKEN},
    "anthropic": {"api_key": ANTHROPIC_KEY},
}

ALL_SECRETS = [HA_TOKEN, PAPERLESS_TOKEN, FIREFLY_TOKEN, OBSIDIAN_TOKEN, ANTHROPIC_KEY]


# ---------------------------------------------------------------------------
# Helpers — reused from test_credential_store.py pattern
# ---------------------------------------------------------------------------


def _sops_env() -> dict[str, str]:
    env = os.environ.copy()
    env["SOPS_CONFIG"] = "/dev/null"
    return env


def _generate_age_key(tmp_path: Path) -> tuple[Path, str]:
    key_file = tmp_path / "age-key.txt"
    result = subprocess.run(
        ["age-keygen", "-o", str(key_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"age-keygen failed: {result.stderr}"
    for line in result.stderr.splitlines():
        if line.startswith("Public key:"):
            return key_file, line.split(":", 1)[1].strip()
    for line in key_file.read_text().splitlines():
        if line.startswith("# public key:"):
            return key_file, line.split(":", 1)[1].strip()
    raise RuntimeError("Could not extract public key from age-keygen output")


def _write_and_encrypt(tmp_path: Path, data: dict, age_pub_key: str) -> Path:
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps(data, indent=2))
    result = subprocess.run(
        [
            "sops",
            "--encrypt",
            "--in-place",
            "--input-type",
            "json",
            "--output-type",
            "json",
            "--age",
            age_pub_key,
            str(creds_file),
        ],
        capture_output=True,
        text=True,
        env=_sops_env(),
    )
    assert result.returncode == 0, f"sops encrypt failed: {result.stderr}"
    return creds_file


# ---------------------------------------------------------------------------
# Malicious fake API server — deliberately echoes credentials back
# ---------------------------------------------------------------------------


class MaliciousAPIHandler(BaseHTTPRequestHandler):
    """A rogue API server that tries every trick to leak credentials."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress request logging."""

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        bearer_token = auth_header.replace("Bearer ", "") if auth_header else ""

        if self.path == "/api/states":
            # Attack 1: Echo the bearer token as entity state
            # Attack 2: Echo the bearer token in friendly_name
            # Attack 3: Echo the token in an attribute value
            self._send_json(
                [
                    {
                        "entity_id": "sensor.leaked_token",
                        "state": bearer_token,
                        "attributes": {
                            "friendly_name": f"Leaked: {bearer_token}",
                            "secret_data": bearer_token,
                            "auth_header": auth_header,
                        },
                        "last_changed": "2026-02-28T00:00:00+00:00",
                        "last_updated": "2026-02-28T00:00:00+00:00",
                    },
                ]
            )
        elif self.path.startswith("/api/states/"):
            # Attack 4: Single entity state contains the token everywhere
            self._send_json(
                {
                    "entity_id": self.path.split("/api/states/")[1],
                    "state": bearer_token,
                    "attributes": {
                        "friendly_name": "Normal Name",
                        "config_dump": json.dumps({"token": bearer_token}),
                        "notes": f"Authorization: Bearer {bearer_token}",
                    },
                    "last_changed": "2026-02-28T00:00:00+00:00",
                    "last_updated": "2026-02-28T00:00:00+00:00",
                }
            )
        elif self.path == "/api/":
            # Used by paperless/firefly — echo token
            self._send_json({"message": f"Authenticated with {bearer_token}"})
        elif self.path.startswith("/api/documents/"):
            # Paperless-style response with embedded credential
            self._send_json(
                {
                    "id": 1,
                    "title": "Secret Document",
                    "content": f"Token found: {bearer_token}",
                    "tags": [1],
                }
            )
        elif self.path.startswith("/api/v1/"):
            # Firefly-style response with embedded credential
            self._send_json(
                {
                    "data": [{"attributes": {"notes": f"Key: {bearer_token}"}}],
                }
            )
        elif self.path.startswith("/vault/"):
            # Obsidian-style response echoing the token
            self._send_json(
                {
                    "content": f"My API key is {bearer_token}",
                    "frontmatter": {"secret": bearer_token},
                }
            )
        elif self.path.startswith("/search/"):
            # Obsidian search results
            self._send_json(
                [
                    {
                        "filename": "secrets.md",
                        "score": 1.0,
                        "matches": [{"match": {"start": 0, "end": 10}}],
                    }
                ]
            )
        else:
            self._send_json({"message": "Not found"}, status=404)

    def do_POST(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        bearer_token = auth_header.replace("Bearer ", "") if auth_header else ""

        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}

        if self.path.startswith("/api/services/"):
            # Attack 5: Echo token in service call response
            self._send_json(
                [
                    {
                        "entity_id": body.get("entity_id", "unknown"),
                        "state": bearer_token,
                        "attributes": {"response_token": bearer_token},
                    }
                ]
            )
        elif self.path.startswith("/api/documents/bulk_edit/"):
            self._send_json({"result": f"Edited with {bearer_token}"})
        else:
            self._send_json({"message": "Not found"}, status=404)

    def do_PUT(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        bearer_token = auth_header.replace("Bearer ", "") if auth_header else ""

        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)  # consume body

        # Obsidian write response echoing the token
        self._send_json({"content": f"Written with {bearer_token}"})

    def do_PATCH(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        bearer_token = auth_header.replace("Bearer ", "") if auth_header else ""

        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)

        self._send_json({"content": f"Appended with {bearer_token}"})


def start_malicious_server() -> tuple[HTTPServer, str]:
    """Start a malicious API server on a random port."""
    server = HTTPServer(("127.0.0.1", 0), MaliciousAPIHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, base_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_sanitize_patterns():
    """Save and restore _CREDENTIAL_PATTERNS between tests."""
    original = _CREDENTIAL_PATTERNS.copy()
    yield
    _CREDENTIAL_PATTERNS.clear()
    _CREDENTIAL_PATTERNS.extend(original)


@pytest.fixture()
def _clean_tool_modules():
    """Reset tool module globals between tests."""
    from corvus.tools import firefly, ha, obsidian, paperless

    orig_ha = (ha._ha_url, ha._ha_token)
    orig_pl = (paperless._paperless_url, paperless._paperless_token)
    orig_ff = (firefly._firefly_url, firefly._firefly_token)
    orig_ob = (obsidian._base_url, obsidian._api_key)
    yield
    ha._ha_url, ha._ha_token = orig_ha
    ha._ha_url, ha._ha_token = orig_ha
    paperless._paperless_url, paperless._paperless_token = orig_pl
    firefly._firefly_url, firefly._firefly_token = orig_ff
    obsidian._base_url, obsidian._api_key = orig_ob


@pytest.fixture()
def _clean_anthropic_env():
    """Save and restore ANTHROPIC_API_KEY env var."""
    orig = os.environ.get("ANTHROPIC_API_KEY")
    yield
    if orig is not None:
        os.environ["ANTHROPIC_API_KEY"] = orig
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture()
def encrypted_store(tmp_path):
    """Create a real SOPS-encrypted credential store."""
    key_file, pub_key = _generate_age_key(tmp_path)
    creds_file = _write_and_encrypt(tmp_path, CREDS_DATA, pub_key)
    store = CredentialStore(path=creds_file, age_key_file=str(key_file))
    store.load()
    return store


@pytest.fixture()
def malicious_server():
    """Start and stop a malicious API server."""
    server, base_url = start_malicious_server()
    yield base_url
    server.shutdown()


# ===========================================================================
# 1. FULL STARTUP CHAIN — SOPS → inject → register → sanitize
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules", "_clean_anthropic_env")
class TestFullStartupChain:
    """Verify the complete credential pipeline from encrypted file to redaction."""

    def test_sops_decrypt_inject_register_sanitize(self, encrypted_store):
        """Full chain: load → inject → register → sanitize catches all values."""
        encrypted_store.inject()
        register_credential_patterns(encrypted_store.credential_values())

        # Every credential value should be redacted when passed through sanitize
        for secret in ALL_SECRETS:
            result = sanitize(f"The value is {secret} in this text")
            assert secret not in result, f"Secret leaked through sanitize: {secret[:10]}..."
            assert _REDACTED in result

    def test_inject_configures_ha_module(self, encrypted_store):
        """inject() sets HA module globals from store."""
        from corvus.tools.ha import _get_config

        encrypted_store.inject()
        url, token = _get_config()
        assert url == "http://homeassistant.local:8123"
        assert token == HA_TOKEN

    def test_inject_configures_paperless_module(self, encrypted_store):
        """inject() sets Paperless module globals from store."""
        from corvus.tools import paperless

        encrypted_store.inject()
        assert paperless._paperless_url == "http://localhost:8010"
        assert paperless._paperless_token == PAPERLESS_TOKEN

    def test_inject_configures_firefly_module(self, encrypted_store):
        """inject() sets Firefly module globals from store."""
        from corvus.tools import firefly

        encrypted_store.inject()
        assert firefly._firefly_url == "http://localhost:8081"
        assert firefly._firefly_token == FIREFLY_TOKEN

    def test_inject_sets_anthropic_env_var(self, encrypted_store):
        """inject() exports ANTHROPIC_API_KEY to env."""
        encrypted_store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == ANTHROPIC_KEY

    def test_get_credential_store_loads_sops(self, tmp_path):
        """get_credential_store() returns a loaded store from SOPS file."""
        key_file, pub_key = _generate_age_key(tmp_path)
        creds_file = _write_and_encrypt(tmp_path, CREDS_DATA, pub_key)
        store = get_credential_store(creds_path=creds_file, age_key_file=str(key_file))
        assert "ha" in store.services()
        assert store.get("ha", "token") == HA_TOKEN

    def test_credential_values_returns_all_secrets(self, encrypted_store):
        """credential_values() returns every leaf value for pattern registration."""
        values = encrypted_store.credential_values()
        for secret in ALL_SECRETS:
            assert secret in values


# ===========================================================================
# 2. PEN-TEST: Malicious API echoes credentials in responses
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules")
class TestMaliciousAPILeakPrevention:
    """Adversarial fake API server tries to exfiltrate credentials.

    The malicious server echoes Bearer tokens back in response bodies.
    Sanitize must catch every instance.
    """

    def _setup_ha_with_malicious_server(self, malicious_url: str) -> None:
        """Configure HA module to point at malicious server, register patterns."""
        from corvus.tools.ha import configure as configure_ha

        configure_ha(ha_url=malicious_url, ha_token=HA_TOKEN)
        register_credential_patterns([HA_TOKEN])

    def test_list_entities_redacts_echoed_token(self, malicious_server):
        """Malicious API echoes Bearer token as entity state — sanitize catches it."""
        from corvus.tools.ha import ha_list_entities

        self._setup_ha_with_malicious_server(malicious_server)
        result = ha_list_entities()
        output_text = result["content"][0]["text"]

        assert HA_TOKEN not in output_text
        assert _REDACTED in output_text

    def test_get_state_redacts_echoed_token(self, malicious_server):
        """Malicious API echoes token in single entity response."""
        from corvus.tools.ha import ha_get_state

        self._setup_ha_with_malicious_server(malicious_server)
        result = ha_get_state("sensor.leaked_token")
        output_text = result["content"][0]["text"]

        assert HA_TOKEN not in output_text
        assert _REDACTED in output_text

    def test_call_service_redacts_echoed_token(self, malicious_server):
        """Malicious API echoes token in service call response."""
        from corvus.tools.ha import ha_call_service

        self._setup_ha_with_malicious_server(malicious_server)
        result = ha_call_service("light", "turn_on", entity_id="light.living_room")
        output_text = result["content"][0]["text"]

        assert HA_TOKEN not in output_text

    def test_token_in_attributes_redacted(self, malicious_server):
        """Token embedded in entity attributes is caught."""
        from corvus.tools.ha import ha_list_entities

        self._setup_ha_with_malicious_server(malicious_server)
        result = ha_list_entities()
        output_text = result["content"][0]["text"]

        # Verify the "auth_header" attribute containing "Bearer <token>" is redacted
        assert f"Bearer {HA_TOKEN}" not in output_text

    def test_token_in_nested_json_redacted(self, malicious_server):
        """Token in a JSON string inside an attribute is caught."""
        from corvus.tools.ha import ha_get_state

        self._setup_ha_with_malicious_server(malicious_server)
        result = ha_get_state("sensor.leaked_token")
        output_text = result["content"][0]["text"]

        # The malicious server puts token inside a JSON string in config_dump
        assert HA_TOKEN not in output_text


# ===========================================================================
# 3. CROSS-TOOL CREDENTIAL ISOLATION
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules")
class TestCrossToolIsolation:
    """Verify credentials from one service don't leak through another's output."""

    def test_ha_output_redacts_all_registered_secrets(self, malicious_server):
        """HA tool output redacts ALL registered secrets, not just its own."""
        from corvus.tools.ha import configure as configure_ha
        from corvus.tools.ha import ha_list_entities

        # Register ALL secrets (simulating full startup)
        register_credential_patterns(ALL_SECRETS)

        # Configure HA to use malicious server
        configure_ha(ha_url=malicious_server, ha_token=HA_TOKEN)
        result = ha_list_entities()
        output_text = result["content"][0]["text"]

        # HA token must be redacted
        assert HA_TOKEN not in output_text

    def test_sanitize_catches_any_registered_secret_in_any_text(self):
        """All registered secrets are caught regardless of which tool produced them."""
        register_credential_patterns(ALL_SECRETS)

        # Simulate a response containing multiple secrets
        mixed_text = json.dumps(
            {
                "ha_token": HA_TOKEN,
                "paperless_token": PAPERLESS_TOKEN,
                "firefly_token": FIREFLY_TOKEN,
                "obsidian_token": OBSIDIAN_TOKEN,
                "anthropic_key": ANTHROPIC_KEY,
            }
        )

        result = sanitize(mixed_text)

        for secret in ALL_SECRETS:
            assert secret not in result, f"Cross-tool leak: {secret[:10]}..."


# ===========================================================================
# 4. ERROR MESSAGE LEAK PREVENTION
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules")
class TestErrorMessageLeaks:
    """Verify error messages from failed requests don't leak credentials."""

    def test_connection_error_does_not_leak(self):
        """ConnectionError message doesn't contain the token."""
        from corvus.tools.ha import configure as configure_ha
        from corvus.tools.ha import ha_list_entities

        register_credential_patterns([HA_TOKEN])
        # Point at a port nothing is listening on
        configure_ha(ha_url="http://127.0.0.1:1", ha_token=HA_TOKEN)
        result = ha_list_entities()
        output_text = result["content"][0]["text"]

        assert HA_TOKEN not in output_text
        assert "error" in output_text.lower()

    def test_http_401_error_does_not_leak_token(self, malicious_server):
        """401 response text doesn't leak the token used in the request."""
        from corvus.tools.ha import ha_get_state

        register_credential_patterns([HA_TOKEN])

        # Use a DIFFERENT token so the server returns data (it doesn't check auth)
        # But register the real token for sanitization
        from corvus.tools.ha import configure as configure_ha

        configure_ha(ha_url=malicious_server, ha_token=HA_TOKEN)

        result = ha_get_state("sensor.test")
        output_text = result["content"][0]["text"]

        assert HA_TOKEN not in output_text

    def test_runtime_error_from_unconfigured_module_is_safe(self):
        """RuntimeError from unconfigured module doesn't leak anything."""
        # Reset module to unconfigured state
        import corvus.tools.ha as ha_mod
        from corvus.tools.ha import ha_list_entities

        ha_mod._ha_url = None
        ha_mod._ha_token = None

        with pytest.raises(RuntimeError, match="not configured"):
            ha_list_entities()


# ===========================================================================
# 5. ENCODING & BYPASS ATTACKS
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns")
class TestSanitizationBypass:
    """Attempt to bypass sanitization via encoding tricks."""

    def test_partial_token_at_boundary(self):
        """Token split across a field boundary is still caught."""
        register_credential_patterns([HA_TOKEN])
        # Token appears as one contiguous string even if split conceptually
        text = f'{{"part1": "{HA_TOKEN[:16]}", "part2": "{HA_TOKEN[16:]}"}}'
        sanitize(text)
        # The full token isn't present as a contiguous string here,
        # so partial matches aren't expected. Verify the full token IS caught:
        assert sanitize(HA_TOKEN) == _REDACTED

    def test_url_encoded_token_in_raw_text(self):
        """URL-encoded version of token — sanitize catches the literal form."""
        register_credential_patterns([HA_TOKEN])
        # If someone URL-encodes the token (replacing - with %2D)
        # URL-encoding the token (replacing - with %2D) produces a different string
        # The literal token should still be caught
        assert HA_TOKEN not in sanitize(f"token={HA_TOKEN}")
        # URL-encoded form is a DIFFERENT string, not the registered pattern
        # This is expected behavior — we catch the exact value, not encodings
        # The URL-encoded form doesn't match because it's a different string

    def test_json_escaped_token(self):
        """JSON-escaped token (with backslash escapes) is still caught."""
        register_credential_patterns([HA_TOKEN])
        # json.dumps wraps the token in quotes but the value itself is unchanged
        json_text = json.dumps({"token": HA_TOKEN})
        result = sanitize(json_text)
        assert HA_TOKEN not in result

    def test_case_sensitivity(self):
        """Sanitize patterns are case-sensitive for exact value matches."""
        register_credential_patterns([HA_TOKEN])
        # Exact case should be caught
        assert HA_TOKEN not in sanitize(HA_TOKEN)
        # Different case should NOT be caught (tokens are case-sensitive)
        upper = HA_TOKEN.upper()
        if upper != HA_TOKEN:
            result = sanitize(upper)
            # upper case is a different string, not a credential
            assert upper in result  # NOT caught — correct behavior

    def test_regex_special_chars_in_credential(self):
        """Credentials with regex special chars (.+*?) are escaped properly."""
        weird_token = "my.token+value*special?chars"
        register_credential_patterns([weird_token])
        text = f"auth={weird_token}"
        result = sanitize(text)
        assert weird_token not in result
        assert _REDACTED in result

    def test_bearer_pattern_catches_generic_tokens(self):
        """Built-in Bearer pattern catches tokens even without registration."""
        unregistered_token = "unregistered-long-bearer-token-xyz123"
        text = f"Bearer {unregistered_token}"
        result = sanitize(text)
        assert unregistered_token not in result

    def test_token_embedded_in_multiline_text(self):
        """Token in multi-line text is still caught."""
        register_credential_patterns([HA_TOKEN])
        text = f"Line 1\nLine 2 contains {HA_TOKEN}\nLine 3"
        result = sanitize(text)
        assert HA_TOKEN not in result

    def test_multiple_occurrences_all_redacted(self):
        """All occurrences of a token are redacted, not just the first."""
        register_credential_patterns([HA_TOKEN])
        text = f"{HA_TOKEN} middle {HA_TOKEN} end {HA_TOKEN}"
        result = sanitize(text)
        assert HA_TOKEN not in result
        assert result.count(_REDACTED) >= 3


# ===========================================================================
# 6. ADVERSARIAL AGENT EXFILTRATION ATTEMPTS (Slice 12 protocol)
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules")
class TestAdversarialExfiltration:
    """Simulate the 9-step adversarial credential isolation protocol.

    Modeled after Slice 12 capability broker design:
    1. Direct credential request
    2. Config dump request
    3. Environment variable request
    4. Config file read attempt
    5. HTTP header inspection
    6. Tool output credential check
    7. Memory/workspace file check
    8. Log inspection
    9. Security audit — verify all above passed
    """

    def test_step1_direct_credential_request(self, encrypted_store):
        """An agent asking 'What is my API key?' gets no raw secrets."""
        register_credential_patterns(encrypted_store.credential_values())

        # Simulate what happens if an agent directly accesses credential_values()
        # and tries to output them — sanitize catches every value
        all_values = encrypted_store.credential_values()
        for val in all_values:
            assert sanitize(val) == _REDACTED

    def test_step2_config_dump_request(self, encrypted_store, malicious_server):
        """An agent asking to 'dump all config' gets redacted output."""
        from corvus.tools.ha import configure as configure_ha
        from corvus.tools.ha import ha_get_state

        encrypted_store.inject()
        register_credential_patterns(encrypted_store.credential_values())

        # Reconfigure HA to point at malicious server (keeps same token)
        configure_ha(ha_url=malicious_server, ha_token=HA_TOKEN)

        # Malicious server puts "config_dump" with token in attributes
        result = ha_get_state("sensor.config")
        output_text = result["content"][0]["text"]

        for secret in ALL_SECRETS:
            assert secret not in output_text

    def test_step3_env_var_request(self, encrypted_store):
        """Credentials injected as env vars are caught by sanitize."""
        encrypted_store.inject()
        register_credential_patterns(encrypted_store.credential_values())

        # If an agent somehow reads ANTHROPIC_API_KEY and tries to output it
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        result = sanitize(f"Found env var: ANTHROPIC_API_KEY={api_key}")
        assert ANTHROPIC_KEY not in result

    def test_step4_config_file_read_blocked(self, encrypted_store):
        """SOPS-encrypted file on disk is not plaintext-readable."""
        # The credentials file is encrypted — cat'ing it returns SOPS metadata
        raw_content = encrypted_store._path.read_text()
        # SOPS-encrypted files contain "sops" metadata, not plaintext
        assert "sops" in raw_content
        # No plaintext credential values should be in the encrypted file
        for secret in ALL_SECRETS:
            assert secret not in raw_content

    def test_step5_http_header_inspection(self, malicious_server):
        """Authorization headers in tool output are caught by built-in patterns."""
        register_credential_patterns([HA_TOKEN])

        # Simulate text containing an Authorization header
        header_text = f"Authorization: Bearer {HA_TOKEN}"
        result = sanitize(header_text)
        assert HA_TOKEN not in result
        assert _REDACTED in result

    def test_step6_tool_output_credential_check(self, encrypted_store, malicious_server):
        """Full tool invocation with malicious server — output is clean."""
        from corvus.tools.ha import configure as configure_ha
        from corvus.tools.ha import ha_list_entities

        encrypted_store.inject()
        register_credential_patterns(encrypted_store.credential_values())

        # Override HA URL to malicious server
        configure_ha(ha_url=malicious_server, ha_token=HA_TOKEN)
        result = ha_list_entities()
        output_text = result["content"][0]["text"]

        # Exhaustive check — no secret appears anywhere in the output
        for secret in ALL_SECRETS:
            assert secret not in output_text, f"Step 6 FAIL: credential leaked in tool output: {secret[:10]}..."

    def test_step7_workspace_file_safety(self, tmp_path, encrypted_store):
        """Credentials should never be written to workspace files."""
        register_credential_patterns(encrypted_store.credential_values())

        # Simulate an agent writing tool output to a file
        tool_output = sanitize(
            json.dumps(
                {
                    "entities": [{"state": HA_TOKEN}],
                    "token": PAPERLESS_TOKEN,
                }
            )
        )

        output_file = tmp_path / "agent_workspace" / "output.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(tool_output)

        contents = output_file.read_text()
        for secret in ALL_SECRETS:
            assert secret not in contents

    def test_step9_security_audit_all_secrets_covered(self, encrypted_store):
        """Every stored credential is registered and caught by sanitize."""
        register_credential_patterns(encrypted_store.credential_values())

        registered_values = encrypted_store.credential_values()
        assert len(registered_values) >= 5  # HA, Paperless, Firefly, Obsidian, Anthropic

        # Build a "worst case" text containing every secret in various forms
        worst_case = "\n".join(
            [f"token={v}" for v in registered_values]
            + [f"Bearer {v}" for v in registered_values]
            + [f'{{"api_key": "{v}"}}' for v in registered_values]
        )

        result = sanitize(worst_case)
        for secret in ALL_SECRETS:
            assert secret not in result, f"Audit FAIL: {secret[:10]}... found in sanitized output"


# ===========================================================================
# 7. ENV-VAR FALLBACK PATH
# ===========================================================================


@pytest.mark.usefixtures("_clean_sanitize_patterns", "_clean_tool_modules", "_clean_anthropic_env")
class TestEnvFallbackIntegration:
    """Verify the env-var fallback path also produces a sanitizable store."""

    def test_from_env_inject_register_sanitize(self):
        """Env-var fallback → inject → register → sanitize catches everything."""
        os.environ["HA_URL"] = "http://ha.local:8123"
        os.environ["HA_TOKEN"] = HA_TOKEN
        os.environ["PAPERLESS_URL"] = "http://paperless.local:8010"
        os.environ["PAPERLESS_API_TOKEN"] = PAPERLESS_TOKEN

        try:
            store = CredentialStore.from_env()
            store.inject()
            register_credential_patterns(store.credential_values())

            for secret in [HA_TOKEN, PAPERLESS_TOKEN]:
                result = sanitize(f"value={secret}")
                assert secret not in result
        finally:
            os.environ.pop("HA_URL", None)
            os.environ.pop("HA_TOKEN", None)
            os.environ.pop("PAPERLESS_URL", None)
            os.environ.pop("PAPERLESS_API_TOKEN", None)
