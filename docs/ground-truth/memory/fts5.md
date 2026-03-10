---
subsystem: memory/fts5
last_verified: 2026-03-09
---

# FTS5Backend — SQLite FTS5 Primary Backend

FTS5Backend is the always-on primary backend for MemoryHub. It stores all memory records in a SQLite database with FTS5 virtual tables for BM25 text search and WAL mode for concurrent read/write safety. Visibility filtering happens at the SQL level via `readable_domains` parameters, not in Python.

## Ground Truths

- Schema creates `memories` table (with record_id, content, domain, visibility, importance, tags, source, timestamps, metadata) and `memories_fts` FTS5 virtual table indexing content, domain, and tags.
- FTS5 content sync uses three triggers: `memories_ai` (after insert), `memories_ad` (after delete), `memories_au` (after update).
- WAL journal mode is set on every connection via `PRAGMA journal_mode=WAL`.
- Search uses `bm25()` ranking via `-rank AS score` from the FTS5 MATCH query; results are ordered by score descending.
- Visibility filtering in search: shared records are always visible; private records require `domain IN (readable_domains)`.
- Soft-delete via `deleted_at` timestamp; all queries exclude rows where `deleted_at IS NOT NULL`.
- `_migrate_legacy_schema()` handles additive migrations: backfills `record_id`, `updated_at`, `deleted_at`, `metadata` columns; drops and recreates the update trigger during migration.
- All async methods delegate to `asyncio.to_thread()` wrapping synchronous SQLite operations.
- `memory_audit` table stores append-only audit events (timestamp, agent_name, operation, record_id, domain, visibility).
- FTS5 query syntax errors return empty results instead of raising exceptions.
- Health check queries `SELECT COUNT(*) FROM memories` and reports "fts5-primary" status.

## Boundaries

- **Depends on:** `sqlite3` stdlib, `corvus.memory.record.MemoryRecord`, `corvus.memory.backends.protocol.HealthStatus`
- **Consumed by:** `corvus.memory.hub.MemoryHub` (as primary backend)
- **Does NOT:** perform temporal decay, enforce domain ownership, or handle overlay fan-out
