"""Tests for Task 5.7: Theme System — switchable themes.

NO MOCKS — tests real TuiTheme instantiation and property changes.
"""

from corvus.tui.theme import THEME_PRESETS, TuiTheme, available_themes


class TestThemeDefaults:
    """Default theme has expected values."""

    def test_default_name(self) -> None:
        theme = TuiTheme()
        assert theme.name == "default"

    def test_default_border(self) -> None:
        theme = TuiTheme()
        assert theme.border == "dim"

    def test_default_error(self) -> None:
        theme = TuiTheme()
        assert theme.error == "bold red"

    def test_agent_color_known(self) -> None:
        theme = TuiTheme()
        assert theme.agent_color("huginn") == "bright_magenta"
        assert theme.agent_color("homelab") == "bright_green"

    def test_agent_color_fallback(self) -> None:
        theme = TuiTheme()
        color = theme.agent_color("unknown_agent")
        assert color  # Should get a fallback color

    def test_agent_color_stable(self) -> None:
        theme = TuiTheme()
        c1 = theme.agent_color("newagent")
        c2 = theme.agent_color("newagent")
        assert c1 == c2


class TestLightTheme:
    """Light theme overrides specific properties."""

    def test_light_name(self) -> None:
        theme = TuiTheme("light")
        assert theme.name == "light"

    def test_light_user_label(self) -> None:
        theme = TuiTheme("light")
        assert "black" in theme.user_label

    def test_light_syntax_theme(self) -> None:
        theme = TuiTheme("light")
        assert theme.tool_syntax_theme != "monokai"

    def test_light_inherits_unset_properties(self) -> None:
        theme = TuiTheme("light")
        # Properties not in light preset should keep defaults
        assert theme.confirm_border == "yellow"


class TestMinimalTheme:
    """Minimal theme uses dim styling throughout."""

    def test_minimal_name(self) -> None:
        theme = TuiTheme("minimal")
        assert theme.name == "minimal"

    def test_minimal_borders_dim(self) -> None:
        theme = TuiTheme("minimal")
        assert theme.welcome_border == "dim"
        assert theme.confirm_border == "dim"
        assert theme.tool_border == "dim"


class TestAvailableThemes:
    """available_themes returns all preset names."""

    def test_includes_default(self) -> None:
        assert "default" in available_themes()

    def test_includes_light(self) -> None:
        assert "light" in available_themes()

    def test_includes_minimal(self) -> None:
        assert "minimal" in available_themes()

    def test_returns_list(self) -> None:
        themes = available_themes()
        assert isinstance(themes, list)
        assert len(themes) >= 3


class TestThemePresets:
    """THEME_PRESETS dict is well-formed."""

    def test_presets_are_dict(self) -> None:
        assert isinstance(THEME_PRESETS, dict)

    def test_default_preset_empty(self) -> None:
        # Default theme uses class defaults — no overrides
        assert THEME_PRESETS["default"] == {}

    def test_light_preset_has_overrides(self) -> None:
        assert len(THEME_PRESETS["light"]) > 0

    def test_all_preset_keys_are_valid_attrs(self) -> None:
        """Every key in every preset must be a real TuiTheme attribute."""
        theme = TuiTheme()
        for preset_name, overrides in THEME_PRESETS.items():
            for key in overrides:
                assert hasattr(theme, key), (
                    f"Preset '{preset_name}' has key '{key}' which is not a TuiTheme attribute"
                )


class TestUnknownTheme:
    """Unknown theme name falls back to defaults."""

    def test_unknown_theme_keeps_defaults(self) -> None:
        theme = TuiTheme("nonexistent")
        assert theme.name == "nonexistent"
        assert theme.border == "dim"  # Still default
        assert theme.error == "bold red"  # Still default
