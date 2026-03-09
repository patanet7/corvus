"""Behavioral tests for ToolContext and ToolPermissions."""

from corvus.security.tool_context import PermissionTier, ToolContext, ToolPermissions


class TestPermissionTier:
    """PermissionTier enum values and string behavior."""

    def test_strict_value(self):
        assert PermissionTier.STRICT == "strict"
        assert PermissionTier.STRICT.value == "strict"

    def test_default_value(self):
        assert PermissionTier.DEFAULT == "default"
        assert PermissionTier.DEFAULT.value == "default"

    def test_break_glass_value(self):
        assert PermissionTier.BREAK_GLASS == "break_glass"
        assert PermissionTier.BREAK_GLASS.value == "break_glass"

    def test_is_str_subclass(self):
        assert isinstance(PermissionTier.STRICT, str)


class TestToolPermissions:
    """ToolPermissions deny and confirm_gated matching."""

    def test_is_denied_glob_pattern(self):
        perms = ToolPermissions(deny=["ha.restart_*"])
        assert perms.is_denied("ha.restart_all") is True
        assert perms.is_denied("ha.restart_server") is True

    def test_is_denied_wildcard_pattern(self):
        perms = ToolPermissions(deny=["*.env*"])
        assert perms.is_denied("read.env.local") is True
        assert perms.is_denied("write.env.production") is True

    def test_is_denied_exact_match(self):
        perms = ToolPermissions(deny=["dangerous_tool"])
        assert perms.is_denied("dangerous_tool") is True

    def test_is_denied_returns_false_for_non_matching(self):
        perms = ToolPermissions(deny=["ha.restart_*", "*.env*"])
        assert perms.is_denied("ha.status") is False
        assert perms.is_denied("read.config") is False
        assert perms.is_denied("safe_tool") is False

    def test_is_denied_empty_deny_list(self):
        perms = ToolPermissions(deny=[])
        assert perms.is_denied("anything") is False
        assert perms.is_denied("ha.restart_all") is False

    def test_is_denied_default_deny_list(self):
        perms = ToolPermissions()
        assert perms.is_denied("anything") is False

    def test_is_confirm_gated_exact_match(self):
        perms = ToolPermissions(confirm_gated=["delete_user", "drop_table"])
        assert perms.is_confirm_gated("delete_user") is True
        assert perms.is_confirm_gated("drop_table") is True

    def test_is_confirm_gated_returns_false_for_non_gated(self):
        perms = ToolPermissions(confirm_gated=["delete_user"])
        assert perms.is_confirm_gated("read_user") is False
        assert perms.is_confirm_gated("list_tables") is False

    def test_is_confirm_gated_empty_list(self):
        perms = ToolPermissions()
        assert perms.is_confirm_gated("anything") is False

    def test_deny_wins_multiple_patterns(self):
        perms = ToolPermissions(deny=["safe_*", "ha.*"])
        assert perms.is_denied("safe_operation") is True
        assert perms.is_denied("ha.lights") is True
        assert perms.is_denied("other.tool") is False


class TestToolContext:
    """ToolContext construction and field access."""

    def test_construction_all_fields(self):
        perms = ToolPermissions(
            deny=["ha.restart_*"],
            confirm_gated=["delete_user"],
        )
        ctx = ToolContext(
            agent_name="homelab",
            session_id="sess-abc-123",
            permission_tier=PermissionTier.DEFAULT,
            credentials={"HA_TOKEN": "resolved-token"},
            permissions=perms,
            break_glass_token=None,
        )
        assert ctx.agent_name == "homelab"
        assert ctx.session_id == "sess-abc-123"
        assert ctx.permission_tier == PermissionTier.DEFAULT
        assert ctx.credentials == {"HA_TOKEN": "resolved-token"}
        assert ctx.permissions is perms
        assert ctx.break_glass_token is None

    def test_break_glass_token_set(self):
        ctx = ToolContext(
            agent_name="admin",
            session_id="sess-bg-456",
            permission_tier=PermissionTier.BREAK_GLASS,
            credentials={},
            permissions=ToolPermissions(),
            break_glass_token="bg-token-xyz",
        )
        assert ctx.break_glass_token == "bg-token-xyz"
        assert ctx.permission_tier == PermissionTier.BREAK_GLASS

    def test_credentials_isolation(self):
        """Only declared credential dependencies are present in the dict."""
        ctx = ToolContext(
            agent_name="finance",
            session_id="sess-fin-001",
            permission_tier=PermissionTier.STRICT,
            credentials={"FIREFLY_TOKEN": "ff-tok"},
            permissions=ToolPermissions(),
        )
        assert "FIREFLY_TOKEN" in ctx.credentials
        assert "HA_TOKEN" not in ctx.credentials
        assert "PAPERLESS_TOKEN" not in ctx.credentials
        assert len(ctx.credentials) == 1

    def test_permissions_accessible_from_context(self):
        perms = ToolPermissions(
            deny=["*.env*"],
            confirm_gated=["deploy"],
        )
        ctx = ToolContext(
            agent_name="work",
            session_id="sess-work-002",
            permission_tier=PermissionTier.DEFAULT,
            credentials={},
            permissions=perms,
        )
        assert ctx.permissions.is_denied("read.env.local") is True
        assert ctx.permissions.is_denied("read.config") is False
        assert ctx.permissions.is_confirm_gated("deploy") is True

    def test_break_glass_token_default_none(self):
        ctx = ToolContext(
            agent_name="test",
            session_id="sess-test",
            permission_tier=PermissionTier.DEFAULT,
            credentials={},
            permissions=ToolPermissions(),
        )
        assert ctx.break_glass_token is None
