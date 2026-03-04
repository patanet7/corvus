"""Tests for credential store wiring in server startup."""

from pathlib import Path


class TestCredentialStoreWiring:
    """Verify _init_credentials is defined and called in the correct order."""

    def test_init_credentials_defined_in_server(self):
        """The _init_credentials function must exist in server.py."""
        source = (Path(__file__).parent.parent.parent / "corvus" / "server.py").read_text()
        assert "def _init_credentials" in source

    def test_init_credentials_called_before_hub_init(self):
        """init_credentials() must run before AgentsHub initialization in runtime wiring."""
        source = (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "runtime.py").read_text()
        init_pos = source.index("init_credentials()")
        hub_pos = source.index("agents_hub = AgentsHub(")
        assert init_pos < hub_pos

    def test_init_credentials_importable(self):
        """_init_credentials must be importable from corvus.server."""
        from corvus.server import _init_credentials

        assert callable(_init_credentials)

    def test_imports_credential_store_at_top_level(self):
        """get_credential_store must be a top-level import (no lazy imports)."""
        source = (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "runtime.py").read_text()
        # Find the import section (before the first function/class definition)
        first_def = source.index("\ndef ")
        import_section = source[:first_def]
        assert "from corvus.credential_store import get_credential_store" in import_section

    def test_imports_register_credential_patterns_at_top_level(self):
        """register_credential_patterns must be a top-level import (no lazy imports)."""
        source = (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "runtime.py").read_text()
        first_def = source.index("\ndef ")
        import_section = source[:first_def]
        assert "from corvus.sanitize import register_credential_patterns" in import_section

    def test_init_credentials_calls_get_credential_store(self):
        """The function body must call get_credential_store()."""
        import inspect

        from corvus.gateway.runtime import init_credentials

        source = inspect.getsource(init_credentials)
        assert "get_credential_store()" in source

    def test_init_credentials_calls_inject(self):
        """The function body must call store.inject()."""
        import inspect

        from corvus.gateway.runtime import init_credentials

        source = inspect.getsource(init_credentials)
        assert "store.inject()" in source

    def test_init_credentials_calls_register_credential_patterns(self):
        """The function body must call register_credential_patterns()."""
        import inspect

        from corvus.gateway.runtime import init_credentials

        source = inspect.getsource(init_credentials)
        assert "register_credential_patterns(store.credential_values())" in source
