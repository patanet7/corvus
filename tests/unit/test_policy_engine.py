"""Behavioral tests for PolicyEngine — real YAML files, no mocks."""

from pathlib import Path
import tempfile

import pytest
import yaml

from corvus.security.policy import PolicyEngine, TierConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_POLICY = {
    "global_deny": ["*.env*", "*.ssh/*", "*credentials*"],
    "tiers": {
        "strict": {
            "mode": "allowlist",
            "confirm_default": "deny",
        },
        "default": {
            "mode": "allowlist_with_baseline",
            "confirm_default": "deny",
        },
        "break_glass": {
            "mode": "allow_all",
            "confirm_default": "allow",
            "requires_auth": True,
            "token_ttl": 3600,
            "max_ttl": 14400,
        },
    },
}


@pytest.fixture()
def policy_yaml(tmp_path: Path) -> Path:
    """Write a real policy YAML to a temp file and return its path."""
    p = tmp_path / "policy.yaml"
    p.write_text(yaml.dump(SAMPLE_POLICY, default_flow_style=False))
    return p


@pytest.fixture()
def engine(policy_yaml: Path) -> PolicyEngine:
    return PolicyEngine.from_yaml(policy_yaml)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestLoadFromYaml:
    def test_loads_global_deny(self, engine: PolicyEngine) -> None:
        assert engine.global_deny == ["*.env*", "*.ssh/*", "*credentials*"]

    def test_loads_all_tiers(self, engine: PolicyEngine) -> None:
        assert set(engine.tiers.keys()) == {"strict", "default", "break_glass"}

    def test_strict_tier_mode(self, engine: PolicyEngine) -> None:
        assert engine.tiers["strict"].mode == "allowlist"

    def test_break_glass_requires_auth(self, engine: PolicyEngine) -> None:
        assert engine.tiers["break_glass"].requires_auth is True

    def test_break_glass_token_ttl(self, engine: PolicyEngine) -> None:
        assert engine.tiers["break_glass"].token_ttl == 3600

    def test_break_glass_max_ttl(self, engine: PolicyEngine) -> None:
        assert engine.tiers["break_glass"].max_ttl == 14400

    def test_default_tier_no_auth(self, engine: PolicyEngine) -> None:
        assert engine.tiers["default"].requires_auth is False

    def test_empty_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("")
        eng = PolicyEngine.from_yaml(p)
        assert eng.global_deny == []
        assert eng.tiers == {}


# ---------------------------------------------------------------------------
# compose_deny_list
# ---------------------------------------------------------------------------


class TestComposeDenyList:
    def test_global_deny_always_present(self, engine: PolicyEngine) -> None:
        result = engine.compose_deny_list("strict", [])
        for pattern in engine.global_deny:
            assert pattern in result

    def test_extra_deny_merged(self, engine: PolicyEngine) -> None:
        extra = ["*.log", "*/tmp/*"]
        result = engine.compose_deny_list("default", extra)
        for pattern in extra:
            assert pattern in result
        for pattern in engine.global_deny:
            assert pattern in result

    def test_duplicates_removed(self, engine: PolicyEngine) -> None:
        extra = ["*.env*", "*.env*", "*.log"]
        result = engine.compose_deny_list("strict", extra)
        assert result == sorted(set(result))

    def test_result_is_sorted(self, engine: PolicyEngine) -> None:
        extra = ["z_pattern", "a_pattern"]
        result = engine.compose_deny_list("default", extra)
        assert result == sorted(result)

    def test_break_glass_still_has_global_deny(self, engine: PolicyEngine) -> None:
        result = engine.compose_deny_list("break_glass", [])
        for pattern in engine.global_deny:
            assert pattern in result

    def test_unknown_tier_still_applies_global_deny(self, engine: PolicyEngine) -> None:
        result = engine.compose_deny_list("nonexistent_tier", [])
        for pattern in engine.global_deny:
            assert pattern in result


# ---------------------------------------------------------------------------
# confirm_default
# ---------------------------------------------------------------------------


class TestConfirmDefault:
    def test_strict_defaults_deny(self, engine: PolicyEngine) -> None:
        assert engine.confirm_default("strict") == "deny"

    def test_default_defaults_deny(self, engine: PolicyEngine) -> None:
        assert engine.confirm_default("default") == "deny"

    def test_break_glass_defaults_allow(self, engine: PolicyEngine) -> None:
        assert engine.confirm_default("break_glass") == "allow"

    def test_unknown_tier_defaults_deny(self, engine: PolicyEngine) -> None:
        assert engine.confirm_default("nonexistent") == "deny"


# ---------------------------------------------------------------------------
# tier_config
# ---------------------------------------------------------------------------


class TestTierConfig:
    def test_returns_tier_config_for_valid_tier(self, engine: PolicyEngine) -> None:
        tc = engine.tier_config("strict")
        assert isinstance(tc, TierConfig)
        assert tc.mode == "allowlist"

    def test_returns_none_for_unknown_tier(self, engine: PolicyEngine) -> None:
        assert engine.tier_config("nonexistent") is None

    def test_break_glass_config_fields(self, engine: PolicyEngine) -> None:
        tc = engine.tier_config("break_glass")
        assert tc is not None
        assert tc.mode == "allow_all"
        assert tc.confirm_default == "allow"
        assert tc.requires_auth is True
        assert tc.token_ttl == 3600
        assert tc.max_ttl == 14400


# ---------------------------------------------------------------------------
# Real config/policy.yaml
# ---------------------------------------------------------------------------


class TestRealPolicyYaml:
    """Load the actual config/policy.yaml shipped with the repo."""

    REAL_POLICY = Path(__file__).resolve().parents[2] / "config" / "policy.yaml"

    def test_real_policy_loads(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert len(engine.global_deny) > 0
        assert len(engine.tiers) >= 3

    def test_real_policy_has_required_tiers(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert "strict" in engine.tiers
        assert "default" in engine.tiers
        assert "break_glass" in engine.tiers

    def test_real_policy_global_deny_blocks_env(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert "*.env*" in engine.global_deny

    def test_real_policy_global_deny_blocks_ssh(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert "*.ssh/*" in engine.global_deny

    def test_real_policy_global_deny_blocks_pem(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert "*.pem" in engine.global_deny

    def test_real_policy_break_glass_requires_auth(self) -> None:
        engine = PolicyEngine.from_yaml(self.REAL_POLICY)
        assert engine.tiers["break_glass"].requires_auth is True
