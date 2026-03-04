"""Multi-account Yahoo Mail IMAP client.

Account discovery via env vars:
    YAHOO_ACCOUNT_{name}_EMAIL=...
    YAHOO_ACCOUNT_{name}_APP_PASSWORD=...

Legacy fallback:
    YAHOO_EMAIL, YAHOO_APP_PASSWORD
"""

import imaplib
import os
import re
import ssl

YAHOO_IMAP_HOST = "imap.mail.yahoo.com"
YAHOO_IMAP_PORT = 993


class YahooClient:
    """Multi-account Yahoo IMAP client."""

    def __init__(self, accounts: dict[str, dict[str, str]] | None = None):
        self._accounts = accounts or {}

    @classmethod
    def from_env(cls) -> "YahooClient":
        """Discover Yahoo accounts from YAHOO_ACCOUNT_* env vars."""
        accounts: dict[str, dict[str, str]] = {}
        pattern = re.compile(r"YAHOO_ACCOUNT_(\w+)_(EMAIL|APP_PASSWORD)")

        for key, value in os.environ.items():
            match = pattern.match(key)
            if match:
                name = match.group(1).lower()
                field = match.group(2).lower()
                if name not in accounts:
                    accounts[name] = {}
                accounts[name][field] = value

        # Legacy fallback
        if not accounts:
            email = os.environ.get("YAHOO_EMAIL", "")
            password = os.environ.get("YAHOO_APP_PASSWORD", "")
            if email or password:
                accounts["default"] = {"email": email, "app_password": password}

        return cls(accounts=accounts)

    def list_accounts(self) -> list[str]:
        return list(self._accounts.keys())

    def get_account_email(self, account: str) -> str:
        if account not in self._accounts:
            raise ValueError(f"Unknown account: {account!r}")
        return self._accounts[account].get("email", "")

    def get_connection_params(self, account: str) -> dict[str, str | int]:
        """Return IMAP connection parameters for an account."""
        if account not in self._accounts:
            raise ValueError(f"Unknown account: {account!r}")
        acct = self._accounts[account]
        return {
            "host": acct.get("host", YAHOO_IMAP_HOST),
            "port": int(acct.get("port", YAHOO_IMAP_PORT)),
            "email": acct.get("email", ""),
            "password": acct.get("app_password", ""),
        }

    def connect(self, account: str | None = None) -> imaplib.IMAP4_SSL:
        """Create authenticated IMAP connection. Caller must close when done."""
        acct_name = account or next(iter(self._accounts), None)
        if not acct_name:
            raise RuntimeError("No Yahoo accounts configured")
        params = self.get_connection_params(acct_name)
        host = params["host"]
        port = params["port"]

        # For testing with self-signed certs
        ctx = ssl.create_default_context()
        if host in ("127.0.0.1", "localhost"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        imap = imaplib.IMAP4_SSL(str(host), int(port), ssl_context=ctx)
        imap.login(str(params["email"]), str(params["password"]))
        return imap
