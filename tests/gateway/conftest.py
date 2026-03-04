"""Gateway test conftest -- shared fixtures for gateway-level tests.

Re-exports from root conftest for backward compatibility:
- run: async-to-sync helper
- make_hub: hub factory function
- memory_config, memory_hub, fts5_backend: composable fixtures (via pytest)

All fixtures use tmp_path for automatic cleanup. NO mocks anywhere.
"""

from tests.conftest import make_hub, run  # noqa: F401 -- re-exported for test files
