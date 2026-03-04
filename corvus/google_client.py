"""Multi-account Google OAuth client with testable HTTP.

Uses raw `requests` instead of google-api-python-client for testability —
the base_url can be overridden to point at a fake HTTP server in tests.

Account discovery via env vars:
    GOOGLE_ACCOUNT_{name}_EMAIL=...
    GOOGLE_ACCOUNT_{name}_CREDENTIALS=...
    GOOGLE_ACCOUNT_{name}_TOKEN=...
    GOOGLE_DEFAULT_ACCOUNT=...

Legacy fallback:
    GMAIL_TOKEN, GMAIL_CREDENTIALS, GMAIL_ADDRESS
"""

import os
import re
from typing import Any

import requests as http_requests


class GoogleClient:
    """Multi-account Google API client with configurable base URL."""

    def __init__(
        self,
        base_url: str | None = None,
        static_token: str | None = None,
        accounts: dict[str, dict[str, str]] | None = None,
        default_account: str | None = None,
    ):
        self._base_url = base_url
        self._static_token = static_token
        self._accounts = accounts or {}
        self.default_account = default_account or next(iter(self._accounts), None)

    @classmethod
    def from_env(cls, skip_auth: bool = False) -> "GoogleClient":
        """Discover Google accounts from GOOGLE_ACCOUNT_* env vars.

        Args:
            skip_auth: If True, don't load credential files (for testing).
        """
        accounts: dict[str, dict[str, str]] = {}
        pattern = re.compile(r"GOOGLE_ACCOUNT_(\w+)_(EMAIL|CREDENTIALS|TOKEN)")

        for key, value in os.environ.items():
            match = pattern.match(key)
            if match:
                name = match.group(1).lower()
                field = match.group(2).lower()
                if name not in accounts:
                    accounts[name] = {}
                accounts[name][field] = value

        # Legacy fallback: GMAIL_TOKEN / GMAIL_CREDENTIALS / GMAIL_ADDRESS
        if not accounts:
            token_path = os.environ.get("GMAIL_TOKEN", "")
            creds_path = os.environ.get("GMAIL_CREDENTIALS", "")
            email = os.environ.get("GMAIL_ADDRESS", "")
            if token_path or creds_path:
                accounts["default"] = {
                    "email": email,
                    "credentials": creds_path,
                    "token": token_path,
                }

        # Load actual OAuth credentials from files (unless skip_auth)
        if not skip_auth:
            for _name, acct in accounts.items():
                token_path = acct.get("token", "")
                if token_path and os.path.exists(token_path):
                    acct["_token_obj"] = cls._load_token(token_path)

        default: str | None = os.environ.get("GOOGLE_DEFAULT_ACCOUNT", "").lower()
        if default and default not in accounts:
            default = None

        return cls(
            accounts=accounts,
            default_account=default or next(iter(accounts), None),
        )

    @staticmethod
    def _load_token(token_path: str) -> str:
        """Load and refresh an OAuth token, returning the access token string."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        SCOPES = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents",
        ]

        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        return str(creds.token)

    def list_accounts(self) -> list[str]:
        """Return names of configured accounts."""
        return list(self._accounts.keys())

    def get_account_email(self, account: str) -> str:
        """Return the email address for a named account."""
        if account not in self._accounts:
            raise ValueError(f"Unknown account: {account!r}")
        return self._accounts[account].get("email", "")

    def _get_token(self, account: str | None = None) -> str:
        """Get a valid Bearer token for the given account."""
        if self._static_token is not None:
            return self._static_token

        acct_name = account or self.default_account
        if not acct_name or acct_name not in self._accounts:
            raise RuntimeError(f"No credentials for account {acct_name!r}. Available: {list(self._accounts.keys())}")

        acct = self._accounts[acct_name]

        # If we have a preloaded token object, use it
        if "_token_obj" in acct:
            return acct["_token_obj"]

        # If we have a static token string (test mode)
        if "token" in acct and not acct["token"].endswith(".json"):
            return acct["token"]

        raise RuntimeError(f"No credentials configured for account {acct_name!r}")

    def request(
        self,
        method: str,
        path: str,
        account: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> Any:
        """Make an authenticated HTTP request.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE, PUT).
            path: API path (e.g., '/gmail/v1/users/me/messages').
            account: Account name. Uses default if None.
            params: Query parameters.
            json: JSON body.
            data: Raw body bytes (for file uploads).
            headers: Extra headers.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: On auth failure or missing credentials.
            requests.HTTPError: On non-2xx response.
        """
        if account and account not in self._accounts:
            raise ValueError(f"Unknown account: {account!r}")

        token = self._get_token(account)
        url = f"{self._base_url}{path}" if self._base_url else path

        req_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            req_headers.update(headers)

        resp = http_requests.request(
            method,
            url,
            params=params,
            json=json,
            data=data,
            headers=req_headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
