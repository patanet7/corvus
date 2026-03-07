"""Tests for credential eligibility evaluation."""

import time

from corvus.auth.profiles import (
    ApiKeyCredential,
    OAuthCredential,
    TokenCredential,
    evaluate_credential_eligibility,
)


class TestEvaluateCredentialEligibility:
    def test_api_key_with_key_is_eligible(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="sk-ant-...")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True
        assert result.reason == "ok"

    def test_api_key_without_key_is_ineligible(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is False
        assert result.reason == "missing_credential"

    def test_token_valid_no_expiry(self) -> None:
        cred = TokenCredential(provider="anthropic", token="sk-ant-oat01-...")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_token_expired(self) -> None:
        cred = TokenCredential(provider="anthropic", token="tok", expires=1000)
        result = evaluate_credential_eligibility(cred, now=2000)
        assert result.eligible is False
        assert result.reason == "expired"

    def test_token_valid_future_expiry(self) -> None:
        future = int(time.time() * 1000) + 3600000
        cred = TokenCredential(provider="anthropic", token="tok", expires=future)
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_oauth_with_access_token(self) -> None:
        future = int(time.time() * 1000) + 3600000
        cred = OAuthCredential(
            provider="codex", access_token="eyJ...", expires=future
        )
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_oauth_expired(self) -> None:
        cred = OAuthCredential(
            provider="codex", access_token="eyJ...", expires=1000
        )
        result = evaluate_credential_eligibility(cred, now=2000)
        assert result.eligible is False
        assert result.reason == "expired"

    def test_oauth_missing_tokens(self) -> None:
        cred = OAuthCredential(provider="codex")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is False
        assert result.reason == "missing_credential"
