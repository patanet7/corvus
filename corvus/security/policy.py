"""Policy engine — loads policy.yaml and composes permission deny lists."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TierConfig:
    """Configuration for a single permission tier."""

    mode: str  # "allowlist" | "allowlist_with_baseline" | "allow_all"
    confirm_default: str  # "deny" | "allow"
    requires_auth: bool = False
    token_ttl: int = 3600
    max_ttl: int = 14400


@dataclass
class PolicyEngine:
    """Loads policy.yaml and composes permission deny lists per agent per tier."""

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
                requires_auth=cfg.get("requires_auth", False),
                token_ttl=cfg.get("token_ttl", 3600),
                max_ttl=cfg.get("max_ttl", 14400),
            )
        return cls(
            global_deny=data.get("global_deny", []),
            tiers=tiers,
        )

    def compose_deny_list(self, tier: str, extra_deny: list[str]) -> list[str]:
        """Compose final deny list from global + extra_deny. Global always applies."""
        deny = list(self.global_deny)
        deny.extend(extra_deny)
        return sorted(set(deny))

    def confirm_default(self, tier: str) -> str:
        """Get the default confirm behavior for a tier."""
        tc = self.tiers.get(tier)
        return tc.confirm_default if tc else "deny"

    def tier_config(self, tier: str) -> TierConfig | None:
        return self.tiers.get(tier)
