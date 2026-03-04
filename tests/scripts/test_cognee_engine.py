"""Tests for Cognee knowledge graph engine.

Real behavior, real temp dirs — NO mocks.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from scripts.common.cognee_engine import CogneeEngine, GraphResult


class TestEnsureInit:
    """Test _ensure_init() behavior with real filesystem."""

    def test_ensure_init_sets_initialized_flag(self) -> None:
        """After calling _ensure_init(), _initialized should reflect cognee availability."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CogneeEngine(data_dir=tmpdir)
            assert engine._initialized is False
            engine._ensure_init()
            # If cognee is importable, _initialized becomes True.
            # If not importable, it stays False (graceful degradation).
            assert engine._initialized == engine.is_available

    def test_ensure_init_idempotent(self) -> None:
        """Calling _ensure_init() multiple times is safe and only inits once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CogneeEngine(data_dir=tmpdir)
            engine._ensure_init()
            first_state = engine._initialized
            engine._ensure_init()
            assert engine._initialized == first_state

    def test_ensure_init_sets_env_vars_when_cognee_available(self) -> None:
        """When cognee is importable, env vars are set with correct paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CogneeEngine(data_dir=tmpdir)
            # Clear any pre-existing env vars to test setdefault behavior
            for key in ("COGNEE_DB_PROVIDER", "COGNEE_VECTOR_DB_PROVIDER", "COGNEE_DB_PATH", "COGNEE_VECTOR_DB_PATH"):
                os.environ.pop(key, None)

            engine._ensure_init()

            if engine.is_available:
                assert os.environ.get("COGNEE_DB_PROVIDER") == "sqlite"
                assert os.environ.get("COGNEE_VECTOR_DB_PROVIDER") == "lancedb"
                assert os.environ.get("COGNEE_DB_PATH") == str(Path(tmpdir) / "cognee.db")
                assert os.environ.get("COGNEE_VECTOR_DB_PATH") == str(Path(tmpdir) / "lancedb")

            # Cleanup env vars
            for key in ("COGNEE_DB_PROVIDER", "COGNEE_VECTOR_DB_PROVIDER", "COGNEE_DB_PATH", "COGNEE_VECTOR_DB_PATH"):
                os.environ.pop(key, None)

    def test_ensure_init_does_not_raise_when_cognee_missing(self) -> None:
        """_ensure_init() must never raise, even if cognee is not installed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CogneeEngine(data_dir=tmpdir)
            # This must not raise regardless of cognee availability
            engine._ensure_init()


class TestIsAvailable:
    """Test is_available property."""

    def test_is_available_returns_bool(self) -> None:
        engine = CogneeEngine()
        result = engine.is_available
        assert isinstance(result, bool)

    def test_is_available_consistent(self) -> None:
        """Multiple calls return the same value."""
        engine = CogneeEngine()
        assert engine.is_available == engine.is_available


class TestGraphResult:
    """Test the GraphResult dataclass."""

    def test_has_required_fields(self) -> None:
        r = GraphResult(
            content="test",
            file_path="test.md",
            score=0.5,
            created_at="2026-01-01",
            relationships=["entity1"],
        )
        assert r.content == "test"
        assert r.file_path == "test.md"
        assert r.score == 0.5
        assert r.created_at == "2026-01-01"
        assert r.relationships == ["entity1"]

    def test_relationships_default_empty(self) -> None:
        r = GraphResult(
            content="test",
            file_path="test.md",
            score=0.5,
            created_at="2026-01-01",
        )
        assert r.relationships == []


class TestCogneeContracts:
    """Contract tests that work regardless of whether cognee is installed."""

    def test_is_available_returns_bool(self) -> None:
        engine = CogneeEngine()
        assert isinstance(engine.is_available, bool)

    def test_search_returns_empty_when_unavailable(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/test-cognee")
        if not engine.is_available:
            results = asyncio.run(engine.search("test query"))
            assert results == []

    def test_index_returns_zero_when_unavailable(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/test-cognee")
        if not engine.is_available:
            count = asyncio.run(engine.index("test content", "personal"))
            assert count == 0

    def test_search_with_domain_returns_empty_when_unavailable(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/test-cognee")
        if not engine.is_available:
            results = asyncio.run(engine.search("test query", domain="homelab"))
            assert results == []

    def test_data_dir_defaults(self) -> None:
        engine = CogneeEngine()
        assert str(engine.data_dir) == "/data/cognee"

    def test_data_dir_custom(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/custom-cognee")
        assert str(engine.data_dir) == "/tmp/custom-cognee"


def _cognee_llm_configured() -> bool:
    """Check that cognee is installed AND an LLM backend is configured."""
    if not CogneeEngine().is_available:
        return False
    return bool(os.environ.get("COGNEE_LLM_MODEL") or os.environ.get("COGNEE_LLM_PROVIDER"))


@pytest.mark.skipif(
    not _cognee_llm_configured(),
    reason="cognee not installed or COGNEE_LLM_MODEL/COGNEE_LLM_PROVIDER not set",
)
class TestCogneeWithPackage:
    """Tests that only run when cognee is installed and an LLM backend is configured."""

    @pytest.mark.asyncio
    async def test_index_returns_one(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/test-cognee-live")
        count = await engine.index("Test memory content", "test-domain")
        assert count == 1

    @pytest.mark.asyncio
    async def test_search_returns_graph_results(self) -> None:
        engine = CogneeEngine(data_dir="/tmp/test-cognee-live")
        await engine.index("The cat sat on the mat", "test-domain")
        results = await engine.search("cat", domain="test-domain")
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], GraphResult)
