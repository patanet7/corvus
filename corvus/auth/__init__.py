"""Auth module — OAuth flows, token management, and authentication middleware.

Includes Authelia trusted-proxy middleware and OpenAI PKCE OAuth flow.
"""

from fastapi import HTTPException, Request

from corvus.config import ALLOWED_USERS


def get_user(request: Request) -> str:
    """Extract and validate user from Authelia header."""
    user = request.headers.get("X-Remote-User") or request.headers.get("Remote-User")
    if not user:
        raise HTTPException(status_code=401, detail="No Remote-User header")
    if not ALLOWED_USERS:
        raise HTTPException(status_code=403, detail="ALLOWED_USERS not configured")
    if user not in ALLOWED_USERS:
        raise HTTPException(status_code=403, detail=f"User {user} not allowed")
    return user
