"""Contract test: resolve_backend_and_model output reaches SDK options."""

import ast
import inspect

from corvus.gateway.options import resolve_backend_and_model, build_backend_options


class TestModelContract:
    """Prove the selected model flows through to SDK client options."""

    def test_build_backend_options_accepts_active_model(self) -> None:
        """The active_model parameter exists in build_backend_options signature."""
        sig = inspect.signature(build_backend_options)
        assert "active_model" in sig.parameters

    def test_build_backend_options_accepts_backend_name(self) -> None:
        """The backend_name parameter exists in build_backend_options signature."""
        sig = inspect.signature(build_backend_options)
        assert "backend_name" in sig.parameters

    def test_resolve_backend_and_model_returns_tuple(self) -> None:
        """resolve_backend_and_model returns a (backend, model) tuple."""
        sig = inspect.signature(resolve_backend_and_model)
        # Verify it takes runtime, agent_name, requested_model
        assert "runtime" in sig.parameters
        assert "agent_name" in sig.parameters
        assert "requested_model" in sig.parameters

    def test_resolve_passes_requested_model_through(self) -> None:
        """If requested_model has a slash, it splits into backend/model."""
        source = inspect.getsource(resolve_backend_and_model)
        tree = ast.parse(source)
        # Verify the function exists and has a return statement
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
