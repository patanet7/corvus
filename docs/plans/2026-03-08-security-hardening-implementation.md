# Security Hardening & MCP Stdio Executor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remediate all 15 security audit findings and replace the Bash-based tool system with an in-process MCP stdio executor, three-tier permission model, and ToolContext credential injection.

**Architecture:** Corvus parent process serves as MCP stdio server (via `create_sdk_mcp_server`). Tools are native MCP tools with typed schemas. Credentials injected via `ToolContext` — never exposed as env vars. Policy engine composes `permissions.deny` dynamically per agent per tier. Break-glass requires Argon2id password + HMAC-SHA256 session token.

**Tech Stack:** Python 3.11+, claude-agent-sdk (`create_sdk_mcp_server`), argon2-cffi, FastAPI, pydantic

**Design Doc:** `docs/plans/2026-03-08-security-hardening-executor-design.md`

---

## Phase 1: Critical Security Fixes (F-001, F-002, F-007, F-003)

These are independent of the MCP executor and can ship immediately.

---

### Task 1: Remove CORVUS_BREAK_GLASS env var bypass (F-002)

**Files:**
- Modify: `corvus/config.py:41`
- Modify: `corvus/gateway/options.py:157,254-255`
- Test: `tests/unit/test_break_glass_env_removal.py`

**Step 1: Write the failing test**

Create `tests/unit/test_break_glass_env_removal.py`:

```python
"""Verify CORVUS_BREAK_GLASS env var no longer grants break-glass access."""

import os

import pytest


class TestBreakGlassEnvRemoval:
    def test_config_has_no_break_glass_mode(self):
        """config.py should not export BREAK_GLASS_MODE."""
        from corvus import config

        assert not hasattr(config, "BREAK_GLASS_MODE")

    def test_env_var_has_no_effect(self):
        """Setting CORVUS_BREAK_GLASS env var must not bypass security."""
        os.environ["CORVUS_BREAK_GLASS"] = "1"
        try:
            # Re-import to test module-level evaluation
            import importlib

            from corvus import config

            importlib.reload(config)
            assert not hasattr(config, "BREAK_GLASS_MODE")
        finally:
            os.environ.pop("CORVUS_BREAK_GLASS", None)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_break_glass_env_removal.py -v`
Expected: FAIL — `BREAK_GLASS_MODE` still exists in config.py

**Step 3: Remove BREAK_GLASS_MODE from config.py**

In `corvus/config.py`, delete line 41:
```python
BREAK_GLASS_MODE = os.environ.get("CORVUS_BREAK_GLASS", "").lower() in {"1", "true", "yes", "on"}
```

**Step 4: Remove all BREAK_GLASS_MODE references from options.py**

In `corvus/gateway/options.py`:

- Line ~10: Remove `from corvus.config import ... BREAK_GLASS_MODE ...` (remove just BREAK_GLASS_MODE from the import)
- Line ~157: Change `allow_secret_access or BREAK_GLASS_MODE` → `allow_secret_access`
- Lines ~254-255: In `_resolve_permission_mode()`, remove `if BREAK_GLASS_MODE:` block that returns `"bypassPermissions"`

**Step 5: Fix any other BREAK_GLASS_MODE references**

Run: `rg "BREAK_GLASS_MODE" --type py` and fix all remaining references.

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_break_glass_env_removal.py -v`
Expected: PASS

**Step 7: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_break_glass_env_removal_results.log`
Expected: All tests pass

**Step 8: Commit**

```bash
git add -A && git commit -m "security: remove CORVUS_BREAK_GLASS env var bypass (F-002)

Break-glass mode must only be activated via Argon2id password
verification through BreakGlassSessionRegistry, never via env var."
```

---

### Task 2: Fix confirm queue fallthrough to deny-default (F-007)

**Files:**
- Modify: `corvus/gateway/options.py:339-340`
- Test: `tests/unit/test_confirm_queue_deny_default.py`

**Step 1: Write the failing test**

Create `tests/unit/test_confirm_queue_deny_default.py`:

```python
"""Verify confirm-gated tools are denied when no confirm queue is available."""

import asyncio

from corvus.gateway.permissions import PermissionDecision


class TestConfirmQueueDenyDefault:
    def test_no_confirm_queue_denies(self):
        """When confirm_queue is None and tool is confirm-gated, result must be deny."""
        from corvus.gateway.options import _build_can_use_tool

        # Build a can_use_tool callback with no confirm_queue, no break-glass
        can_use_tool = _build_can_use_tool(
            spec=_make_spec_with_confirm_gated(["test.write"]),
            ws_callback=None,
            confirm_queue=None,
            allow_secret_access=False,
        )

        result = asyncio.get_event_loop().run_until_complete(
            can_use_tool("test.write", {})
        )

        # Must be denied, not allowed
        from claude_agent_sdk import PermissionResultDeny

        assert isinstance(result, PermissionResultDeny)

    def test_with_confirm_queue_and_approval_allows(self):
        """When confirm_queue is present and user approves, result is allow."""
        # This test verifies the happy path still works
        pass  # Placeholder — existing tests cover this path
```

Note: The exact test setup depends on how `_build_can_use_tool` is structured. The test must verify that when `confirm_queue is None` and the tool is confirm-gated, the result is `PermissionResultDeny`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_confirm_queue_deny_default.py -v`
Expected: FAIL — current code returns `PermissionResultAllow()`

**Step 3: Fix the fallthrough**

In `corvus/gateway/options.py`, change lines 339-340:

```python
# BEFORE (vulnerable):
# No confirm queue — fall through to allow (break-glass / no WS)
return PermissionResultAllow()

# AFTER (secure):
# No confirm queue — deny by default. Break-glass is handled
# by the allow_secret_access check earlier in the flow.
return PermissionResultDeny(
    message=f"Tool '{tool_name}' requires confirmation but no confirm queue is available.",
    interrupt=False,
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_confirm_queue_deny_default.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_confirm_deny_default_results.log`
Expected: All tests pass (some tests may need updates if they relied on the auto-allow behavior)

**Step 6: Commit**

```bash
git add -A && git commit -m "security: confirm queue fallthrough denies by default (F-007/SEC-003)

Confirm-gated tools without a confirm queue are now denied instead
of silently allowed. Break-glass sessions bypass via allow_secret_access."
```

---

### Task 3: Enforce break-glass TTL cap (F-006)

**Files:**
- Modify: `corvus/gateway/control_plane.py:115-116`
- Test: `tests/unit/test_break_glass_ttl_cap.py`

**Step 1: Write the failing test**

Create `tests/unit/test_break_glass_ttl_cap.py`:

```python
"""Verify break-glass sessions enforce a maximum TTL."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from corvus.break_glass import BreakGlassManager
from corvus.gateway.control_plane import BreakGlassSessionRegistry


class TestBreakGlassTTLCap:
    def _make_registry(self, max_ttl_minutes: int = 240) -> BreakGlassSessionRegistry:
        tmp = tempfile.mkdtemp()
        mgr = BreakGlassManager(data_dir=Path(tmp))
        mgr.set_passphrase("test-passphrase")
        return BreakGlassSessionRegistry(
            mgr, default_ttl_minutes=30, max_ttl_minutes=max_ttl_minutes
        )

    def test_ttl_capped_at_max(self):
        reg = self._make_registry(max_ttl_minutes=240)
        ok, expires_at = reg.activate(
            user="alice",
            session_id="s1",
            passphrase="test-passphrase",
            ttl_minutes=9999,  # Requesting absurd TTL
        )
        assert ok
        # Should be capped at 240 minutes, not 9999
        max_allowed = datetime.now(UTC) + timedelta(minutes=241)
        assert expires_at < max_allowed

    def test_ttl_within_cap_unchanged(self):
        reg = self._make_registry(max_ttl_minutes=240)
        ok, expires_at = reg.activate(
            user="alice",
            session_id="s2",
            passphrase="test-passphrase",
            ttl_minutes=60,
        )
        assert ok
        # Should be ~60 minutes from now
        expected_min = datetime.now(UTC) + timedelta(minutes=59)
        expected_max = datetime.now(UTC) + timedelta(minutes=61)
        assert expected_min < expires_at < expected_max
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_break_glass_ttl_cap.py -v`
Expected: FAIL — `BreakGlassSessionRegistry.__init__` does not accept `max_ttl_minutes`

**Step 3: Add max_ttl_minutes to BreakGlassSessionRegistry**

In `corvus/gateway/control_plane.py`, modify `BreakGlassSessionRegistry`:

```python
class BreakGlassSessionRegistry:
    def __init__(
        self,
        manager: BreakGlassManager,
        *,
        default_ttl_minutes: int = 30,
        max_ttl_minutes: int = 240,
    ) -> None:
        self._manager = manager
        self._default_ttl_minutes = max(1, default_ttl_minutes)
        self._max_ttl_minutes = max(1, max_ttl_minutes)
        self._lock = RLock()
        self._active_until: dict[tuple[str, str], datetime] = {}

    def activate(self, *, user, session_id, passphrase, ttl_minutes=None):
        if not self._manager.verify_passphrase(passphrase):
            return False, None
        minutes = ttl_minutes if ttl_minutes is not None else self._default_ttl_minutes
        minutes = min(max(1, minutes), self._max_ttl_minutes)  # CAP TTL
        expires_at = datetime.now(UTC) + timedelta(minutes=minutes)
        with self._lock:
            self._active_until[(user, session_id)] = expires_at
        return True, expires_at
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_break_glass_ttl_cap.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_break_glass_ttl_cap_results.log`
Expected: All tests pass

**Step 6: Commit**

```bash
git add -A && git commit -m "security: enforce max TTL cap on break-glass sessions (F-006)

Prevents indefinite break-glass sessions by capping requested TTL
at max_ttl_minutes (default 240min/4h). Configurable per deployment."
```

---

### Task 4: Add `_ALLOWED_ENV` whitelist for CLI subprocess (F-001)

**Files:**
- Modify: `corvus/cli/chat.py` (replace `_prepare_isolated_env` env construction)
- Test: `tests/unit/test_env_whitelist.py`

**Step 1: Write the failing test**

Create `tests/unit/test_env_whitelist.py`:

```python
"""Verify CLI subprocess environment uses allowlist, not full inheritance."""

import os


class TestEnvWhitelist:
    def test_sensitive_vars_not_in_env(self):
        """Sensitive env vars must not appear in the prepared environment."""
        # Set some sensitive vars
        os.environ["HA_TOKEN"] = "secret-ha-token"
        os.environ["PAPERLESS_API_TOKEN"] = "secret-paperless"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-secret"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "aws-secret"

        try:
            from corvus.cli.chat import _build_subprocess_env

            env = _build_subprocess_env()

            # None of these should be present
            assert "HA_TOKEN" not in env
            assert "PAPERLESS_API_TOKEN" not in env
            assert "ANTHROPIC_API_KEY" not in env
            assert "AWS_SECRET_ACCESS_KEY" not in env
            assert "CORVUS_BREAK_GLASS" not in env
        finally:
            for key in ["HA_TOKEN", "PAPERLESS_API_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY"]:
                os.environ.pop(key, None)

    def test_allowed_vars_present(self):
        """Allowed vars must be present in the prepared environment."""
        from corvus.cli.chat import _build_subprocess_env

        env = _build_subprocess_env()

        assert "PATH" in env
        assert "HOME" in env
        assert "SHELL" in env

    def test_tmpdir_included(self):
        """TMPDIR must be included (macOS requires it)."""
        os.environ["TMPDIR"] = "/tmp/test"
        try:
            from corvus.cli.chat import _build_subprocess_env

            env = _build_subprocess_env()
            assert env.get("TMPDIR") == "/tmp/test"
        finally:
            os.environ.pop("TMPDIR", None)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_env_whitelist.py -v`
Expected: FAIL — `_build_subprocess_env` does not exist yet

**Step 3: Implement `_build_subprocess_env` in chat.py**

Add to `corvus/cli/chat.py`:

```python
_ALLOWED_ENV = frozenset({
    "PATH", "HOME", "SHELL", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "USER", "LOGNAME",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR", "XDG_STATE_HOME",
})


def _build_subprocess_env(
    *,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal environment for the Claude CLI subprocess.

    Only explicitly allowed vars from the parent process plus any
    extra vars (like ANTHROPIC_BASE_URL when LiteLLM is running)
    are included. Credentials NEVER leak via environment.
    """
    env: dict[str, str] = {}
    for key in _ALLOWED_ENV:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if extra:
        env.update(extra)
    return env
```

Then update `_prepare_isolated_env` to use `_build_subprocess_env()` instead of `dict(os.environ)`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_env_whitelist.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_env_whitelist_results.log`
Expected: All tests pass

**Step 6: Commit**

```bash
git add -A && git commit -m "security: replace env blocklist with strict allowlist (F-001)

CLI subprocess now gets only PATH, HOME, SHELL, TERM, LANG, TMPDIR,
XDG dirs. All credentials flow through ToolContext in-process, never
via environment variables to the subprocess."
```

---

### Task 5: Add snapshot ignore entries as interim fix (F-009)

**Files:**
- Modify: `corvus/gateway/workspace_runtime.py` (`_SNAPSHOT_IGNORE`)
- Test: `tests/unit/test_snapshot_ignore.py`

**Step 1: Write the failing test**

Create `tests/unit/test_snapshot_ignore.py`:

```python
"""Verify workspace snapshot ignores sensitive files."""

from corvus.gateway.workspace_runtime import _SNAPSHOT_IGNORE


class TestSnapshotIgnore:
    def test_env_files_ignored(self):
        assert ".env" in _SNAPSHOT_IGNORE

    def test_config_dir_ignored(self):
        assert "config/" in _SNAPSHOT_IGNORE or "config" in _SNAPSHOT_IGNORE

    def test_hash_files_ignored(self):
        assert any("hash" in entry or "*.hash" in entry for entry in _SNAPSHOT_IGNORE)

    def test_claude_md_ignored(self):
        assert "CLAUDE.md" in _SNAPSHOT_IGNORE
```

**Step 2: Run test, verify fail, then add missing entries to `_SNAPSHOT_IGNORE`**

In `corvus/gateway/workspace_runtime.py`, add to `_SNAPSHOT_IGNORE`:
```python
".env", ".env.*", "config/", ".corvus/", "CLAUDE.md",
"passphrase.hash", "lockout.json", "*.hash",
```

**Step 3: Run test to verify pass, then full suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_snapshot_ignore_results.log`

**Step 4: Commit**

```bash
git add -A && git commit -m "security: add sensitive files to workspace snapshot ignore (F-009)

Blocks .env, config/, CLAUDE.md, *.hash, and .corvus/ from being
copied into agent workspaces. Interim fix until purpose-built
workspaces replace snapshots entirely."
```

---

### Task 6: Wire parent_allows_* to agent spec (F-005)

**Files:**
- Modify: `corvus/gateway/acp_executor.py:118-120`
- Modify: `corvus/agents/spec.py` (add permission_tier to AgentToolConfig)
- Test: `tests/unit/test_parent_allows_wiring.py`

**Step 1: Write the failing test**

Create `tests/unit/test_parent_allows_wiring.py`:

```python
"""Verify parent_allows_* flags are derived from agent spec, not hardcoded."""

from corvus.agents.spec import AgentSpec, AgentToolConfig


class TestParentAllowsWiring:
    def test_agent_without_bash_gets_bash_denied(self):
        """Agent without Bash in builtins should have parent_allows_bash=False."""
        spec = AgentSpec(
            name="test",
            description="test agent",
            tools=AgentToolConfig(builtin=["Read", "Grep"]),  # No Bash
        )
        allows = _resolve_parent_allows(spec)
        assert allows["bash"] is False
        assert allows["read"] is True

    def test_agent_with_bash_gets_bash_allowed(self):
        spec = AgentSpec(
            name="test",
            description="test agent",
            tools=AgentToolConfig(builtin=["Bash", "Read"]),
        )
        allows = _resolve_parent_allows(spec)
        assert allows["bash"] is True

    def test_strict_tier_denies_all(self):
        spec = AgentSpec(
            name="test",
            description="test agent",
            tools=AgentToolConfig(builtin=["Bash", "Read"]),
            metadata={"permission_tier": "strict"},
        )
        allows = _resolve_parent_allows(spec)
        # strict tier: only explicitly allowed tools
        assert allows["bash"] is True  # declared in builtins
        assert allows["read"] is True
        assert allows["write"] is False  # not declared
```

Note: `_resolve_parent_allows` is a new helper function to extract from the spec.

**Step 2: Implement `_resolve_parent_allows` and wire into acp_executor**

Add helper in `corvus/gateway/acp_executor.py`:

```python
def _resolve_parent_allows(spec: AgentSpec) -> dict[str, bool]:
    builtins = {b.lower() for b in spec.tools.builtin}
    return {
        "read": "read" in builtins,
        "write": "write" in builtins or "edit" in builtins,
        "bash": "bash" in builtins,
    }
```

Replace lines 118-120:
```python
allows = _resolve_parent_allows(spec)
parent_allows_read = allows["read"]
parent_allows_write = allows["write"]
parent_allows_bash = allows["bash"]
```

**Step 3: Run tests, full suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_parent_allows_results.log`

**Step 4: Commit**

```bash
git add -A && git commit -m "security: wire parent_allows to agent spec builtins (F-005)

parent_allows_read/write/bash now derived from agent YAML builtins
list instead of being hardcoded to True. Agents only get the
capabilities they declare."
```

---

## Phase 2: Policy Engine & ToolContext Foundation

---

### Task 7: Add `permission_tier` and `extra_deny` to AgentToolConfig

**Files:**
- Modify: `corvus/agents/spec.py:52-59`
- Modify: `config/agents/*/agent.yaml` (add permission_tier to each)
- Test: `tests/unit/test_agent_spec_policy_fields.py`

**Step 1: Write the failing test**

```python
"""Verify AgentToolConfig supports permission_tier and extra_deny fields."""

from corvus.agents.spec import AgentToolConfig


class TestAgentToolConfigPolicyFields:
    def test_permission_tier_default(self):
        cfg = AgentToolConfig()
        assert cfg.permission_tier == "default"

    def test_permission_tier_from_yaml(self):
        cfg = AgentToolConfig(permission_tier="strict")
        assert cfg.permission_tier == "strict"

    def test_extra_deny_default_empty(self):
        cfg = AgentToolConfig()
        assert cfg.extra_deny == []

    def test_extra_deny_from_yaml(self):
        cfg = AgentToolConfig(extra_deny=["ha.restart_*"])
        assert cfg.extra_deny == ["ha.restart_*"]

    def test_invalid_permission_tier_raises(self):
        import pytest

        with pytest.raises(ValueError):
            AgentToolConfig(permission_tier="invalid")
```

**Step 2: Add fields to AgentToolConfig**

In `corvus/agents/spec.py`:

```python
@dataclass
class AgentToolConfig:
    builtin: list[str] = field(default_factory=list)
    modules: dict[str, dict] = field(default_factory=dict)
    confirm_gated: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
    permission_tier: str = "default"
    extra_deny: list[str] = field(default_factory=list)

    def __post_init__(self):
        valid_tiers = {"strict", "default", "break_glass"}
        if self.permission_tier not in valid_tiers:
            raise ValueError(
                f"permission_tier must be one of {sorted(valid_tiers)}, "
                f"got {self.permission_tier!r}"
            )
```

**Step 3: Add `permission_tier: default` to all agent YAMLs that don't have one**

**Step 4: Run tests, commit**

```bash
git add -A && git commit -m "feat: add permission_tier and extra_deny to AgentToolConfig"
```

---

### Task 8: Create policy.yaml and PolicyEngine

**Files:**
- Create: `config/policy.yaml`
- Create: `corvus/security/policy.py`
- Test: `tests/unit/test_policy_engine.py`

**Step 1: Write the failing test**

```python
"""Verify PolicyEngine loads policy.yaml and composes deny lists."""

import tempfile
from pathlib import Path

import yaml

from corvus.security.policy import PolicyEngine


class TestPolicyEngine:
    def _write_policy(self, tmp: str, data: dict) -> Path:
        p = Path(tmp) / "policy.yaml"
        p.write_text(yaml.dump(data))
        return p

    def test_global_deny_always_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_policy(tmp, {
                "global_deny": ["*.env*", "*.ssh/*"],
                "tiers": {"default": {"mode": "allowlist_with_baseline", "confirm_default": "deny"}},
            })
            engine = PolicyEngine.from_yaml(path)
            deny_list = engine.compose_deny_list(tier="default", extra_deny=[])
            assert "*.env*" in deny_list
            assert "*.ssh/*" in deny_list

    def test_extra_deny_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_policy(tmp, {
                "global_deny": ["*.env*"],
                "tiers": {"default": {"mode": "allowlist_with_baseline", "confirm_default": "deny"}},
            })
            engine = PolicyEngine.from_yaml(path)
            deny_list = engine.compose_deny_list(tier="default", extra_deny=["ha.restart_*"])
            assert "*.env*" in deny_list
            assert "ha.restart_*" in deny_list

    def test_break_glass_tier_still_has_global_deny(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_policy(tmp, {
                "global_deny": ["*.env*"],
                "tiers": {"break_glass": {"mode": "allow_all", "confirm_default": "allow"}},
            })
            engine = PolicyEngine.from_yaml(path)
            deny_list = engine.compose_deny_list(tier="break_glass", extra_deny=[])
            assert "*.env*" in deny_list  # global_deny applies even in break-glass

    def test_confirm_default_for_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_policy(tmp, {
                "global_deny": [],
                "tiers": {
                    "default": {"mode": "allowlist_with_baseline", "confirm_default": "deny"},
                    "break_glass": {"mode": "allow_all", "confirm_default": "allow"},
                },
            })
            engine = PolicyEngine.from_yaml(path)
            assert engine.confirm_default("default") == "deny"
            assert engine.confirm_default("break_glass") == "allow"
```

**Step 2: Implement PolicyEngine**

Create `corvus/security/__init__.py` (empty) and `corvus/security/policy.py`:

```python
"""Policy engine — loads policy.yaml and composes permission deny lists."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TierConfig:
    mode: str
    confirm_default: str


@dataclass
class PolicyEngine:
    global_deny: list[str] = field(default_factory=list)
    tiers: dict[str, TierConfig] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> PolicyEngine:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        tiers = {}
        for name, cfg in data.get("tiers", {}).items():
            tiers[name] = TierConfig(
                mode=cfg.get("mode", "allowlist_with_baseline"),
                confirm_default=cfg.get("confirm_default", "deny"),
            )
        return cls(
            global_deny=data.get("global_deny", []),
            tiers=tiers,
        )

    def compose_deny_list(
        self,
        tier: str,
        extra_deny: list[str],
    ) -> list[str]:
        deny = list(self.global_deny)
        deny.extend(extra_deny)
        return sorted(set(deny))

    def confirm_default(self, tier: str) -> str:
        tc = self.tiers.get(tier)
        return tc.confirm_default if tc else "deny"
```

**Step 3: Create config/policy.yaml**

```yaml
global_deny:
  - "*.env*"
  - "*.ssh/*"
  - "*credentials*"
  - "*/secrets/*"
  - "*.pem"
  - "*.key"
  - "*passphrase*"

tiers:
  strict:
    mode: allowlist
    confirm_default: deny

  default:
    mode: allowlist_with_baseline
    confirm_default: deny

  break_glass:
    mode: allow_all
    confirm_default: allow
    requires_auth: true
    token_ttl: 3600
    max_ttl: 14400
```

**Step 4: Run tests, commit**

```bash
git add -A && git commit -m "feat: add PolicyEngine and global policy.yaml

Three-tier permission model (strict/default/break_glass) with
global deny list. Policy composes deny lists from global + extra_deny."
```

---

### Task 9: Create ToolContext and ToolPermissions

**Files:**
- Create: `corvus/security/tool_context.py`
- Test: `tests/unit/test_tool_context.py`

**Step 1: Write the failing test**

```python
"""Verify ToolContext credential isolation and permission checking."""

import pytest

from corvus.security.tool_context import ToolContext, ToolPermissions, PermissionTier


class TestToolContext:
    def test_credentials_only_declared_deps(self):
        ctx = ToolContext(
            agent_name="homelab",
            session_id="s1",
            permission_tier=PermissionTier.DEFAULT,
            credentials={"HA_URL": "http://ha", "HA_TOKEN": "secret"},
            permissions=ToolPermissions(deny=[], confirm_gated=[]),
            break_glass_token=None,
        )
        assert ctx.credentials["HA_URL"] == "http://ha"
        assert ctx.credentials["HA_TOKEN"] == "secret"

    def test_is_denied(self):
        perms = ToolPermissions(deny=["ha.restart_*", "*.env*"], confirm_gated=[])
        assert perms.is_denied("ha.restart_all") is True
        assert perms.is_denied("ha.call_service") is False
        assert perms.is_denied("read.env.local") is True

    def test_is_confirm_gated(self):
        perms = ToolPermissions(deny=[], confirm_gated=["ha.call_service", "obsidian.write"])
        assert perms.is_confirm_gated("ha.call_service") is True
        assert perms.is_confirm_gated("ha.get_states") is False
```

**Step 2: Implement**

Create `corvus/security/tool_context.py`:

```python
"""ToolContext — runtime security context passed to every tool handler."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum


class PermissionTier(str, Enum):
    STRICT = "strict"
    DEFAULT = "default"
    BREAK_GLASS = "break_glass"


@dataclass
class ToolPermissions:
    deny: list[str] = field(default_factory=list)
    confirm_gated: list[str] = field(default_factory=list)

    def is_denied(self, tool_name: str) -> bool:
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in self.deny)

    def is_confirm_gated(self, tool_name: str) -> bool:
        return tool_name in self.confirm_gated


@dataclass
class ToolContext:
    agent_name: str
    session_id: str
    permission_tier: PermissionTier
    credentials: dict[str, str]
    permissions: ToolPermissions
    break_glass_token: str | None = None
```

**Step 3: Run tests, commit**

```bash
git add -A && git commit -m "feat: add ToolContext and ToolPermissions for credential isolation

ToolContext carries pre-resolved credentials and permission state.
ToolPermissions supports fnmatch deny patterns and confirm gating."
```

---

### Task 10: Create RuntimeAdapter protocol and ClaudeCodeAdapter

**Files:**
- Create: `corvus/security/runtime_adapter.py`
- Test: `tests/unit/test_runtime_adapter.py`

**Step 1: Write the failing test**

```python
"""Verify ClaudeCodeAdapter composes settings.json correctly."""

import json

from corvus.security.policy import PolicyEngine
from corvus.security.runtime_adapter import ClaudeCodeAdapter
from corvus.security.tool_context import PermissionTier


class TestClaudeCodeAdapter:
    def test_compose_permissions_default_tier(self):
        engine = PolicyEngine(
            global_deny=["*.env*", "*.ssh/*"],
            tiers={},
        )
        adapter = ClaudeCodeAdapter()
        result = adapter.compose_permissions(
            tier=PermissionTier.DEFAULT,
            global_deny=engine.global_deny,
            extra_deny=["ha.restart_*"],
        )
        assert "*.env*" in result["deny"]
        assert "ha.restart_*" in result["deny"]

    def test_compose_settings_json(self):
        adapter = ClaudeCodeAdapter()
        settings = adapter.compose_settings(deny=["*.env*"])
        parsed = json.loads(settings)
        assert parsed["permissions"]["deny"] == ["*.env*"]
        assert parsed["enabledPlugins"] == {}
        assert parsed["strictKnownMarketplaces"] == []
```

**Step 2: Implement**

Create `corvus/security/runtime_adapter.py`:

```python
"""RuntimeAdapter — abstracts CLI-specific concerns for portability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from corvus.security.tool_context import PermissionTier


class RuntimeAdapter(Protocol):
    def compose_permissions(
        self,
        tier: PermissionTier,
        global_deny: list[str],
        extra_deny: list[str],
    ) -> dict: ...

    def compose_settings(self, deny: list[str]) -> str: ...

    def build_launch_cmd(
        self,
        workspace: Path,
        mcp_config: dict,
        system_prompt: str,
        model: str | None,
    ) -> list[str]: ...


class ClaudeCodeAdapter:
    """Adapter for Claude Code CLI as the agent runtime."""

    def compose_permissions(
        self,
        tier: PermissionTier,
        global_deny: list[str],
        extra_deny: list[str],
    ) -> dict:
        deny = sorted(set(global_deny + extra_deny))
        return {"deny": deny}

    def compose_settings(self, deny: list[str]) -> str:
        return json.dumps(
            {
                "permissions": {"deny": deny},
                "enabledPlugins": {},
                "strictKnownMarketplaces": [],
            },
            indent=2,
        )

    def build_launch_cmd(
        self,
        workspace: Path,
        mcp_config: dict,
        system_prompt: str,
        model: str | None,
    ) -> list[str]:
        cmd = ["claude", "--print", "--verbose"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--setting-sources", "user,project"])
        return cmd
```

**Step 3: Run tests, commit**

```bash
git add -A && git commit -m "feat: add RuntimeAdapter protocol and ClaudeCodeAdapter

CLI-specific concerns (settings.json, launch command) isolated
behind RuntimeAdapter. Core security layers remain runtime-agnostic."
```

---

### Task 11: Create HMAC break-glass token system (F-014)

**Files:**
- Create: `corvus/security/tokens.py`
- Modify: `corvus/gateway/control_plane.py` (integrate tokens)
- Test: `tests/unit/test_break_glass_tokens.py`

**Step 1: Write the failing test**

```python
"""Verify HMAC-SHA256 break-glass tokens."""

import time

import pytest

from corvus.security.tokens import create_break_glass_token, validate_break_glass_token


class TestBreakGlassTokens:
    SECRET = b"test-secret-key-that-is-at-least-32-bytes-long!!"

    def test_create_and_validate(self):
        token = create_break_glass_token(
            secret=self.SECRET,
            agent_name="homelab",
            session_id="s1",
            ttl_seconds=3600,
        )
        payload = validate_break_glass_token(secret=self.SECRET, token=token)
        assert payload["agent_name"] == "homelab"
        assert payload["session_id"] == "s1"

    def test_expired_token_rejected(self):
        token = create_break_glass_token(
            secret=self.SECRET,
            agent_name="homelab",
            session_id="s1",
            ttl_seconds=1,
        )
        time.sleep(1.1)
        with pytest.raises(ValueError, match="expired"):
            validate_break_glass_token(secret=self.SECRET, token=token)

    def test_wrong_secret_rejected(self):
        token = create_break_glass_token(
            secret=self.SECRET,
            agent_name="homelab",
            session_id="s1",
            ttl_seconds=3600,
        )
        with pytest.raises(ValueError, match="signature"):
            validate_break_glass_token(secret=b"wrong-secret-key-also-32-bytes!!", token=token)

    def test_tampered_token_rejected(self):
        token = create_break_glass_token(
            secret=self.SECRET,
            agent_name="homelab",
            session_id="s1",
            ttl_seconds=3600,
        )
        # Tamper with the payload
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # Reverse payload
        tampered = ".".join(parts)
        with pytest.raises(ValueError):
            validate_break_glass_token(secret=self.SECRET, token=tampered)
```

**Step 2: Implement `corvus/security/tokens.py`**

Reuse the HMAC-SHA256 pattern from `corvus/cli/tool_token.py` (which will be deleted later). The new token includes `agent_name` and `session_id` in the payload.

```python
"""HMAC-SHA256 break-glass session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

MIN_SECRET_LEN = 32


def create_break_glass_token(
    *,
    secret: bytes,
    agent_name: str,
    session_id: str,
    ttl_seconds: int,
) -> str:
    if len(secret) < MIN_SECRET_LEN:
        raise ValueError(f"Secret must be at least {MIN_SECRET_LEN} bytes")
    payload = {
        "agent_name": agent_name,
        "session_id": session_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def validate_break_glass_token(*, secret: bytes, token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid token format")
    payload_b64, sig = parts
    expected_sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid token signature")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token expired")
    return payload
```

**Step 3: Integrate into BreakGlassSessionRegistry**

Modify `control_plane.py` to generate and store tokens on activation, validate on `is_active()`.

**Step 4: Run tests, commit**

```bash
git add -A && git commit -m "feat: add HMAC-SHA256 break-glass session tokens (F-014)

Session-scoped tokens with TTL, agent binding, and tamper detection.
Replaces in-memory dict lookup for break-glass state verification."
```

---

### Task 12: Add WebSocket session token auth (F-003)

**Files:**
- Modify: `corvus/api/chat.py:54-63`
- Create: `corvus/security/session_auth.py`
- Test: `tests/unit/test_websocket_auth.py`

**Step 1: Write the failing test**

```python
"""Verify WebSocket connections require session token, not auto-auth."""

from corvus.security.session_auth import SessionAuthManager


class TestWebSocketAuth:
    def test_localhost_without_token_rejected(self):
        mgr = SessionAuthManager(secret=b"x" * 32, allowed_users=["alice"])
        result = mgr.authenticate(client_host="127.0.0.1", token=None, headers={})
        assert result.authenticated is False

    def test_valid_token_accepted(self):
        mgr = SessionAuthManager(secret=b"x" * 32, allowed_users=["alice"])
        token = mgr.create_session_token(user="alice")
        result = mgr.authenticate(client_host="127.0.0.1", token=token, headers={})
        assert result.authenticated is True
        assert result.user == "alice"

    def test_header_auth_still_works(self):
        mgr = SessionAuthManager(secret=b"x" * 32, allowed_users=["alice"])
        result = mgr.authenticate(
            client_host="10.0.0.1",
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is True
```

**Step 2: Implement SessionAuthManager**

**Step 3: Update `corvus/api/chat.py` to use SessionAuthManager instead of localhost auto-auth**

**Step 4: Run tests, commit**

```bash
git add -A && git commit -m "security: replace localhost auto-auth with session tokens (F-003/SEC-007)

WebSocket connections now require a signed session token or trusted
header auth. Localhost no longer auto-authenticates."
```

---

## Phase 3: MCP Stdio Executor

---

### Task 13: Create MCP tool handler base with ToolContext injection

**Files:**
- Create: `corvus/security/mcp_tool.py`
- Test: `tests/unit/test_mcp_tool_handler.py`

**Step 1: Define the MCP tool handler base class**

```python
"""Base class for MCP tool handlers with ToolContext injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_credentials: list[str] = field(default_factory=list)
    is_mutation: bool = False
```

**Step 2: Write tests for credential resolution and permission checking**

**Step 3: Implement, test, commit**

```bash
git add -A && git commit -m "feat: add MCPToolDef base with credential declaration and permission checking"
```

---

### Task 14: Convert tool modules to MCPToolDef format

**Files:**
- Modify: `corvus/cli/tool_registry.py` — refactor modules to return `MCPToolDef` instances
- Test: `tests/unit/test_tool_module_conversion.py`

Convert each module (obsidian, ha, paperless, firefly, email, drive, memory) from returning `(name, callable)` tuples to returning `MCPToolDef` instances with `requires_credentials` declarations.

**Step 1: Write tests verifying each module declares its credentials**

**Step 2: Refactor module registry**

**Step 3: Run tests, commit**

```bash
git add -A && git commit -m "refactor: convert tool modules to MCPToolDef with credential declarations"
```

---

### Task 15: Build in-process MCP stdio server

**Files:**
- Create: `corvus/cli/mcp_stdio.py`
- Modify: `corvus/cli/chat.py` (replace tool_server with MCP stdio)
- Test: `tests/unit/test_mcp_stdio_server.py`

**Step 1: Write tests for MCP server tool registration and invocation**

**Step 2: Implement using `create_sdk_mcp_server` from claude-agent-sdk**

```python
"""In-process MCP stdio server for agent tool execution."""

from __future__ import annotations

from corvus.security.tool_context import ToolContext


async def create_agent_mcp_server(
    tool_defs: list,
    ctx: ToolContext,
):
    """Create an MCP stdio server with agent-scoped tools.

    Uses create_sdk_mcp_server from claude-agent-sdk to register
    tool_defs as native MCP tools. Each tool handler receives the
    ToolContext for credential access and permission checking.
    """
    from claude_agent_sdk import create_sdk_mcp_server

    server = create_sdk_mcp_server()
    for tool_def in tool_defs:
        # Register each tool with its handler bound to ctx
        server.register_tool(
            name=tool_def.name,
            description=tool_def.description,
            input_schema=tool_def.input_schema,
            handler=lambda params, _td=tool_def, _ctx=ctx: _td.execute(_ctx, **params),
        )
    return server
```

**Step 3: Wire into chat.py spawn flow**

Replace `_start_tool_server()` with `create_agent_mcp_server()`. The MCP server runs in the same process, communicating with Claude CLI via stdio pipe.

**Step 4: Run tests, commit**

```bash
git add -A && git commit -m "feat: in-process MCP stdio server replaces Unix socket tool server

Tools are now native MCP tools via create_sdk_mcp_server. No more
Bash wrappers, no socket, no JWT. Credentials stay in-process."
```

---

### Task 16: Delete legacy tool execution files

**Files:**
- Delete: `corvus/cli/tool_server.py`
- Delete: `corvus/cli/tool_token.py`
- Delete: `corvus/hooks.py` (Bash blocklist — replaced by permissions.deny)
- Modify: All files that import from these modules
- Test: Run full suite to verify no breakage

**Step 1: Find all imports of deleted modules**

Run: `rg "from corvus.cli.tool_server|from corvus.cli.tool_token|from corvus.hooks" --type py`

**Step 2: Remove/redirect all imports**

**Step 3: Delete the files**

**Step 4: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_legacy_deletion_results.log`

**Step 5: Commit**

```bash
git add -A && git commit -m "cleanup: remove legacy tool_server, tool_token, and hooks.py

Replaced by in-process MCP stdio server and permissions.deny.
Bash blocklist no longer needed — agents don't have Bash access."
```

---

### Task 17: Purpose-built workspace composition

**Files:**
- Create: `corvus/cli/workspace.py`
- Modify: `corvus/cli/chat.py` (use new workspace builder)
- Test: `tests/unit/test_purpose_built_workspace.py`

**Step 1: Write tests**

```python
"""Verify purpose-built workspace contains only safe, expected files."""

import os
import tempfile
from pathlib import Path


class TestPurposeBuiltWorkspace:
    def test_no_env_files(self):
        ws = _create_test_workspace()
        env_files = list(ws.rglob(".env*"))
        assert env_files == []

    def test_no_source_code(self):
        ws = _create_test_workspace()
        py_files = list(ws.rglob("*.py"))
        assert py_files == []

    def test_has_claude_md(self):
        ws = _create_test_workspace()
        assert (ws / ".claude" / "CLAUDE.md").exists()

    def test_has_settings_json(self):
        ws = _create_test_workspace()
        settings = ws / ".claude" / "settings.json"
        assert settings.exists()

    def test_workspace_perms_restrictive(self):
        ws = _create_test_workspace()
        stat = os.stat(ws)
        assert stat.st_mode & 0o777 == 0o700

    def test_cleanup_removes_workspace(self):
        ws = _create_test_workspace()
        _cleanup_workspace(ws)
        assert not ws.exists()
```

**Step 2: Implement `corvus/cli/workspace.py`**

Uses `tempfile.mkdtemp()` with `0o700` permissions (symlink attack prevention per audit).

**Step 3: Run tests, commit**

```bash
git add -A && git commit -m "feat: purpose-built workspace replaces source snapshot (SEC-002)

Workspace contains only CLAUDE.md, settings.json, and agent skills.
No source code, no .env, no config. Created with 0o700 permissions
via tempfile.mkdtemp() to prevent symlink attacks."
```

---

## Phase 4: Hooks, Audit, and Session Lifecycle

---

### Task 18: Hook-driven audit logging (F-006, F-015)

**Files:**
- Create: `corvus/security/audit.py`
- Test: `tests/unit/test_audit_logging.py`

Implement `on_tool_call` and `on_tool_deny` hooks that log to persistent storage (JSONL file). Both allowed and denied tool calls are logged.

```bash
git add -A && git commit -m "feat: persistent audit logging for tool calls and denials (F-006/F-015)"
```

---

### Task 19: Rate limiting for tool calls (F-008)

**Files:**
- Create: `corvus/security/rate_limiter.py`
- Test: `tests/unit/test_rate_limiter.py`

Sliding-window rate limiter per tool per session. Default: 10/min for mutations, 60/min for reads. Configurable per agent YAML.

```bash
git add -A && git commit -m "feat: sliding-window rate limiter for tool calls (F-008)"
```

---

### Task 20: Session lifecycle hooks (summarization, memory, cleanup)

**Files:**
- Create: `corvus/security/session_lifecycle.py`
- Modify: `corvus/cli/chat.py` (wire lifecycle hooks)
- Test: `tests/unit/test_session_lifecycle.py`

Implement `on_session_end` hook that:
1. Builds `SessionSummary` from audit trail
2. Stores to memory via agent's domain
3. Surfaces to chat UI
4. Cleans up workspace

```bash
git add -A && git commit -m "feat: hook-driven session lifecycle with summarization"
```

---

### Task 21: Cross-domain memory write validation (F-011)

**Files:**
- Modify: `corvus/api/memory.py:172-224`
- Test: `tests/unit/test_memory_domain_validation.py`

Add domain validation at the API layer: the requested domain must match the agent's `own_domain`.

```bash
git add -A && git commit -m "security: validate memory domain at API layer (F-011/SEC-009)"
```

---

### Task 22: Lockout file integrity protection (F-012)

**Files:**
- Modify: `corvus/break_glass.py` (HMAC on lockout.json, perm check on read)
- Test: `tests/unit/test_lockout_integrity.py`

```bash
git add -A && git commit -m "security: add HMAC integrity to lockout.json (F-012)"
```

---

### Task 23: Session idle timeout (F-013)

**Files:**
- Modify: `corvus/cli/chat.py` or session management
- Test: `tests/unit/test_session_timeout.py`

Configurable idle timeout. When triggered, break-glass is auto-deactivated and session drops to default tier.

```bash
git add -A && git commit -m "feat: configurable session idle timeout with break-glass deactivation (F-013)"
```

---

## Phase 5: Hardening & Cleanup

---

### Task 24: Tighten Darwin sandbox profile (F-010)

**Files:**
- Modify: `corvus/acp/sandbox.py:56`
- Test: `tests/unit/test_darwin_sandbox.py`

Replace `(allow default)` with explicit allows for workspace and system dirs only.

```bash
git add -A && git commit -m "security: tighten Darwin sandbox to workspace-only file access (F-010)"
```

---

### Task 25: Tool result sanitization

**Files:**
- Create: `corvus/security/sanitizer.py`
- Test: `tests/unit/test_result_sanitizer.py`

Scrub credential patterns (API keys, tokens, passwords) from tool outputs before they reach the agent context.

```bash
git add -A && git commit -m "security: sanitize credential patterns from tool results"
```

---

### Task 26: Skill integrity checksums

**Files:**
- Modify: `corvus/cli/workspace.py` (add checksum on copy)
- Test: `tests/unit/test_skill_integrity.py`

SHA-256 checksum skills at copy time. Verify before agent reads them.

```bash
git add -A && git commit -m "security: checksum skill files for integrity verification (SEC-010)"
```

---

### Task 27: Final integration test

**Files:**
- Create: `tests/integration/test_security_hardening.py`

End-to-end test: spawn agent, verify env whitelist, verify deny patterns applied, verify tool calls logged, verify break-glass flow with token, verify session cleanup.

```bash
git add -A && git commit -m "test: add end-to-end security hardening integration test"
```

---

## Task Summary

| Phase | Tasks | Focus |
|-------|-------|-------|
| 1 | 1-6 | Critical security fixes (ship immediately) |
| 2 | 7-12 | Policy engine, ToolContext, runtime adapter, tokens, WebSocket auth |
| 3 | 13-17 | MCP stdio executor, module conversion, workspace |
| 4 | 18-23 | Hooks, audit, rate limiting, session lifecycle |
| 5 | 24-27 | Hardening, sanitization, checksums, integration test |

**Total: 27 tasks across 5 phases.**

Phase 1 tasks are independent and can ship as hotfixes. Phases 2-5 build on each other sequentially.
