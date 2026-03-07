# Slice 11: Memory System — DONE

**Goal:** Persistent hybrid-search memory with evergreen files, session-memory hook, and command-logger hook. Memory survives across sessions so the assistant remembers context.

**Architecture:** Three-layer design. Layer 1: Markdown files (MEMORY.md, daily logs, evergreen). Layer 2: memory-core plugin with SQLite + sqlite-vec, hybrid BM25 + vector search, MMR diversity, temporal decay. Layer 3: future (Cognee, Remember.md).

**Tech Stack:** Third-party OpenClaw (memory-core plugin, hooks, EmbeddingGemma 300M local GGUF model), Markdown, SQLite + sqlite-vec

**Depends on:** Slice 10 (Corvus Gateway)
**Blocks:** Slice 12 (Capability Broker + Obsidian)

---

## Summary

| Task | What | Status |
|------|------|--------|
| 1–3 | Memory dirs, evergreen files, shared-memory | DONE |
| 4 | Verify + fix hybrid search config | DONE |
| 5–6 | Hooks (session-memory, command-logger, boot-md) | DONE |
| 7–9 | Manual testing (user does via UI) | READY |
| 10 | Commit checkpoint | DONE |

---

### Tasks 1–3: Memory files + shared-memory — DONE

Created skeleton evergreen files on laptop-server at `~/.openclaw/workspace/`:
- `MEMORY.md` — Curated long-term memory with About Me, Preferences, Homelab, Tools sections
- `USER.md` — Thomas's profile (name, timezone, ADHD note, preferences)
- `memory/personal.md` — Skeleton (Corvus populates organically)
- `memory/projects.md` — Skeleton (Corvus populates organically)
- `memory/health.md` — Skeleton (Corvus populates organically)
- `shared-memory/README.md` — Cross-domain rules (no secrets, structured summaries only)
- `memory/2026-02-26.md` — First daily log (auto-created by session-memory hook)

Other auto-generated workspace files: `SOUL.md`, `AGENTS.md`, `IDENTITY.md`, `TOOLS.md`, `HEARTBEAT.md`

### Task 4: Hybrid search + memory-core plugin — DONE

**Problem found:** memory-core plugin was not loaded. Gateway logged `memory slot plugin not found or not marked as memory: memory-core`.

**Fix applied:**
1. Added `plugins.slots.memory: "memory-core"` to openclaw.json
2. Added `/app/extensions/memory-core` to `plugins.load.paths`
3. Added `memory-core` to `plugins.allow` and `plugins.entries`
4. Configured local embedding provider: EmbeddingGemma 300M GGUF via node-llama-cpp (fully offline)
5. Added sync (watch + 5m interval) and cache (50k entries) settings
6. Restarted gateway — error gone, memory-core loaded

**Verified:**
- SQLite database created at `~/.openclaw/memory/main.sqlite`
- Schema includes: `chunks`, `chunks_fts` (BM25), `embedding_cache`, `files`, `meta`
- sqlite-vec available for vector search
- Embedding model auto-downloads on first search (~600MB)

Config applied:
```json
{
  "memorySearch": {
    "provider": "local",
    "local": {
      "modelPath": "hf:ggml-org/embeddinggemma-300m-qat-q8_0-GGUF/...",
      "modelCacheDir": "/home/node/.cache/openclaw/embeddings"
    },
    "store": { "vector": { "enabled": true } },
    "query": {
      "hybrid": {
        "enabled": true,
        "mmr": { "enabled": true, "lambda": 0.5 },
        "temporalDecay": { "enabled": true, "halfLifeDays": 30 }
      }
    },
    "sync": { "watch": true, "debounceMs": 1500, "interval": "5m" },
    "cache": { "enabled": true, "maxEntries": 50000 },
    "extraPaths": ["~/shared-memory"]
  }
}
```

### Tasks 5–6: Hooks — DONE

All three hooks registered and firing:
- `boot-md` → gateway:startup — runs BOOT.md on startup
- `command-logger` → command — writes structured JSON to `~/.openclaw/logs/commands.log`
- `session-memory` → command:new, command:reset — saves session context to daily log

Verified command-logger output:
```json
{"timestamp":"2026-02-26T14:22:32.139Z","action":"new","sessionKey":"agent:main:main","senderId":"openclaw-control-ui","source":"webchat"}
```

### Tasks 7–9: Manual testing — READY FOR USER

User should test via `https://claw.absolvbass.com/`:
1. Send a few messages, then `/new` — verify daily log updates
2. In new session, ask about previous session content — verify recall
3. The embedding model (~600MB) will auto-download on first `memory_search`

### Task 10: Commit — DONE

Reference config updated at `infra/stacks/laptop-server/openclaw/openclaw.json.reference`.

---

## Memory Architecture

```
~/.openclaw/workspace/
  MEMORY.md                       ← Curated long-term memory (loaded in every session)
  USER.md                         ← User profile
  SOUL.md                         ← Agent personality
  IDENTITY.md                     ← Agent identity
  AGENTS.md                       ← Workspace instructions
  memory/
    personal.md                   ← Evergreen: populated by Corvus organically
    projects.md                   ← Evergreen: populated by Corvus organically
    health.md                     ← Evergreen: populated by Corvus organically
    2026-02-26.md                 ← Daily log (auto-created by session-memory hook)
  shared-memory/
    README.md                     ← Cross-domain shared surface

~/.openclaw/memory/
  main.sqlite                     ← SQLite + sqlite-vec (BM25 + vector search)

~/.openclaw/logs/
  commands.log                    ← Audit trail (command-logger hook)
  telemetry.jsonl                 ← Plugin telemetry
  debug-events.jsonl              ← Plugin debug events
```
