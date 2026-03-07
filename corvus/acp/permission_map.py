"""ACP permission mapper — translates ACP session/request_permission kinds to Corvus capability names.

This is Layer 5 security: mapping ACP permission kinds to Corvus capability
names for policy lookup against CapabilitiesRegistry. Unknown kinds are denied
by default (deny-wins principle).
"""

_ACP_KIND_MAP: dict[str, str | None] = {
    "read": "Read",
    "search": "Grep",
    "edit": "Write",
    "delete": "Write",
    "move": "Write",
    "execute": "Bash",
    "fetch": "WebFetch",
    "think": None,  # Always allowed — no policy check needed
}


def map_acp_permission(acp_kind: str) -> str | None:
    """Map an ACP permission kind to a Corvus capability name.

    Args:
        acp_kind: The ACP session/request_permission kind string (e.g. "read", "execute").

    Returns:
        The Corvus capability name (e.g. "Read", "Bash"), None if always allowed,
        or "__DENIED__" if the kind is unknown (deny-wins for unmapped kinds).
    """
    normalized = acp_kind.lower()
    if normalized in _ACP_KIND_MAP:
        return _ACP_KIND_MAP[normalized]
    return "__DENIED__"
