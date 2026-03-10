---
subsystem: memory/cognee
last_verified: 2026-03-09
---

# CogneeBackend — Optional Overlay

CogneeBackend is an optional overlay backend that integrates Cognee knowledge graph recall into the memory system. It degrades gracefully when the `cognee` package is not installed, returning empty results or no-ops for all operations. It is a search/index overlay only; FTS5 remains the source of truth.

## Ground Truths

- `is_available` property checks whether `cognee` is importable; all operations short-circuit with safe defaults when unavailable.
- Configuration is lazy via `_configure()`: sets Cognee DB provider (sqlite), vector DB (lancedb), LLM config from environment variables, and resolves Ollama endpoint via `resolve_ollama_url()`.
- Data is stored per domain as Cognee datasets; domain maps directly to dataset name.
- Save prepends `__corvus_record_id__:` prefix to content so record IDs survive round-trip through Cognee; extraction uses `_extract_record_id()` on search results.
- Search iterates all readable domain datasets, merges results by record ID keeping highest score, and applies a configurable `weight` multiplier (default 0.3) to raw scores.
- `get()`, `list_memories()`, and `forget()` return None/empty/False respectively; the overlay does not support direct record lookup, pagination, or per-record deletion.
- Health check reports "cognee-overlay" status; unhealthy if package is missing or `_configure()` raises.
- Fallback record IDs use `uuid5(NAMESPACE_URL, "cognee:{dataset}:{content}")` when no embedded record ID prefix is found.

## Boundaries

- **Depends on:** `cognee` package (optional), `corvus.ollama_probe.resolve_ollama_url`, `corvus.memory.record.MemoryRecord`
- **Consumed by:** `corvus.memory.hub.MemoryHub` (as overlay in `overlays` list)
- **Does NOT:** serve as source of truth, support update/forget/list operations, or enforce domain ownership
