"""Auth profile types -- multi-credential per-provider storage.

Profiles are named credentials (e.g. 'anthropic:default', 'anthropic:backup')
that support round-robin rotation, failure tracking, and per-agent overrides.
All stored SOPS-encrypted in the credential store.

Multi-credential profiles with SOPS encryption at rest.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiKeyCredential:
    """Static API key credential (e.g. sk-ant-api3...)."""

    provider: str
    key: str = ""
    email: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    type: str = field(default="api_key", init=False)


@dataclass
class TokenCredential:
    """Static bearer token (e.g. setup-token from claude setup-token).

    Not refreshable -- treated like an API key but with optional expiry.
    """

    provider: str
    token: str = ""
    expires: int | None = None
    email: str = ""
    type: str = field(default="token", init=False)


@dataclass
class OAuthCredential:
    """OAuth credential with access/refresh tokens (e.g. Codex PKCE flow)."""

    provider: str
    access_token: str = ""
    refresh_token: str = ""
    expires: int = 0
    account_id: str = ""
    client_id: str = ""
    email: str = ""
    type: str = field(default="oauth", init=False)


AuthProfileCredential = ApiKeyCredential | TokenCredential | OAuthCredential


@dataclass
class EligibilityResult:
    """Result of credential eligibility check."""

    eligible: bool
    reason: str  # "ok", "missing_credential", "expired", "invalid_expires"


@dataclass
class ProfileUsageStats:
    """Per-profile usage statistics for rotation and cooldown tracking."""

    last_used: int = 0
    cooldown_until: int = 0
    disabled_until: int = 0
    disabled_reason: str = ""
    error_count: int = 0
    last_failure_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_used": self.last_used,
            "cooldown_until": self.cooldown_until,
            "disabled_until": self.disabled_until,
            "disabled_reason": self.disabled_reason,
            "error_count": self.error_count,
            "last_failure_at": self.last_failure_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileUsageStats:
        return cls(
            last_used=data.get("last_used", 0),
            cooldown_until=data.get("cooldown_until", 0),
            disabled_until=data.get("disabled_until", 0),
            disabled_reason=data.get("disabled_reason", ""),
            error_count=data.get("error_count", 0),
            last_failure_at=data.get("last_failure_at", 0),
        )


@dataclass
class AuthProfileStore:
    """In-memory store of all auth profiles with ordering and usage stats.

    Serialized to/from a dict for SOPS-encrypted storage in credentials.json
    under the '_auth_profiles' key.
    """

    profiles: dict[str, AuthProfileCredential] = field(default_factory=dict)
    order: dict[str, list[str]] = field(default_factory=dict)
    last_good: dict[str, str] = field(default_factory=dict)
    usage_stats: dict[str, ProfileUsageStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "version": 1,
            "profiles": {},
            "order": self.order,
            "last_good": self.last_good,
            "usage_stats": {},
        }
        for pid, cred in self.profiles.items():
            if isinstance(cred, ApiKeyCredential):
                result["profiles"][pid] = {
                    "type": "api_key",
                    "provider": cred.provider,
                    "key": cred.key,
                    "email": cred.email,
                    "metadata": cred.metadata,
                }
            elif isinstance(cred, TokenCredential):
                result["profiles"][pid] = {
                    "type": "token",
                    "provider": cred.provider,
                    "token": cred.token,
                    "expires": cred.expires,
                    "email": cred.email,
                }
            elif isinstance(cred, OAuthCredential):
                result["profiles"][pid] = {
                    "type": "oauth",
                    "provider": cred.provider,
                    "access_token": cred.access_token,
                    "refresh_token": cred.refresh_token,
                    "expires": cred.expires,
                    "account_id": cred.account_id,
                    "client_id": cred.client_id,
                    "email": cred.email,
                }
        for pid, stats in self.usage_stats.items():
            result["usage_stats"][pid] = stats.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthProfileStore:
        store = cls()
        store.order = data.get("order", {})
        store.last_good = data.get("last_good", {})
        for pid, cred_data in data.get("profiles", {}).items():
            cred_type = cred_data.get("type", "api_key")
            if cred_type == "api_key":
                store.profiles[pid] = ApiKeyCredential(
                    provider=cred_data.get("provider", ""),
                    key=cred_data.get("key", ""),
                    email=cred_data.get("email", ""),
                    metadata=cred_data.get("metadata", {}),
                )
            elif cred_type == "token":
                store.profiles[pid] = TokenCredential(
                    provider=cred_data.get("provider", ""),
                    token=cred_data.get("token", ""),
                    expires=cred_data.get("expires"),
                    email=cred_data.get("email", ""),
                )
            elif cred_type == "oauth":
                store.profiles[pid] = OAuthCredential(
                    provider=cred_data.get("provider", ""),
                    access_token=cred_data.get("access_token", ""),
                    refresh_token=cred_data.get("refresh_token", ""),
                    expires=cred_data.get("expires", 0),
                    account_id=cred_data.get("account_id", ""),
                    client_id=cred_data.get("client_id", ""),
                    email=cred_data.get("email", ""),
                )
        for pid, stats_data in data.get("usage_stats", {}).items():
            store.usage_stats[pid] = ProfileUsageStats.from_dict(stats_data)
        return store


def evaluate_credential_eligibility(
    credential: AuthProfileCredential,
    now: int | None = None,
) -> EligibilityResult:
    """Check if a credential is usable right now."""
    if now is None:
        now = int(time.time() * 1000)

    if isinstance(credential, ApiKeyCredential):
        if not credential.key:
            return EligibilityResult(eligible=False, reason="missing_credential")
        return EligibilityResult(eligible=True, reason="ok")

    if isinstance(credential, TokenCredential):
        if not credential.token:
            return EligibilityResult(eligible=False, reason="missing_credential")
        if credential.expires is not None:
            if credential.expires <= 0:
                return EligibilityResult(eligible=False, reason="invalid_expires")
            if now >= credential.expires:
                return EligibilityResult(eligible=False, reason="expired")
        return EligibilityResult(eligible=True, reason="ok")

    if isinstance(credential, OAuthCredential):
        if not credential.access_token and not credential.refresh_token:
            return EligibilityResult(eligible=False, reason="missing_credential")
        if credential.expires > 0 and now >= credential.expires:
            return EligibilityResult(eligible=False, reason="expired")
        return EligibilityResult(eligible=True, reason="ok")

    return EligibilityResult(eligible=False, reason="missing_credential")
