"""Custom provider/service modal — add arbitrary credentials.

Allows adding a new provider or service with a user-defined name
and key/value pairs.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class CustomModal(ModalScreen[dict[str, str] | None]):
    """Modal for adding a custom provider or service."""

    DEFAULT_CSS = """
    CustomModal {
        align: center middle;
    }
    #custom-container {
        width: 60;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #custom-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .custom-field {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    .custom-field Input {
        width: 1fr;
    }
    .custom-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    .custom-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, section: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.section = section
        self._field_count = 1

    def compose(self) -> ComposeResult:
        title = "Add Custom Provider" if self.section == "provider" else "Add Custom Service"
        with Vertical(id="custom-container"):
            yield Static(title, id="custom-title")

            yield Label("Name")
            yield Input(placeholder="e.g. my-service", id="custom-name")

            yield Static("Fields:", classes="section-label")
            with Vertical(id="custom-fields"):
                yield self._make_field_row(1)

            yield Button("+ Add Field", id="custom-add-field", variant="default")

            with Vertical(classes="custom-buttons"):
                yield Button("Cancel", id="custom-cancel", variant="default")
                yield Button("Save", id="custom-save", variant="primary")

    def _make_field_row(self, index: int) -> Vertical:
        row = Vertical(classes="custom-field", id=f"field-row-{index}")
        row.compose_add_child(Input(placeholder="Key", id=f"custom-key-{index}"))
        row.compose_add_child(Input(placeholder="Value", id=f"custom-val-{index}", password=True))
        return row

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "custom-cancel":
            self.dismiss(None)
        elif event.button.id == "custom-add-field":
            self._field_count += 1
            container = self.query_one("#custom-fields")
            container.mount(self._make_field_row(self._field_count))
        elif event.button.id == "custom-save":
            name = self.query_one("#custom-name", Input).value.strip()
            if not name:
                return
            result: dict[str, str] = {"_name": name, "_section": self.section}
            for i in range(1, self._field_count + 1):
                try:
                    key_input = self.query_one(f"#custom-key-{i}", Input)
                    val_input = self.query_one(f"#custom-val-{i}", Input)
                    if key_input.value and val_input.value:
                        result[key_input.value] = val_input.value
                except Exception:
                    continue
            self.dismiss(result)
