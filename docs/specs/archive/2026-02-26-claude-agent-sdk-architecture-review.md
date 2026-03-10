---
title: "Architecture Review: Claude Agent SDK as OpenClaw Replacement"
type: spec
status: implemented
date: 2026-02-26
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Architecture Review: Claude Agent SDK as OpenClaw Replacement

**Date:** 2026-02-26
**Status:** DECISION DOCUMENT
**Author:** LLM Architect review
**Context:** The previous architecture decision report (2026-02-26) recommended Option B (raw Claude SDK + MCP). The Claude Agent SDK has since been identified as a higher-level abstraction that sits between "raw SDK" and "full platform." This document evaluates whether the Agent SDK changes the calculus, and produces a revised build plan.

---

## 1. Feature Matrix: Claude Agent SDK vs OpenClaw vs Raw SDK

| Dimension | OpenClaw (Current) | Raw Claude SDK (Previous Option B) | Claude Agent SDK (New Option) |
|-----------|--------------------|------------------------------------|-------------------------------|
| **Agent loop** | Built-in | Must build (~100-200 lines) | Built-in (query() iterator) |
| **Tool execution** | Built-in | Must build (~100 lines) | Built-in (all tools auto-executed) |
| **Built-in tools** | Limited (sandbox tools) | None (all custom) | Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, AskUserQuestion |
| **MCP support** | None (plugin system instead) | Must integrate MCP client (~200 lines) | Native (mcpServers config, stdio/HTTP) |
| **Subagents** | Agent configs in openclaw.json | Must build routing (~200-300 lines) | Native (agents param in query(), automatic delegation) |
| **Hooks** | Plugin event hooks (api.on()) | Must build (~50-100 lines) | Native callbacks (PreToolUse, PostToolUse, Stop, etc.) |
| **Session management** | Built-in | Must build (SQLite, ~50 lines) | Built-in (auto-generated IDs, resume, fork) |
| **Permissions** | Config-based (allow/deny groups) | Must build (~50-100 lines) | Built-in (modes + allowedTools/disallowedTools + canUseTool callback) |
| **System prompts** | openclaw.json + Persona.md | Custom string per agent | systemPrompt option + CLAUDE.md support |
| **Memory** | memory-core plugin (SQLite+vec, BM25+vectors, MMR, temporal decay) | Must rebuild (~400-600 lines) | None built-in -- must provide via MCP or custom tool |
| **Web UI** | Control UI (built-in chat) | Must build or adopt (~4-6 hours) | None -- must build or adopt |
| **Webhook endpoint** | Built-in gateway HTTP server | Must build (~30 lines) | None -- must build |
| **Authentication** | Trusted-proxy (Authelia header) | Must build (~20 lines) | None -- must build |
| **Sandbox execution** | Docker containers (mode: all) | Docker API directly | Container-based sandboxing (recommended pattern) |
| **Credential isolation** | Must build as plugin (Slice 12) | MCP server env vars (free) | MCP server env vars + createSdkMcpServer() -- free by design |
| **Observability** | Plugin hooks + JSONL logs | Must build | Hook callbacks (PostToolUse, Notification) -- wire to Loki |
| **Streaming** | Built-in | Must build | Built-in (async iterator from query()) |
| **Multi-model** | Config-based model selection | Must implement | Supports Anthropic, Bedrock, Vertex, Azure out of the box |
| **Plugin system** | OpenClaw plugin SDK | N/A | Plugins (local path, manifest) + SDK MCP servers |
| **Tool search** | N/A | N/A | Auto-activates when MCP tools > 10% of context |
| **Context compaction** | safeguard mode | N/A | PreCompact hook + built-in compaction |
| **Cost** | Anthropic API key (same) | Anthropic API key (same) | Anthropic API key (same) |

### Summary Scorecard

| Criteria | OpenClaw | Raw SDK | Agent SDK |
|----------|----------|---------|-----------|
| Build effort for core runtime | 0 (done) | High (~24-34h) | Low (~4-8h) |
| Build effort for domain tools | High (~30h of plugins) | Medium (~15-20h MCP) | Medium (~15-20h MCP) |
| Credential isolation | Must build (Slice 12) | Free (MCP design) | Free (MCP + SDK MCP server) |
| Memory system | Best (hybrid search running) | Must rebuild | Must rebuild or port |
| Web UI | Done | Must build | Must build |
| Vendor lock-in | OpenClaw project | Anthropic SDK | Anthropic SDK |
| Portability of tools | OpenClaw plugins (non-portable) | MCP servers (portable) | MCP servers (portable) |
| Maintenance burden | High (tracking OpenClaw releases) | Medium (own code) | Low-Medium (Anthropic maintains SDK) |
| Future-proofing | Unknown (project maturity unclear) | Full control | Anthropic's primary agent interface |

---

## 2. What the Claude Agent SDK Gives Us for Free

These are capabilities we would NOT need to build:

### 2.1 Agent Loop (Critical -- saves ~200 lines and ~4 hours)
The `query()` function returns an async iterator that handles the entire tool-use loop: send message, receive tool calls, execute tools, return results, continue until done. This is the most complex piece of Option B that we no longer need to build.

```typescript
// This is the ENTIRE agent loop -- query() handles everything
for await (const message of query({
  prompt: userMessage,
  options: { systemPrompt, mcpServers, agents, hooks }
})) {
  // Stream messages to the web UI
  sendToClient(message);
}
```

### 2.2 Built-in Tools (saves ~3-4 hours)
Read, Write, Edit, Bash, Glob, Grep -- the exact same tools Claude Code uses. These are production-tested and battle-hardened. We get file operations, shell execution, and code search without writing a single line. For the homelab agent, Bash is particularly valuable: `docker ps`, `docker logs`, SSH commands to remote hosts.

### 2.3 Subagent System (saves ~4-6 hours)
Instead of building a router agent that classifies intent and spawns separate sessions, we define subagents declaratively:

```typescript
const agents = [
  {
    name: "personal",
    description: "Daily planning, task management, journaling, ADHD support",
    prompt: personalAgentPrompt,
    tools: ["mcp__obsidian__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write"]
  },
  {
    name: "homelab",
    description: "Server management, Docker, Komodo, Loki log queries",
    prompt: homelabAgentPrompt,
    tools: ["Bash", "mcp__homelab__*", "mcp__memory__*"]
  }
];
```

Claude automatically delegates based on the description field. No keyword matching, no classifier, no routing rules. The LLM does the routing.

### 2.4 Native MCP Integration (saves ~4-6 hours of client code)
MCP servers plug in via configuration -- no client library integration needed:

```typescript
const mcpServers = {
  obsidian: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/obsidian/dist/index.js"],
    env: { OBSIDIAN_API_KEY: process.env.OBSIDIAN_API_KEY }
  },
  memory: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/memory/dist/index.js"],
    env: { MEMORY_DB_PATH: process.env.MEMORY_DB_PATH }
  }
};
```

Tools are automatically namespaced as `mcp__obsidian__search`, `mcp__obsidian__read`, etc. No manual wiring.

### 2.5 Hook System (saves ~2-3 hours)
PreToolUse and PostToolUse are callback functions -- not shell scripts, not plugin events. They run in-process with full type safety:

```typescript
const hooks = {
  preToolUse: async ({ toolName, toolInput, agent }) => {
    // Block credential-revealing patterns
    if (toolName === "Bash" && /cat.*\.env/.test(toolInput.command)) {
      return { decision: "block", reason: "Reading .env files is prohibited" };
    }
    // Log all tool calls to Loki
    await lokiClient.push({
      streams: [{ stream: { job: "corvus", agent: agent.name }, values: [[Date.now(), JSON.stringify({ tool: toolName, input: toolInput })]] }]
    });
    return { decision: "allow" };
  },
  postToolUse: async ({ toolName, toolOutput, agent }) => {
    // Sanitize outputs before they reach the LLM
    return { outputOverride: sanitize(toolOutput) };
  }
};
```

### 2.6 Permission System (saves ~2-3 hours)
Fine-grained tool permissions per agent without custom code:

```typescript
// Per-agent tool restrictions
{
  allowedTools: ["mcp__obsidian__*", "mcp__memory__*"],
  disallowedTools: ["Bash", "Write", "Edit", "WebFetch"]
}
```

Plus dynamic permission modes (acceptEdits, bypassPermissions, plan mode) and a `canUseTool` callback for complex logic.

### 2.7 Session Management (saves ~2-3 hours)
Auto-generated session IDs, resume with `resume: sessionId`, fork with `forkSession: true`. No SQLite session table needed.

### 2.8 Streaming (saves ~1-2 hours)
The async iterator from `query()` provides streaming out of the box. Each message can be forwarded to the web UI via WebSocket as it arrives.

### 2.9 Context Compaction (saves ~2-3 hours)
PreCompact hook lets us archive transcript content before summarization. Built-in compaction prevents context window exhaustion. This replaces OpenClaw's "safeguard" compaction mode AND the entire Slice 20 context compression task.

### 2.10 SDK MCP Server (saves ~2-3 hours per in-process tool set)
`createSdkMcpServer()` lets us define tools that run in the same process as the gateway, with direct access to server-side state. This is ideal for the memory system:

```typescript
const memoryServer = createSdkMcpServer({
  name: "memory",
  version: "1.0.0",
  tools: [
    tool("memory_search", "Search memories by query", { query: z.string() }, async ({ query }) => {
      const results = await hybridSearch(db, query);
      return { content: [{ type: "text", text: JSON.stringify(results) }] };
    }),
    tool("memory_save", "Save a memory", { content: z.string(), tags: z.array(z.string()).optional() }, async ({ content, tags }) => {
      await saveMemory(db, content, tags);
      return { content: [{ type: "text", text: "Memory saved." }] };
    })
  ]
});
```

### Total: ~30-40 hours of build effort eliminated vs. raw SDK

The Agent SDK eliminates most of the "glue" code that was the bulk of Option B. What remains is genuinely unique to our system: the web UI gateway, domain MCP servers, and the memory engine.

---

## 3. What We Still Need to Build

### 3.1 Web UI Gateway Server (~4-6 hours)
The Agent SDK has no web server, no HTTP endpoint, no WebSocket layer. We need:

```
Browser (React chat UI)
    |
    | WebSocket + HTTP
    v
Gateway Server (Express/Fastify)
    |-- POST /api/chat        -> creates query() call, streams responses
    |-- POST /api/sessions     -> manages session list
    |-- POST /api/webhooks/:id -> receives external events (transcripts, email)
    |-- GET  /api/health       -> healthcheck
    |
    | Authelia trusted-proxy header (Remote-User)
    v
Auth middleware (reads X-Remote-User, validates against allowlist)
```

This is the thinnest possible web layer. ~200-300 lines of server code. The React chat UI is additional (~1000-1500 lines for a clean chat interface, or adopt an existing one).

### 3.2 Memory System (~8-12 hours for full parity, ~3-4 hours for MVP)

**The Agent SDK has no built-in memory.** This is the single largest gap.

**MVP approach (3-4 hours):**
- Markdown files on disk (MEMORY.md, evergreen files, daily logs) -- already exist
- CLAUDE.md / systemPrompt injects MEMORY.md content at session start -- replaces boot-md hook
- `memory_search` tool backed by SQLite FTS5 (BM25 text search) -- ~150 lines
- `memory_save` tool appends to daily log and indexes -- ~50 lines
- Reuse existing SQLite database and markdown files (zero migration of content)

**Full parity (8-12 hours):**
- Hybrid search: BM25 (FTS5) + vector search (sqlite-vec) + MMR diversity
- Temporal decay weighting
- Local embeddings (EmbeddingGemma 300M GGUF via node-llama-cpp) -- reuse existing model file
- Session-memory hook equivalent (save context summary on session end)
- Command-logger equivalent (structured audit log)

**Key insight:** The existing SQLite database at `~/.openclaw/memory/main.sqlite` with its `chunks`, `chunks_fts`, and `embedding_cache` tables can be reused directly. The schema is not OpenClaw-proprietary -- it is standard SQLite + FTS5 + sqlite-vec. We can open it from our own code.

**Implementation:** Build as an SDK MCP server (`createSdkMcpServer()`) running in-process for zero-latency access to the database.

### 3.3 Domain MCP Servers (~12-18 hours total)

Each domain needs an MCP server. Some can use community servers, others must be custom.

| MCP Server | Community Available? | Custom Work | Effort |
|-----------|---------------------|-------------|--------|
| Obsidian | Yes (obsidian-mcp) | Vet + configure | 1-2 hours |
| Gmail | Partial (google-gmail-mcp) | May need customization | 2-3 hours |
| Paperless-ngx | No | Build from scratch | 3-4 hours |
| Firefly III | No | Build from scratch | 3-4 hours |
| Homelab (Komodo/Docker/Loki) | No (but built-in Bash covers 80%) | Custom for Komodo API, Loki LogQL | 3-4 hours |
| Home Assistant | Yes (homeassistant-mcp) | Vet + configure + entity restrictions | 2-3 hours |

**Critical realization:** The homelab agent barely needs a custom MCP server. The Agent SDK's built-in `Bash` tool can run `docker ps`, `docker logs`, `ssh patanet7@100.x.y.z "docker compose restart"`, and even `curl` Komodo/Loki APIs. The PreToolUse hook ensures commands are safe. The only custom MCP tools needed are structured wrappers for common operations (e.g., `loki_query` that constructs LogQL properly).

### 3.4 Observability Integration (~2-3 hours)
Wire hooks to existing Grafana/Loki/Alloy stack:
- PostToolUse hook writes structured JSON to a log file
- Alloy tails the log file and ships to Loki (reuse existing Alloy config pattern)
- Grafana dashboard (reuse existing OpenClaw dashboard with modified queries)

### 3.5 Webhook/Event Ingestion (~1-2 hours)
- Transcript watcher fires POST to gateway webhook endpoint
- Gateway creates a new query() call targeting the work subagent
- Same pattern for Gmail PubSub, Paperless events, etc.

### 3.6 Auth Middleware (~1 hour)
- Read `X-Remote-User` header from Authelia (same as current OpenClaw setup)
- Validate against an allowlist
- SWAG proxy config already exists and routes to the gateway

### 3.7 Docker Deployment (~1-2 hours)
- Dockerfile for the gateway + MCP servers
- compose.yaml (replace existing OpenClaw compose)
- Reuse NFS mounts, Docker socket access, memory volumes

### Total build effort: ~28-42 hours

---

## 4. Architecture Design

### 4.1 System Overview

```
                    Internet
                       |
                   [SWAG + Authelia on optiplex]
                       |
                       | X-Remote-User: patanet7
                       v
    +-----------------------------------------+
    |         Gateway Server (laptop-server)   |
    |  Express + WebSocket                     |
    |  - Auth middleware (Authelia header)      |
    |  - Chat API (POST /api/chat)             |
    |  - Session API (GET/POST /api/sessions)  |
    |  - Webhook API (POST /api/webhooks/:id)  |
    |  - Health endpoint (GET /health)         |
    +-------------------+---------------------+
                        |
                        v
    +-----------------------------------------+
    |     Claude Agent SDK Runtime             |
    |                                          |
    |  query() call per chat message           |
    |  - systemPrompt (loaded from CLAUDE.md)  |
    |  - mcpServers (domain tools)             |
    |  - agents (subagent definitions)         |
    |  - hooks (security, logging, memory)     |
    |  - permissions per subagent              |
    |                                          |
    |  Built-in tools:                         |
    |  - Bash (homelab ops, SSH to hosts)      |
    |  - Read/Write/Edit (file operations)     |
    |  - Glob/Grep (code/config search)        |
    |  - WebFetch (optional, restricted)       |
    +---------+------+------+-----------------+
              |      |      |
     stdio    |      |      |  stdio
    +---------+--+ +-+------+-+ +-------------+
    | Obsidian   | | Memory   | | Paperless   |
    | MCP Server | | MCP Srv  | | MCP Server  |
    | (obsidian  | | (in-proc | | (custom)    |
    | community) | | SDK MCP) | |             |
    +------------+ +----------+ +------+------+
                                       |
    +------------+ +----------+ +------+------+
    | Firefly    | | Gmail    | | Home Asst   |
    | MCP Server | | MCP Srv  | | MCP Server  |
    | (custom)   | | (custom) | | (community) |
    +------------+ +----------+ +-------------+
```

### 4.2 Gateway Server Design

```typescript
// gateway/src/server.ts -- ~200-300 lines

import express from 'express';
import { WebSocketServer } from 'ws';
import { query } from '@anthropic-ai/claude-agent-sdk';
import { createServer } from 'http';
import { loadConfig } from './config';
import { authMiddleware } from './auth';
import { buildQueryOptions } from './agents';
import { SessionStore } from './sessions';

const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

// Auth: read X-Remote-User from Authelia
app.use(authMiddleware);

// Health check for Komodo/Docker
app.get('/health', (req, res) => res.json({ status: 'ok' }));

// Chat endpoint (REST fallback)
app.post('/api/chat', async (req, res) => {
  const { message, sessionId } = req.body;
  const user = req.headers['x-remote-user'];
  const options = buildQueryOptions(user, sessionId);

  const messages = [];
  for await (const msg of query({ prompt: message, ...options })) {
    messages.push(msg);
  }
  res.json({ messages, sessionId: options.sessionId });
});

// WebSocket for streaming
wss.on('connection', (ws, req) => {
  const user = req.headers['x-remote-user'];
  if (!user) { ws.close(4401, 'Unauthorized'); return; }

  ws.on('message', async (data) => {
    const { message, sessionId } = JSON.parse(data.toString());
    const options = buildQueryOptions(user, sessionId);

    for await (const msg of query({ prompt: message, ...options })) {
      ws.send(JSON.stringify(msg));
    }
    ws.send(JSON.stringify({ type: 'done', sessionId: options.sessionId }));
  });
});

// Webhook endpoint for transcript ingestion, email events, etc.
app.post('/api/webhooks/:type', async (req, res) => {
  const { type } = req.params;
  const { agentId, message } = req.body;
  // Validate webhook token
  // Create a new query() targeting the specified subagent
  // ...
  res.json({ status: 'accepted' });
});

server.listen(18789, '0.0.0.0');
```

### 4.3 Subagent Definitions

Each domain agent is a subagent definition -- a JavaScript object with a description, system prompt, and tool restrictions. No separate processes, no separate configs, no JSON files to manage.

```typescript
// gateway/src/agents.ts

import { readFileSync } from 'fs';

const personalPrompt = readFileSync('./prompts/personal.md', 'utf-8');
const workPrompt = readFileSync('./prompts/work.md', 'utf-8');
const homelabPrompt = readFileSync('./prompts/homelab.md', 'utf-8');
const financePrompt = readFileSync('./prompts/finance.md', 'utf-8');
const emailPrompt = readFileSync('./prompts/email.md', 'utf-8');
const docsPrompt = readFileSync('./prompts/docs.md', 'utf-8');
const musicPrompt = readFileSync('./prompts/music.md', 'utf-8');
const homePrompt = readFileSync('./prompts/home.md', 'utf-8');

export const agents = [
  {
    name: "personal",
    description: "Daily planning, task management, journaling, ADHD support, stray thought capture, health notes",
    prompt: personalPrompt,
    allowedTools: ["mcp__obsidian__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "WebFetch", "WebSearch"]
  },
  {
    name: "work",
    description: "Work projects, meeting notes, transcript processing, professional task management",
    prompt: workPrompt,
    allowedTools: ["mcp__obsidian__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "WebFetch", "WebSearch"]
  },
  {
    name: "homelab",
    description: "Server management, Docker containers, Komodo fleet, Loki log queries, Tailscale network, system monitoring and troubleshooting",
    prompt: homelabPrompt,
    allowedTools: ["Bash", "Read", "Grep", "Glob", "mcp__homelab__*", "mcp__memory__*"],
    disallowedTools: ["WebFetch", "WebSearch"]
  },
  {
    name: "finance",
    description: "Personal finance, Firefly III transactions, budgets, spending reports, invoice processing",
    prompt: financePrompt,
    allowedTools: ["mcp__firefly__*", "mcp__paperless__search", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch"]
  },
  {
    name: "email",
    description: "Gmail triage, inbox management, email categorization, confirm-gated send and archive",
    prompt: emailPrompt,
    allowedTools: ["mcp__gmail__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch"]
  },
  {
    name: "docs",
    description: "Document management, Paperless-ngx search, document tagging, OCR, invoice filing",
    prompt: docsPrompt,
    allowedTools: ["mcp__paperless__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch"]
  },
  {
    name: "music",
    description: "Music practice planning, repertoire tracking, practice logging, music coaching",
    prompt: musicPrompt,
    allowedTools: ["mcp__obsidian__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "WebFetch", "WebSearch"]
  },
  {
    name: "home",
    description: "Smart home control, Home Assistant devices, lights, thermostat, sensors, scenes",
    prompt: homePrompt,
    allowedTools: ["mcp__homeassistant__*", "mcp__memory__*"],
    disallowedTools: ["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch"]
  }
];
```

### 4.4 MCP Server Configuration

```typescript
// gateway/src/mcp-config.ts

export const mcpServers = {
  // Community MCP server for Obsidian
  obsidian: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/obsidian/dist/index.js"],
    env: {
      OBSIDIAN_API_KEY: process.env.OBSIDIAN_API_KEY,
      OBSIDIAN_URL: process.env.OBSIDIAN_URL || "https://127.0.0.1:27124"
    }
  },

  // In-process memory server (SDK MCP server for zero-latency)
  memory: {
    // Created via createSdkMcpServer() -- see memory section
  },

  // Custom Paperless-ngx MCP server
  paperless: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/paperless/dist/index.js"],
    env: {
      PAPERLESS_API_TOKEN: process.env.PAPERLESS_API_TOKEN,
      PAPERLESS_URL: process.env.PAPERLESS_URL || "http://192.168.1.165:8010"
    }
  },

  // Custom Firefly III MCP server
  firefly: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/firefly/dist/index.js"],
    env: {
      FIREFLY_API_TOKEN: process.env.FIREFLY_API_TOKEN,
      FIREFLY_URL: process.env.FIREFLY_URL || "http://192.168.1.165:8080"
    }
  },

  // Custom Gmail MCP server
  gmail: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/gmail/dist/index.js"],
    env: {
      GMAIL_ADDRESS: process.env.GMAIL_ADDRESS,
      GMAIL_APP_PASSWORD: process.env.GMAIL_APP_PASSWORD
    }
  },

  // Community Home Assistant MCP server
  homeassistant: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/homeassistant/dist/index.js"],
    env: {
      HA_TOKEN: process.env.HA_TOKEN,
      HA_URL: process.env.HA_URL || "http://homeassistant.local:8123"
    }
  },

  // Custom homelab MCP server (Komodo API, Loki LogQL wrappers)
  homelab: {
    type: "stdio",
    command: "node",
    args: ["./mcp-servers/homelab/dist/index.js"],
    env: {
      KOMODO_API_KEY: process.env.KOMODO_API_KEY,
      KOMODO_URL: process.env.KOMODO_URL,
      LOKI_URL: process.env.LOKI_URL || "http://127.0.0.1:3100"
    }
  }
};
```

### 4.5 Memory Architecture

The memory system is the most critical custom component. It must:
1. Load MEMORY.md and evergreen files into the system prompt at session start
2. Provide `memory_search` and `memory_save` tools
3. Support hybrid search (BM25 + vector) for recall quality
4. Auto-index new memories and daily logs
5. Preserve the existing SQLite database and markdown files

**Design: In-process SDK MCP server**

```typescript
// gateway/src/memory-server.ts

import { createSdkMcpServer, tool } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';
import Database from 'better-sqlite3';
import { readFileSync, appendFileSync, readdirSync } from 'fs';

const MEMORY_DIR = process.env.MEMORY_DIR || '/home/node/.openclaw/workspace/memory';
const MEMORY_DB = process.env.MEMORY_DB || '/home/node/.openclaw/memory/main.sqlite';

// Open existing SQLite database (reuse OpenClaw's)
const db = new Database(MEMORY_DB);

export const memoryMcpServer = createSdkMcpServer({
  name: "memory",
  version: "1.0.0",
  tools: [
    tool(
      "memory_search",
      "Search memories using hybrid BM25 + vector search. Returns relevant memory fragments ranked by relevance and recency.",
      { query: z.string(), limit: z.number().optional().default(10) },
      async ({ query, limit }) => {
        // BM25 search via FTS5
        const ftsResults = db.prepare(`
          SELECT c.id, c.content, c.file_path, c.created_at,
                 rank AS bm25_score
          FROM chunks_fts
          JOIN chunks c ON chunks_fts.rowid = c.id
          WHERE chunks_fts MATCH ?
          ORDER BY rank
          LIMIT ?
        `).all(query, limit * 2);

        // Vector search via sqlite-vec (if available)
        // ... embed query, search embedding_cache ...

        // Merge and re-rank with MMR + temporal decay
        // ... (reuse existing algorithm) ...

        return {
          content: [{
            type: "text",
            text: JSON.stringify(ftsResults.slice(0, limit), null, 2)
          }]
        };
      }
    ),
    tool(
      "memory_save",
      "Save a new memory to the daily log. Use for important facts, decisions, and context that should persist across sessions.",
      {
        content: z.string(),
        tags: z.array(z.string()).optional()
      },
      async ({ content, tags }) => {
        const today = new Date().toISOString().split('T')[0];
        const dailyLog = `${MEMORY_DIR}/${today}.md`;
        const timestamp = new Date().toISOString();
        const entry = `\n## ${timestamp}\n${content}\n${tags ? `Tags: ${tags.join(', ')}` : ''}\n`;
        appendFileSync(dailyLog, entry);
        // Index into SQLite for search
        // ... chunk and insert ...
        return { content: [{ type: "text", text: `Memory saved to ${today} daily log.` }] };
      }
    ),
    tool(
      "memory_get",
      "Read the contents of a specific memory file by name.",
      { filename: z.string() },
      async ({ filename }) => {
        const filepath = `${MEMORY_DIR}/${filename}`;
        try {
          const content = readFileSync(filepath, 'utf-8');
          return { content: [{ type: "text", text: content }] };
        } catch {
          return { content: [{ type: "text", text: `Memory file not found: ${filename}` }] };
        }
      }
    )
  ]
});
```

**Memory file reuse:** All existing markdown files (MEMORY.md, daily logs, evergreen files) are preserved in place. The SQLite database schema is compatible. Zero content migration.

### 4.6 Security: Hook-Based Credential Protection

```typescript
// gateway/src/hooks.ts

export const hooks = {
  preToolUse: async ({ toolName, toolInput, agent }) => {
    // Block .env file reads (same as current PreToolUse hooks)
    if (toolName === "Bash") {
      const cmd = toolInput.command || '';
      if (/cat\s+.*\.env|head\s+.*\.env|source\s+.*\.env/.test(cmd)) {
        return { decision: "block", reason: "Reading .env files is prohibited." };
      }
    }
    if (toolName === "Read" && /\.env$/.test(toolInput.file_path || '')) {
      return { decision: "block", reason: "Reading .env files is prohibited." };
    }

    // Confirm-gate mutations (email send, email archive, HA callService, transaction create)
    const confirmGatedTools = [
      "mcp__gmail__send",
      "mcp__gmail__archive",
      "mcp__homeassistant__call_service",
      "mcp__firefly__create_transaction",
      "mcp__firefly__apply_rules",
      "mcp__paperless__bulk_edit"
    ];
    if (confirmGatedTools.includes(toolName)) {
      // The subagent system prompts instruct Claude to confirm with the user
      // This hook is the enforcement backstop
      // (Implementation depends on Agent SDK's permission request flow)
    }

    return { decision: "allow" };
  },

  postToolUse: async ({ toolName, toolOutput }) => {
    // Sanitize all MCP tool outputs for credential leakage
    const sanitized = toolOutput
      .replace(/Bearer\s+[A-Za-z0-9+/=._~-]+/g, 'Bearer [REDACTED]')
      .replace(/Authorization:\s*[^\n]+/gi, 'Authorization: [REDACTED]')
      .replace(/token["\s:=]+[A-Za-z0-9+/=._~-]{20,}/gi, 'token: [REDACTED]');

    if (sanitized !== toolOutput) {
      return { outputOverride: sanitized };
    }
  },

  stop: async ({ sessionId, messages }) => {
    // Save session summary to memory (replaces session-memory hook)
    // ... extract key facts, save to daily log ...
  },

  notification: async ({ type, message }) => {
    // Forward to Loki for observability (replaces telemetry plugin)
    // ... push to Alloy/Loki ...
  }
};
```

### 4.7 Credential Isolation Design

**MCP servers provide credential isolation by design.** Each MCP server is a separate process with its own environment variables. The LLM never sees the env vars -- it only sees the tool interface.

```
Gateway Process (no credentials except ANTHROPIC_API_KEY)
    |
    | stdio (JSON-RPC)
    v
Obsidian MCP Server Process
    env: OBSIDIAN_API_KEY=xxxxx  <- only this process sees it

Gmail MCP Server Process
    env: GMAIL_APP_PASSWORD=xxxx  <- only this process sees it

Firefly MCP Server Process
    env: FIREFLY_API_TOKEN=xxxx  <- only this process sees it
```

This is fundamentally more secure than OpenClaw's Capability Broker pattern, where all credentials lived in a single plugin config (openclaw.json). With MCP:
- Compromise of the Obsidian server leaks only the Obsidian key
- No single config file holds all secrets
- Each `.env` entry is scoped to one server process
- The LLM cannot construct a tool call that reveals credentials (tool outputs are sanitized in PostToolUse)

### 4.8 Observability Integration

```
Gateway hooks (PostToolUse, Notification)
    |
    | Write structured JSONL
    v
/var/log/corvus/events.jsonl
    |
    | Alloy tails the file (reuse existing pattern)
    v
Loki (existing instance on laptop-server)
    |
    v
Grafana (existing dashboards, adapt label selectors)
```

Reuse the existing Alloy JSONL tail configuration from the OpenClaw observability setup. Change the file path and container label. Adapt the Grafana dashboard queries from `{container_name="openclaw"}` to `{job="corvus"}`.

### 4.9 Docker Deployment

```yaml
# infra/stacks/laptop-server/corvus/compose.yaml

services:
  corvus-gateway:
    build:
      context: ../../../../  # repo root
      dockerfile: gateway/Dockerfile
    container_name: corvus-gateway
    restart: always
    init: true
    environment:
      NODE_ENV: production
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      MEMORY_DIR: /data/workspace/memory
      MEMORY_DB: /data/memory/main.sqlite
      # MCP server credentials (each forwarded to its server process)
      OBSIDIAN_API_KEY: ${OBSIDIAN_API_KEY}
      OBSIDIAN_URL: ${OBSIDIAN_URL:-https://127.0.0.1:27124}
      GMAIL_ADDRESS: ${GMAIL_ADDRESS}
      GMAIL_APP_PASSWORD: ${GMAIL_APP_PASSWORD}
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      PAPERLESS_URL: ${PAPERLESS_URL:-http://192.168.1.165:8010}
      FIREFLY_API_TOKEN: ${FIREFLY_API_TOKEN}
      FIREFLY_URL: ${FIREFLY_URL:-http://192.168.1.165:8080}
      KOMODO_API_KEY: ${KOMODO_API_KEY}
      KOMODO_URL: ${KOMODO_URL}
      LOKI_URL: ${LOKI_URL:-http://127.0.0.1:3100}
      HA_TOKEN: ${HA_TOKEN}
      HA_URL: ${HA_URL:-http://homeassistant.local:8123}
    volumes:
      - ${DATA_DIR:-/home/patanet7/.openclaw}:/data  # Reuse existing data!
      - /mnt/vaults:/mnt/vaults:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - /usr/bin/docker:/usr/bin/docker:ro
      - /var/log/corvus:/var/log/corvus  # For Alloy to tail
    group_add:
      - "988"  # docker group GID
    ports:
      - "192.168.1.200:18789:18789"
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 1G
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:18789/health').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

**Key point:** The `/data` volume mount points to the EXISTING OpenClaw data directory. The memory database, markdown files, and workspace are reused in place. No data migration needed.

---

## 5. Revised Slice Plan

### What changes from the original Slices 12-20

| Original Slice | Original Effort | New Approach | New Effort | Change |
|---------------|----------------|--------------|------------|--------|
| 12: Capability Broker + Obsidian | ~4 hours | Obsidian MCP server (community or custom) | ~1-2 hours | -50% (no OpenClaw plugin boilerplate, no credential isolation testing -- MCP is isolated by design) |
| 13: Personal Agent | ~2 hours | Subagent definition + system prompt file | ~1 hour | -50% (no openclaw.json editing, no Persona.md in container) |
| 14: Router + Work Agent | ~3 hours | Subagent definitions (router is implicit) | ~1 hour | -67% (Agent SDK does routing automatically via subagent descriptions) |
| 15: Email Agent | ~3 hours | Gmail MCP server + subagent definition | ~2-3 hours | Similar (Gmail MCP still needs building) |
| 16: Paperless Agent | ~3 hours | Paperless MCP server + subagent definition | ~3-4 hours | Similar (custom MCP server) |
| 17: Finance Agent | ~3 hours | Firefly MCP server + subagent definition | ~3-4 hours | Similar (custom MCP server) |
| 18: Homelab Agent | ~4 hours | Homelab MCP server + built-in Bash + subagent | ~2-3 hours | -25% (Bash handles 80% of ops) |
| 19: Remaining Agents | ~3 hours | Music + HA subagents + HA MCP server | ~2-3 hours | Similar |
| 20: Memory Enhancements | ~varies | Context compaction built-in; Cognee is the same work | ~varies | Simpler (compaction is free) |
| NEW: Gateway Server | N/A | Build web server + WebSocket layer | ~4-6 hours | New work |
| NEW: Web UI | N/A | Build React chat UI or adopt existing | ~4-8 hours | New work |
| NEW: Memory MCP Server | N/A | Port memory system to SDK MCP server | ~3-12 hours | New work (replaces Slice 11 dependency) |

### Revised Slice Plan

**Phase 1: Foundation (Days 1-2, ~8-12 hours)**

**Slice 12-NEW: Gateway + Memory + First Subagent**
1. Scaffold the gateway server (Express + WebSocket) -- 2-3 hours
2. Build memory SDK MCP server (MVP: FTS5 search, markdown files, reuse existing DB) -- 3-4 hours
3. Build minimal React chat UI (or adopt Open WebUI as interim) -- 2-4 hours
4. Define personal subagent with ADHD support prompt -- 30 min
5. Deploy behind existing SWAG + Authelia -- 1 hour
6. Verify: chat works, memory persists, auth works

Acceptance: You can talk to a personal assistant at `claw.absolvbass.com` that remembers you.

**Phase 2: Domain Tools (Days 3-5, ~12-16 hours)**

**Slice 13-NEW: Obsidian + Note-Taking Agents**
1. Vet and configure Obsidian MCP server (community) -- 1-2 hours
2. Wire Obsidian tools to personal and work subagents -- 30 min
3. Create Obsidian vault structure on NAS (reuse existing if present) -- 30 min
4. Test daily planning, thought capture, journal workflows -- 1 hour

**Slice 14-NEW: Gmail + Email Agent**
1. Build Gmail MCP server (IMAP/SMTP with imapflow + nodemailer) -- 2-3 hours
2. Define email subagent with triage workflow prompt -- 30 min
3. Test inbox triage, confirm-gated send/archive -- 1 hour

**Slice 15-NEW: Paperless + Firefly + Cross-Domain**
1. Build Paperless-ngx MCP server -- 3-4 hours
2. Build Firefly III MCP server -- 3-4 hours
3. Define docs and finance subagents -- 30 min
4. Test invoice-to-transaction pipeline (Paperless search from finance agent) -- 1 hour

**Phase 3: Infrastructure + Remaining (Days 6-7, ~8-12 hours)**

**Slice 16-NEW: Homelab Agent**
1. Build homelab MCP server (Komodo API wrapper, Loki LogQL wrapper) -- 2-3 hours
2. Define homelab subagent (built-in Bash + custom MCP tools) -- 30 min
3. Test: container status, log queries, SSH to hosts via Bash -- 1 hour

**Slice 17-NEW: Music + Home Automation + Webhooks**
1. Define music subagent (memory + Obsidian only, no new MCP) -- 30 min
2. Vet and configure Home Assistant MCP server (community) -- 1-2 hours
3. Define home subagent with entity allowlist/blocklist in prompt -- 30 min
4. Implement webhook endpoint for transcript ingestion -- 1-2 hours
5. Set up transcript watcher (reuse existing systemd timer pattern) -- 1 hour

**Phase 4: Polish + Observability (Day 8, ~4-6 hours)**

**Slice 18-NEW: Observability + Memory Enhancements**
1. Wire hooks to Loki via Alloy (reuse existing JSONL pattern) -- 1-2 hours
2. Adapt Grafana dashboard -- 1 hour
3. Upgrade memory to full hybrid search (vectors + MMR + temporal decay) -- 4-8 hours (optional, can defer)
4. Cognee integration (same work as Slice 20, if desired) -- varies

### Time Summary

| Phase | Hours | Calendar |
|-------|-------|----------|
| Phase 1: Foundation | 8-12 | Days 1-2 |
| Phase 2: Domain Tools | 12-16 | Days 3-5 |
| Phase 3: Infrastructure + Remaining | 8-12 | Days 6-7 |
| Phase 4: Polish + Observability | 4-6 (base) + 4-8 (optional memory) | Day 8 |
| **Total** | **32-46 hours** (base) | **~8 working days** |
| **Total with full memory parity** | **36-54 hours** | **~9-10 working days** |

---

## 6. Effort Comparison

| Path | Total Effort | What You Get | Ongoing Maintenance |
|------|-------------|--------------|---------------------|
| **OpenClaw (remaining slices)** | ~30 hours | All 8 domain agents, working memory, web UI | High: track OpenClaw releases, fix plugin breakage, learn underdocumented SDK |
| **Raw Claude SDK (previous Option B)** | ~24-34 hours | Same agents, portable MCP tools, own stack | Medium: maintain ~1,600-2,000 lines of custom code |
| **Claude Agent SDK (this proposal)** | ~32-46 hours | Same agents, portable MCP tools, built-in agent loop, own stack | Low-Medium: maintain ~800-1,200 lines of custom code (SDK handles the complex parts) |

### Why Agent SDK effort is higher than raw SDK but better

The raw SDK estimate of 24-34 hours was optimistic. It did not fully account for:
- The agent loop complexity (retries, streaming, error recovery) -- the Agent SDK handles this
- Tool execution edge cases (timeouts, partial results, concurrent tool calls) -- handled
- Session management robustness (resume, fork, cleanup) -- handled
- Permission enforcement consistency -- handled

The Agent SDK estimate of 32-46 hours is more realistic because it includes the web UI build (which the raw SDK estimate deferred) and more detailed MCP server estimates. If you subtract the web UI (4-8 hours), the core system is 24-38 hours -- comparable to the raw SDK but with dramatically less custom code to maintain.

### Lines of code comparison

| Component | Raw SDK | Agent SDK |
|-----------|---------|-----------|
| Agent loop + tool execution | ~200-300 | 0 (built-in) |
| Session management | ~50-100 | 0 (built-in) |
| Routing/subagents | ~200-300 | ~50 (definitions only) |
| Hooks/permissions | ~100-200 | ~100 (callbacks) |
| Gateway server | ~200 | ~200 |
| Web UI | ~1000-1500 | ~1000-1500 |
| Memory system | ~400-600 | ~400-600 |
| MCP servers (total) | ~900-1200 | ~900-1200 |
| **Total** | **~3,050-4,200** | **~2,650-3,650** |
| **Custom code (excl. UI + MCP)** | **~750-1,100** | **~350-550** |

The Agent SDK cuts the custom "glue" code roughly in half while giving us a better-tested, Anthropic-maintained agent loop.

---

## 7. Risks and Tradeoffs

### 7.1 Risks

**R1: Web UI Build Time (Medium)**
The biggest unknown is the web UI. Options:
- Build a minimal React chat UI (~1000-1500 lines, 4-8 hours) -- clean but time investment
- Adopt Open WebUI as interim (1-2 hours setup) -- works but less control
- Use the OpenClaw web UI temporarily while building the replacement -- hybrid approach

Mitigation: Start with Open WebUI or a very minimal custom UI. Polish later.

**R2: Memory System Parity (Medium)**
The hybrid search engine (BM25 + vectors + MMR + temporal decay) is ~400-600 lines. Starting with BM25-only (FTS5) is viable as MVP, but recall quality may degrade for semantic queries.

Mitigation: Start with FTS5 (1-2 hours). The existing SQLite database already has the FTS5 index. Add vector search iteratively. The embedding model and sqlite-vec are already on disk.

**R3: Agent SDK Stability (Low)**
The Claude Agent SDK is relatively new. API changes could require adaptation.

Mitigation: The SDK is Anthropic's official agent runtime. It is in their interest to maintain backward compatibility. Pin to a specific version and upgrade deliberately.

**R4: Subagent Routing Quality (Low-Medium)**
The Agent SDK's automatic subagent delegation relies on the LLM understanding the description field. Misrouting is possible for ambiguous queries.

Mitigation: Write precise, non-overlapping descriptions. Test with the same ambiguity scenarios from Slice 14. The LLM-based routing will likely be BETTER than keyword matching for edge cases.

**R5: Confirm-Gate Enforcement (Medium)**
The Agent SDK does not have a built-in "confirm before executing" mechanism equivalent to OpenClaw's `confirmationRequired: true`. Enforcement relies on:
1. System prompt instructions ("always confirm before sending email")
2. PreToolUse hook (can block if no confirmation detected)
3. Permission mode (`acceptEdits` for mutation tools)

Mitigation: The PreToolUse hook is the enforcement backstop. If the LLM skips confirmation, the hook blocks the tool call. Test thoroughly.

### 7.2 Tradeoffs vs. Staying on OpenClaw

| Dimension | OpenClaw Advantage | Agent SDK Advantage |
|-----------|-------------------|---------------------|
| Time to first working agent | Already working (Slice 11 done) | ~2 days to rebuild foundation |
| Memory quality | Hybrid search running now | Must rebuild (starts with BM25 only) |
| Web UI | Working today | Must build or adopt |
| Tool portability | None (OpenClaw plugins only) | Full (MCP works everywhere) |
| Vendor dependency | OpenClaw project | Anthropic (more stable) |
| Custom code to maintain | OpenClaw plugins (~30h of boilerplate) | Gateway + hooks (~350-550 lines) |
| Future agent additions | openclaw.json + plugin + credential test | System prompt file + MCP server (if new API) |
| Credential isolation | Must test per-credential (Appendix A) | Free by MCP process isolation |
| Community ecosystem | OpenClaw plugins (limited) | MCP servers (growing rapidly) |

### 7.3 What We Lose

1. **The working web UI** -- must replace it (biggest loss)
2. **The hybrid search memory** -- must rebuild (or degrade to BM25 temporarily)
3. **The proven deployment** -- must redeploy and retest
4. **The sandbox enforcement** -- must implement via hooks + Docker (different mechanism)
5. **The specific OpenClaw hooks** (boot-md, session-memory, command-logger) -- must reimplement as Agent SDK hooks

### 7.4 What We Gain

1. **Portable tools** -- MCP servers work with Claude Code, VS Code, Cursor, LangChain, any MCP client
2. **Credential isolation by design** -- no Capability Broker needed, no Appendix A testing per credential
3. **Built-in agent loop** -- battle-tested by Anthropic, handles streaming, retries, tool execution
4. **Automatic routing** -- LLM-based subagent delegation instead of keyword matching
5. **Half the custom code** -- ~350-550 lines of glue vs. ~750-1,100
6. **Full stack ownership** -- no upstream breakage risk from OpenClaw updates
7. **Context compaction** -- built-in, replaces Slice 20 compression task
8. **Future-proofing** -- MCP is the emerging standard; Agent SDK is Anthropic's primary interface

---

## 8. Recommendation

**Build on the Claude Agent SDK.** Replace OpenClaw.

### Reasoning

1. **The Agent SDK addresses the primary weakness of Option B.** The raw SDK required building an agent loop, tool execution, session management, and routing from scratch. The Agent SDK provides all of these, cutting the "glue" code in half while being maintained by Anthropic.

2. **MCP credential isolation eliminates the single riskiest OpenClaw slice.** Slice 12 (Capability Broker) was the security gate -- all subsequent slices depended on it. With MCP, credential isolation is architectural, not implemented. Each MCP server process holds only its own credentials. No `sensitive: true` uiHints, no regex-based output sanitization, no 10-step Appendix A testing per credential. The PostToolUse hook provides defense-in-depth sanitization, but the primary isolation is process-level.

3. **The effort delta is acceptable.** Agent SDK takes ~32-46 hours vs. OpenClaw's ~30 hours remaining. But the OpenClaw path produces non-portable plugins with ongoing maintenance burden. The Agent SDK path produces portable MCP servers and a system with half the custom code.

4. **The web UI is the only hard loss.** The memory system can be rebuilt incrementally (start BM25, add vectors later). The hooks can be reimplemented as callbacks. The sandbox can be enforced via Docker + hooks. The web UI is the only thing that requires a net-new build. Budget 4-8 hours for this.

5. **Every MCP server built is immediately useful.** Even before the gateway is ready, the Obsidian, Homelab, and Memory MCP servers work with Claude Code (the CLI tool you are using right now). This means Phase 1 produces value on day 1.

### Execution Recommendation

**Staged migration, not big bang.**

1. **This week:** Build the gateway server, memory MCP server, and deploy with a minimal UI behind existing SWAG + Authelia. Get the personal agent working.

2. **Next week:** Build the domain MCP servers one at a time. Each one works independently. Test with Claude Code first, then wire into the gateway.

3. **Following week:** Polish the web UI, add observability, upgrade memory to full hybrid search if needed.

4. **Then:** Retire the OpenClaw container. Keep the data directory (it is the same volume mount).

### Decision Criteria Met

- Performance: Agent SDK query() provides streaming with minimal latency overhead
- Cost: Same Anthropic API costs; reduced infrastructure complexity
- Safety: MCP process isolation + PreToolUse hooks + PostToolUse sanitization
- Maintainability: ~350-550 lines of glue code vs. ~750-1,100 for raw SDK or 30+ hours of OpenClaw plugins
- Portability: MCP servers work with any MCP client
- Future-proofing: Anthropic-maintained SDK + industry-standard MCP protocol

---

## Appendix A: Project Structure

```
corvus/
  gateway/
    src/
      server.ts           -- Express + WebSocket gateway (~200-300 lines)
      agents.ts           -- Subagent definitions (~100 lines)
      hooks.ts            -- Security, logging, memory hooks (~150 lines)
      auth.ts             -- Authelia header middleware (~30 lines)
      sessions.ts         -- Session persistence (~50 lines)
      mcp-config.ts       -- MCP server configuration (~80 lines)
      memory-server.ts    -- In-process memory MCP server (~300-500 lines)
    Dockerfile
    package.json
    tsconfig.json

  mcp-servers/
    obsidian/             -- Community MCP server (vendored/configured)
    paperless/
      src/index.ts        -- Custom Paperless-ngx MCP server (~200 lines)
    firefly/
      src/index.ts        -- Custom Firefly III MCP server (~250 lines)
    gmail/
      src/index.ts        -- Custom Gmail MCP server (~300 lines)
    homelab/
      src/index.ts        -- Custom Komodo/Loki MCP server (~200 lines)
    homeassistant/        -- Community MCP server (vendored/configured)

  prompts/
    personal.md           -- Personal agent system prompt (reuse Persona.md content)
    work.md               -- Work agent system prompt
    homelab.md            -- Homelab agent system prompt
    finance.md            -- Finance agent system prompt
    email.md              -- Email agent system prompt
    docs.md               -- Docs agent system prompt
    music.md              -- Music agent system prompt
    home.md               -- Home automation system prompt

  ui/
    src/                  -- React chat UI
      App.tsx
      components/
        ChatWindow.tsx
        MessageList.tsx
        InputBar.tsx
    package.json
    vite.config.ts

  infra/
    stacks/laptop-server/corvus/
      compose.yaml        -- Docker deployment

  docs/
    plans/                -- Planning docs (this file, etc.)
```

## Appendix B: Migration Checklist

- [ ] Scaffold gateway server with Express + WebSocket
- [ ] Implement auth middleware (read X-Remote-User from Authelia)
- [ ] Build memory SDK MCP server (FTS5 search, reuse existing DB)
- [ ] Define personal subagent with ADHD support prompt
- [ ] Build minimal React chat UI (or adopt Open WebUI interim)
- [ ] Create compose.yaml (reuse existing data volume mount)
- [ ] Deploy behind SWAG + Authelia
- [ ] Test: chat works, memory persists, auth works
- [ ] Build/configure Obsidian MCP server
- [ ] Build Gmail MCP server
- [ ] Build Paperless-ngx MCP server
- [ ] Build Firefly III MCP server
- [ ] Build Homelab MCP server (Komodo + Loki wrappers)
- [ ] Configure Home Assistant MCP server
- [ ] Define all 8 subagents with system prompts
- [ ] Wire hooks to Loki via Alloy
- [ ] Adapt Grafana dashboard
- [ ] Implement webhook endpoint for transcript ingestion
- [ ] Test all domain agents end-to-end
- [ ] Security verification: credential isolation (spot-check, not Appendix A per-credential)
- [ ] Retire OpenClaw container
- [ ] Update SWAG proxy config if needed
- [ ] Update Komodo stack reference
- [ ] Commit and push to Forgejo
