"""Behavioral tests for corvus.tui.input.editor.ChatEditor.

No mocks -- exercises real prompt_toolkit objects and verifies
observable properties and binding registrations.
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.keys import Keys

from corvus.tui.input.editor import ChatEditor, _build_keybindings


class _StubCompleter(Completer):
    """Minimal real Completer for testing (no mocks)."""

    def get_completions(self, document: Document, complete_event: object):
        yield Completion("hello", start_position=0)


def _make_editor(multiline: bool = False) -> ChatEditor:
    """Helper to build a ChatEditor for keybinding tests."""
    return ChatEditor(completer=_StubCompleter(), multiline=multiline)


# ------------------------------------------------------------------
# _build_keybindings
# ------------------------------------------------------------------


class TestBuildKeybindings:
    """Tests for the _build_keybindings helper."""

    def test_single_line_has_ctrl_c_and_ctrl_d(self) -> None:
        editor = _make_editor(multiline=False)
        kb = _build_keybindings(multiline=False, editor=editor)
        bound_keys = {
            tuple(b.keys) for b in kb.bindings
        }
        assert (Keys.ControlC,) in bound_keys
        assert (Keys.ControlD,) in bound_keys

    def test_single_line_does_not_bind_enter(self) -> None:
        editor = _make_editor(multiline=False)
        kb = _build_keybindings(multiline=False, editor=editor)
        bound_keys = {
            tuple(b.keys) for b in kb.bindings
        }
        # In single-line mode, Enter is handled by prompt_toolkit default
        assert (Keys.Enter,) not in bound_keys

    def test_multiline_binds_enter_and_submit_keys(self) -> None:
        editor = _make_editor(multiline=True)
        kb = _build_keybindings(multiline=True, editor=editor)
        bound_keys = {
            tuple(b.keys) for b in kb.bindings
        }
        # Enter inserts newline
        assert (Keys.Enter,) in bound_keys
        # Meta+Enter submits
        assert (Keys.Escape, Keys.Enter) in bound_keys
        # Ctrl+J also submits
        assert (Keys.ControlJ,) in bound_keys

    def test_multiline_still_has_ctrl_c_and_ctrl_d(self) -> None:
        editor = _make_editor(multiline=True)
        kb = _build_keybindings(multiline=True, editor=editor)
        bound_keys = {
            tuple(b.keys) for b in kb.bindings
        }
        assert (Keys.ControlC,) in bound_keys
        assert (Keys.ControlD,) in bound_keys

    def test_single_line_binding_count(self) -> None:
        editor = _make_editor(multiline=False)
        kb = _build_keybindings(multiline=False, editor=editor)
        # Ctrl+C + Ctrl+D + Ctrl+L + Ctrl+B + Ctrl+T + Escape = 6 bindings
        assert len(kb.bindings) == 6

    def test_multiline_binding_count(self) -> None:
        editor = _make_editor(multiline=True)
        kb = _build_keybindings(multiline=True, editor=editor)
        # Ctrl+C + Ctrl+D + Ctrl+L + Ctrl+B + Ctrl+T + Escape + Enter + Meta+Enter + Ctrl+J = 9
        assert len(kb.bindings) == 9

    def test_new_keybindings_present(self) -> None:
        """Verify Ctrl+L, Ctrl+B, Ctrl+T, and Escape are bound."""
        editor = _make_editor(multiline=False)
        kb = _build_keybindings(multiline=False, editor=editor)
        bound_keys = {tuple(b.keys) for b in kb.bindings}
        assert (Keys.ControlL,) in bound_keys
        assert (Keys.ControlB,) in bound_keys
        assert (Keys.ControlT,) in bound_keys
        assert (Keys.Escape,) in bound_keys


# ------------------------------------------------------------------
# ChatEditor construction
# ------------------------------------------------------------------


class TestChatEditorConstruction:
    """Tests for ChatEditor initialisation."""

    def test_default_is_single_line(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        assert editor.multiline is False

    def test_multiline_flag_stored(self) -> None:
        editor = ChatEditor(completer=_StubCompleter(), multiline=True)
        assert editor.multiline is True

    def test_session_property_returns_prompt_session(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        assert isinstance(editor.session, PromptSession)

    def test_session_has_completer(self) -> None:
        completer = _StubCompleter()
        editor = ChatEditor(completer=completer)
        assert editor.session.completer is completer

    def test_session_has_history_search_enabled(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        assert editor.session.enable_history_search is True

    def test_key_bindings_property(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        kb = editor.key_bindings
        bound_keys = {tuple(b.keys) for b in kb.bindings}
        assert (Keys.ControlC,) in bound_keys
        assert (Keys.ControlD,) in bound_keys

    def test_session_receives_custom_keybindings(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        # The session's key_bindings should be the same object we built
        assert editor.session.key_bindings is editor.key_bindings

    def test_callbacks_default_to_none(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        assert editor._clear_callback is None
        assert editor._sidebar_callback is None
        assert editor._split_callback is None
        assert editor._back_callback is None

    def test_set_clear_callback(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        called = []
        editor.set_clear_callback(lambda: called.append("clear"))
        assert editor._clear_callback is not None
        editor._clear_callback()
        assert called == ["clear"]

    def test_set_sidebar_callback(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        called = []
        editor.set_sidebar_callback(lambda: called.append("sidebar"))
        assert editor._sidebar_callback is not None
        editor._sidebar_callback()
        assert called == ["sidebar"]

    def test_set_split_callback(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        called = []
        editor.set_split_callback(lambda: called.append("split"))
        assert editor._split_callback is not None
        editor._split_callback()
        assert called == ["split"]

    def test_set_back_callback(self) -> None:
        editor = ChatEditor(completer=_StubCompleter())
        called = []
        editor.set_back_callback(lambda: called.append("back"))
        assert editor._back_callback is not None
        editor._back_callback()
        assert called == ["back"]


# ------------------------------------------------------------------
# Multiline toggle
# ------------------------------------------------------------------


class TestMultilineToggle:
    """Tests for single-line vs multiline construction."""

    def test_single_line_session_multiline_false(self) -> None:
        editor = ChatEditor(completer=_StubCompleter(), multiline=False)
        assert editor.session.multiline is False

    def test_multiline_session_multiline_true(self) -> None:
        editor = ChatEditor(completer=_StubCompleter(), multiline=True)
        assert editor.session.multiline is True

    def test_multiline_has_more_bindings_than_single(self) -> None:
        single = ChatEditor(completer=_StubCompleter(), multiline=False)
        multi = ChatEditor(completer=_StubCompleter(), multiline=True)
        assert len(multi.key_bindings.bindings) > len(single.key_bindings.bindings)
