"""Model backends configuration screen.

Five toggleable backend sections: Claude, OpenAI, Ollama, Kimi, OpenAI-compatible.
All toggles off by default. Each backend shows input fields when enabled.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Header, Input, Static

# (backend_id, display_label, fields_when_enabled)
# Each field: (field_id_suffix, placeholder, is_password, default_value)
BACKENDS = [
    (
        "claude",
        "Anthropic Claude",
        [
            ("api-key", "API key (sk-ant-...)", True, ""),
        ],
    ),
    (
        "openai",
        "OpenAI",
        [
            ("api-key", "API key (sk-...)", True, ""),
        ],
    ),
    (
        "ollama",
        "Ollama (local)",
        [
            ("base-url", "Base URL", False, "http://localhost:11434"),
        ],
    ),
    (
        "kimi",
        "Kimi / Moonshot",
        [
            ("api-key", "API key", True, ""),
        ],
    ),
    (
        "openai-compat",
        "OpenAI-compatible endpoint",
        [
            ("label", "Provider name (e.g. LM Studio)", False, ""),
            ("base-url", "Base URL", False, ""),
            ("api-key", "API key (optional)", True, ""),
        ],
    ),
]


def _validate_backend(backend_id: str, fields: dict[str, str]) -> tuple[bool, str]:
    """Validate backend fields. Returns (is_valid, error_message)."""
    if backend_id == "claude":
        key = fields.get("api-key", "")
        if not key.startswith("sk-ant-"):
            return False, "Must start with sk-ant-"
        if len(key) < 80:
            return False, f"Too short ({len(key)} chars, need 80+)"
        return True, ""
    if backend_id == "openai":
        key = fields.get("api-key", "")
        if not key.startswith("sk-"):
            return False, "Must start with sk-"
        return True, ""
    if backend_id == "ollama":
        url = fields.get("base-url", "")
        if not url.startswith(("http://", "https://")):
            return False, "Must be an HTTP(S) URL"
        return True, ""
    if backend_id == "kimi":
        key = fields.get("api-key", "")
        if not key:
            return False, "API key required"
        return True, ""
    if backend_id == "openai-compat":
        url = fields.get("base-url", "")
        if not url.startswith(("http://", "https://")):
            return False, "Must be an HTTP(S) URL"
        return True, ""
    return True, ""


class ModelBackendsScreen(Screen):
    """Model backend configuration with toggleable sections."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("MODEL BACKENDS", id="title")
        yield Static("\nEnable the LLM backends you want to use.\nAll are optional — skip to configure later.\n")

        for backend_id, label, fields in BACKENDS:
            with Vertical(id=f"backend-{backend_id}", classes="backend-section"):
                yield Checkbox(label, id=f"toggle-{backend_id}", value=False)
                with Vertical(id=f"fields-{backend_id}", classes="backend-fields"):
                    for field_suffix, placeholder, is_password, default in fields:
                        yield Input(
                            placeholder=placeholder,
                            id=f"{backend_id}-{field_suffix}",
                            password=is_password,
                            value=default,
                        )
                yield Static("", id=f"validation-{backend_id}")

        yield Button("\u2190 Back", id="back-btn")
        yield Button("Skip All \u2192", id="skip-btn", variant="warning")
        yield Button("Next \u2192", id="next-btn", variant="primary")

    def on_mount(self) -> None:
        """Hide all field containers initially."""
        for backend_id, _, _ in BACKENDS:
            self.query_one(f"#fields-{backend_id}").display = False

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Show/hide fields when a backend toggle changes."""
        checkbox_id = event.checkbox.id
        if not checkbox_id or not checkbox_id.startswith("toggle-"):
            return
        backend_id = checkbox_id.removeprefix("toggle-")
        fields_container = self.query_one(f"#fields-{backend_id}")
        fields_container.display = event.value

    def _collect_enabled_backends(self) -> dict[str, dict[str, str]]:
        """Collect field values from all enabled backends."""
        result: dict[str, dict[str, str]] = {}
        for backend_id, _, fields in BACKENDS:
            toggle = self.query_one(f"#toggle-{backend_id}", Checkbox)
            if not toggle.value:
                continue
            field_values: dict[str, str] = {}
            for field_suffix, _, _, _ in fields:
                inp = self.query_one(f"#{backend_id}-{field_suffix}", Input)
                if inp.value:
                    field_values[field_suffix] = inp.value
            if field_values:
                result[backend_id] = field_values
        return result

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "skip-btn":
            self.app._backends_data = {}  # type: ignore[attr-defined]
            self.app.push_screen("services")
        elif event.button.id == "next-btn":
            backends = self._collect_enabled_backends()
            # Validate enabled backends
            for backend_id, fields in backends.items():
                valid, msg = _validate_backend(backend_id, fields)
                if not valid:
                    label = self.query_one(f"#validation-{backend_id}", Static)
                    label.update(f"Error: {msg}")
                    return
            self.app._backends_data = backends  # type: ignore[attr-defined]
            self.app.push_screen("services")
