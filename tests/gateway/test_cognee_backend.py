"""Behavioral contract tests for optional Cognee memory overlay backend."""

from __future__ import annotations

from pathlib import Path

from corvus.memory.backends.cognee import CogneeBackend
from corvus.memory.record import MemoryRecord
from tests.conftest import run


class TestCogneeBackend:
    def test_save_and_search_do_not_crash_when_package_missing(self, tmp_path: Path) -> None:
        backend = CogneeBackend(data_dir=tmp_path / "cognee", weight=0.4)
        if backend.is_available:
            # Package is installed in this environment; this contract test is
            # for graceful absence behavior.
            return

        record = MemoryRecord(
            id="cg-1",
            content="Cognee fallback behavior test",
            domain="shared",
            visibility="shared",
            created_at="2026-03-03T00:00:00+00:00",
        )
        assert run(backend.save(record)) == "cg-1"
        assert run(backend.search("fallback", readable_domains=["shared"])) == []

    def test_health_reports_availability(self, tmp_path: Path) -> None:
        backend = CogneeBackend(data_dir=tmp_path / "cognee", weight=0.4)
        status = run(backend.health_check())
        assert status.name == "cognee-overlay"
        if backend.is_available:
            assert status.status == "healthy"
        else:
            assert status.status == "unhealthy"
