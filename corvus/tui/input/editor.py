"""ChatEditor — wraps prompt_toolkit PromptSession with custom keybindings.

Provides a unified input editor for the Corvus TUI with:
- Ctrl+R: reverse history search (built-in, enabled via enable_history_search)
- Ctrl+C: cancel/clear current input
- Ctrl+D: signal exit (raises EOFError)
- Enter: submit input in single-line mode
- Meta+Enter / Ctrl+J: insert newline in multiline mode
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


def _build_keybindings(multiline: bool) -> KeyBindings:
    """Build the custom keybinding set for the chat editor.

    Args:
        multiline: When True, Enter inserts a newline and Meta+Enter /
            Ctrl+J submits.  When False, Enter submits directly.

    Returns:
        A KeyBindings instance with all custom bindings registered.
    """
    kb = KeyBindings()

    @kb.add(Keys.ControlC)
    def _clear_input(event: object) -> None:
        """Cancel / clear the current input buffer."""
        buf = event.current_buffer  # type: ignore[attr-defined]
        if buf.text:
            buf.reset()
        else:
            buf.reset()
            raise KeyboardInterrupt

    @kb.add(Keys.ControlD)
    def _exit(event: object) -> None:
        """Signal exit by raising EOFError."""
        raise EOFError

    if multiline:

        @kb.add(Keys.Enter)
        def _newline(event: object) -> None:
            """Insert a newline in multiline mode."""
            event.current_buffer.insert_text("\n")  # type: ignore[attr-defined]

        @kb.add(Keys.Escape, Keys.Enter)
        def _submit_meta_enter(event: object) -> None:
            """Submit input with Meta+Enter in multiline mode."""
            event.current_buffer.validate_and_handle()  # type: ignore[attr-defined]

        @kb.add(Keys.ControlJ)
        def _submit_ctrl_j(event: object) -> None:
            """Submit input with Ctrl+J in multiline mode."""
            event.current_buffer.validate_and_handle()  # type: ignore[attr-defined]

    return kb


class ChatEditor:
    """Wraps prompt_toolkit PromptSession with custom keybindings.

    Attributes:
        multiline: Whether the editor is in multiline mode.
    """

    def __init__(self, completer: Completer, multiline: bool = False) -> None:
        """Initialise the chat editor.

        Args:
            completer: A prompt_toolkit Completer (typically ChatCompleter)
                passed through to the underlying PromptSession.
            multiline: When True, Enter inserts a newline and Meta+Enter /
                Ctrl+J submits the input.
        """
        self.multiline: bool = multiline
        self._keybindings: KeyBindings = _build_keybindings(multiline)
        self._session: PromptSession = PromptSession(
            completer=completer,
            key_bindings=self._keybindings,
            enable_history_search=True,
            multiline=multiline,
        )

    async def prompt(
        self,
        prompt_text: str,
        bottom_toolbar: object = None,
    ) -> str:
        """Get input from the user with custom keybindings.

        Args:
            prompt_text: The prompt string displayed to the user.
            bottom_toolbar: Optional toolbar content (string, HTML, or callable).

        Returns:
            The text entered by the user.

        Raises:
            EOFError: When the user presses Ctrl+D.
            KeyboardInterrupt: When the user presses Ctrl+C on empty input.
        """
        result: str = await self._session.prompt_async(
            prompt_text,
            bottom_toolbar=bottom_toolbar,
        )
        return result

    @property
    def session(self) -> PromptSession:
        """Access the underlying PromptSession."""
        return self._session

    @property
    def key_bindings(self) -> KeyBindings:
        """Access the custom keybindings."""
        return self._keybindings
