"""Provider edit/setup modal -- text-field credential input.

Shows a modal dialog with password inputs for each field,
masked existing values as hints, and save/cancel buttons.
Saves immediately to the credential store on confirm.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from corvus.credential_store import mask_value


class ProviderModal(ModalScreen[dict[str, str] | None]):
    """Modal for editing a provider's credentials."""

    DEFAULT_CSS = """
    ProviderModal {
        align: center middle;
    }
    #modal-container {
        width: 60;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .field-hint {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    .field-input {
        margin-bottom: 1;
    }
    .modal-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        provider_id: str,
        store_key: str,
        label: str,
        fields: list[tuple[str, str, bool]],
        existing_data: dict[str, str],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.store_key = store_key
        self.label = label
        self.fields = fields
        self.existing_data = existing_data

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static(f"Configure {self.label}", id="modal-title")

            for field_key, placeholder, is_password in self.fields:
                existing = self.existing_data.get(field_key, "")
                yield Label(placeholder)
                yield Input(
                    placeholder=placeholder,
                    id=f"input-{field_key}",
                    password=is_password,
                    classes="field-input",
                )
                if existing:
                    yield Static(
                        f"Current: {mask_value(existing)}",
                        classes="field-hint",
                    )
                    yield Static(
                        "Leave blank to keep existing.",
                        classes="field-hint",
                    )

            with Vertical(classes="modal-buttons"):
                yield Button("Cancel", id="modal-cancel", variant="default")
                yield Button("Save", id="modal-save", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-cancel":
            self.dismiss(None)
        elif event.button.id == "modal-save":
            result: dict[str, str] = {}
            for field_key, _, _ in self.fields:
                inp = self.query_one(f"#input-{field_key}", Input)
                if inp.value:
                    result[field_key] = inp.value
                elif field_key in self.existing_data:
                    result[field_key] = self.existing_data[field_key]
            self.dismiss(result)
