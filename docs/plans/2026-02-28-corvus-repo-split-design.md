# Corvus Repo Split — Design Doc

> **Date:** 2026-02-28
> **Status:** Approved
> **Scope:** Split the current monorepo into a public `corvus` framework and a private `corvus-infra` deployment repo. Introduce a plugin architecture for tools and memory, a setup wizard for onboarding, and hot-loading for runtime plugin management.

---

## Decision Summary

| Decision | Choice |
|----------|--------|
| Project name | **Corvus** (Latin: crow — intelligent, tool-using, security-aware) |
| Split strategy | **Approach A** — Corvus is the full running server; private repo is config + infra overlay |
| Tool integrations | **Plugin system** — no domain tools built into core; each is an installable plugin |
| Memory architecture | **Pluggable** — `MemoryBackend` protocol with base SQLite FTS5 built in; others as plugins |
| Prompts | **Example templates** — ship generic `.md.example` files; users customize |
| Plugin loading | **Hot-loaded** — add/remove/reload plugins at runtime without restart |
| Subsystem branding | **Huginn** (routing/agents) + **Muninn** (memory) — branding in docs/README only, not in code |
| Private repo relationship | Config directory + infra mounted into Corvus via env var or Docker volume |

---

## 1. Repository Structure

### Public: `corvus` (GitHub, open source)

The full server — clone, configure, run.

```
corvus/
├── corvus/                          # Python package — the server
│   ├── __init__.py
│   ├── server.py                    # FastAPI + WebSocket gateway
│   ├── router.py                    # Intent classification → agent dispatch
│   ├── session.py                   # Session management
│   ├── auth.py                      # Auth framework (pluggable: Authelia, basic, none)
│   ├── events.py                    # Event emitter
│   ├── hooks.py                     # Lifecycle hooks + confirm-gating
│   ├── supervisor.py                # Agent supervisor / heartbeat
│   ├── scheduler.py                 # Cron scheduler (APScheduler)
│   ├── sanitize.py                  # Credential sanitization (never exposes secrets)
│   ├── memory_backends.py           # MemoryEngine (fan-out) + MemoryBackend Protocol
│   ├── model_router.py              # Multi-model routing (Claude, OpenAI, Ollama, etc.)
│   ├── agent_config.py              # Agent config loader (reads from user config dir)
│   ├── config.py                    # Config loader (env vars + CORVUS_CONFIG_DIR)
│   ├── providers/                   # Model provider adapters
│   │   ├── __init__.py
│   │   └── registry.py
│   ├── plugins/                     # Plugin system
│   │   ├── __init__.py
│   │   ├── base.py                  # ToolPlugin ABC + MemoryPlugin ABC
│   │   ├── loader.py                # Discovery, init, hot-load, lifecycle
│   │   └── registry.py              # Runtime plugin registry
│   └── prompts/                     # Example/template prompts
│       ├── README.md                # "How to write agent prompts"
│       └── examples/
│           ├── personal.md.example
│           ├── work.md.example
│           ├── homelab.md.example
│           ├── finance.md.example
│           ├── email.md.example
│           ├── docs.md.example
│           ├── music.md.example
│           ├── home.md.example
│           └── general.md.example
├── plugins/                         # First-party plugins (each a small pip-installable package)
│   ├── corvus-memory-sqlite/        # Built-in: SQLite FTS5 (default, ships with core)
│   ├── corvus-memory-cognee/        # Optional: Cognee graph-backed recall
│   ├── corvus-memory-obsidian/      # Optional: Obsidian vault as memory store
│   ├── corvus-memory-pgvector/      # Optional: PostgreSQL + pgvector
│   ├── corvus-obsidian/             # Tool plugin: obsidian.search/read/write/append
│   ├── corvus-email/                # Tool plugin: Gmail/Yahoo email tools
│   ├── corvus-paperless/            # Tool plugin: Paperless-ngx document tools
│   ├── corvus-firefly/              # Tool plugin: Firefly III finance tools
│   ├── corvus-ha/                   # Tool plugin: Home Assistant tools
│   └── corvus-drive/                # Tool plugin: Google Drive tools
├── scripts/                         # Utility scripts (generic)
│   └── common/
│       ├── vault_writer.py
│       ├── memory_engine.py
│       └── cognee_engine.py
├── tests/
│   ├── contracts/
│   ├── gateway/
│   ├── integration/
│   └── plugins/                     # Plugin-specific tests
├── config.example/                  # User copies this to start
│   ├── corvus.yaml                  # Main config (agents, auth, plugins)
│   ├── models.yaml                  # Model assignments per agent
│   ├── schedules.yaml               # Cron schedules
│   └── prompts/                     # Copied from examples, user customizes
├── corvus-setup                     # Interactive CLI setup wizard
├── Dockerfile
├── docker-compose.yaml
├── pyproject.toml
├── README.md
└── LICENSE
```

### Private: `corvus-infra` (Forgejo, private)

Your personal deployment — config, infra, secrets.

```
corvus-infra/
├── config/                          # YOUR runtime config (mounted into Corvus)
│   ├── corvus.yaml                  # Your enabled agents, plugins, auth settings
│   ├── models.yaml                  # Your model assignments (sonnet, haiku, opus)
│   ├── schedules.yaml               # Your morning briefing, EOD review, weekly review
│   └── prompts/                     # Your actual personas
│       ├── personal.md              # "You are Thomas's assistant, has ADHD..."
│       ├── work.md
│       ├── homelab.md
│       ├── finance.md
│       ├── email.md
│       ├── docs.md
│       ├── music.md
│       ├── home.md
│       └── general.md
├── infra/                           # Infrastructure management
│   ├── stacks/                      # Docker Compose files per host
│   │   ├── laptop-server/
│   │   ├── miniserver/
│   │   └── optiplex/
│   ├── scripts/                     # Deployment scripts
│   ├── procedures/                  # Runbooks (secret rotation, OS updates)
│   ├── observability/               # Alloy configs, Grafana dashboards
│   └── docs/                        # Fleet inventory, backup strategy, NFS guide
├── docs/                            # Personal project docs, plans, memory
│   ├── plans/
│   ├── claude-memory/
│   └── ...
├── docker-compose.override.yaml     # Mounts config/ into the Corvus container
├── .sops.yaml                       # SOPS encryption config
├── .forgejo/                        # CI workflows
├── renovate.json
├── CLAUDE.md                        # Personal Claude Code instructions
└── ARCHITECTURE.md                  # Your deployment-specific architecture notes
```

### How they connect:

```yaml
# docker-compose.override.yaml (in corvus-infra)
services:
  corvus:
    volumes:
      - ./config:/config:ro
    environment:
      - CORVUS_CONFIG_DIR=/config
```

Or for local dev: `CORVUS_CONFIG_DIR=../corvus-infra/config corvus serve`

---

## 2. Plugin Architecture

### Plugin types

**Tool Plugins** — expose typed tools that agents can call:
```python
class ToolPlugin(ABC):
    name: str                           # e.g., "corvus-obsidian"
    tools: list[ToolDefinition]         # Tools this plugin provides

    @abstractmethod
    async def initialize(self, config: dict) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...

    @classmethod
    def compose_manifest(cls) -> ComposeManifest | None:
        """Return Docker Compose service definition for the backing service.

        Returns None if this plugin doesn't need a backing container
        (e.g., it only calls an external API the user already runs).
        The setup wizard uses this to generate docker-compose.yaml.
        """
        return None
```

**ComposeManifest** — describes how to run the backing service:
```python
@dataclass
class ComposeManifest:
    service_name: str                   # e.g., "paperless"
    image: str                          # e.g., "ghcr.io/paperless-ngx/paperless-ngx:latest"
    ports: list[str]                    # e.g., ["8000:8000"]
    volumes: list[str]                  # e.g., ["paperless-data:/usr/src/paperless/data"]
    environment: dict[str, str]         # Default env vars
    depends_on: list[str]              # Other compose services this needs
    description: str                    # Human-readable for wizard display
    health_check: str | None           # e.g., "curl -f http://localhost:8000/api/"
    env_keys_required: list[str]       # e.g., ["PAPERLESS_API_TOKEN"] — wizard prompts for these
    connection_config: dict[str, str]  # Config fields auto-set when compose is used
                                       # e.g., {"url": "http://paperless:8000"}
```

**Memory Plugins** — implement the `MemoryBackend` protocol:
```python
class MemoryPlugin(ABC):
    name: str                           # e.g., "corvus-memory-cognee"

    @abstractmethod
    async def initialize(self, config: dict) -> None: ...

    @abstractmethod
    async def save(self, content: str, domain: str, tags: list[str], importance: float, **kwargs) -> None: ...

    @abstractmethod
    async def search(self, query: str, limit: int, domain: str | None) -> list[MemoryResult]: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...

    @abstractmethod
    async def shutdown(self) -> None: ...
```

### Plugin discovery

Plugins register via Python entry points:
```toml
# In a plugin's pyproject.toml
[project.entry-points."corvus.plugins.tools"]
obsidian = "corvus_obsidian:ObsidianPlugin"

[project.entry-points."corvus.plugins.memory"]
cognee = "corvus_memory_cognee:CogneeMemoryPlugin"
```

The loader scans entry points at startup, cross-references with `corvus.yaml` to determine which are enabled, and initializes them.

### Hot-loading

Plugins can be loaded, unloaded, and reloaded at runtime:

```
POST /admin/plugins/reload          — Re-scan config, load new, unload removed
GET  /admin/plugins                 — List loaded plugins + health status
POST /admin/plugins/{name}/enable   — Enable a plugin (loads it)
POST /admin/plugins/{name}/disable  — Disable a plugin (unloads it)
```

On reload:
1. Read `corvus.yaml` (or receive config via API)
2. Diff current loaded plugins vs. new config
3. Call `shutdown()` on removed plugins, deregister their tools/memory backends
4. Call `initialize()` on new plugins, register their tools/memory backends
5. Existing plugins with changed config: `shutdown()` → `initialize()` with new config

File watcher on `corvus.yaml` triggers auto-reload (optional, configurable).

### Memory fan-out

The `MemoryEngine` writes to ALL enabled memory backends and merges search results:
- **Writes:** Fan out to all backends (SQLite + Cognee + Obsidian, etc.)
- **Reads:** Query all backends, merge + deduplicate + rank by score
- **Base memory (SQLite FTS5):** Always enabled, cannot be disabled. Ships with core.

---

## 3. Setup Wizard (`corvus setup`)

Interactive CLI for first-time onboarding. NOT the credential store / SOPS / break-glass system (that's a separate subsystem).

```
$ corvus setup

Welcome to Corvus — security-first multi-agent system.

Step 1/6: Agent Selection
  Which agents do you want to enable?
  [x] personal    — Daily planning, tasks, journaling
  [x] work        — Work context, meetings, projects
  [x] finance     — Firefly III integration
  [ ] homelab     — Docker/infra management
  [x] email       — Gmail/Yahoo integration
  [ ] docs        — Paperless-ngx document management
  [ ] music       — Music library management
  [ ] home        — Home Assistant integration

Step 2/6: Model Configuration
  Default model provider:
  (1) Claude (Anthropic) — requires ANTHROPIC_API_KEY
  (2) OpenAI — requires OPENAI_API_KEY
  (3) Local Ollama — free, private, lower quality
  (4) Custom endpoint
  > 1

Step 3/6: Memory Setup
  Base memory (SQLite FTS5) is always enabled.
  Additional memory backends:
  [x] Obsidian vault — canonical markdown store
  [ ] Cognee — graph-backed semantic recall
  [ ] PostgreSQL + pgvector — vector search

Step 4/6: Service Configuration
  Your selections require these backing services:

  corvus-obsidian → Obsidian Remote (REST API for Obsidian vault)
    (1) Deploy with Corvus — add to docker-compose.yaml (port 27124)
    (2) Use existing — I already run Obsidian Remote
    > 1 ✓ Will add obsidian-remote to docker-compose.yaml

  corvus-firefly → Firefly III (personal finance manager)
    (1) Deploy with Corvus — add to docker-compose.yaml (port 8080)
    (2) Use existing — I already run Firefly III
    > 2
    Firefly III URL: http://192.168.1.165:8080
    ✓ Will connect to your existing Firefly III

  corvus-email → No backing service needed (uses Gmail/Yahoo APIs directly)
    ✓ Nothing to deploy

Step 5/6: Plugin Installation
  Installing: corvus-obsidian, corvus-firefly, corvus-email,
              corvus-memory-obsidian
  Installing... done.

Step 6/6: Prompt Templates + Compose Generation
  Generated config/prompts/ for: personal, work, finance, email
  Generated config/corvus.yaml
  Generated config/models.yaml
  Generated config/schedules.yaml
  Generated docker-compose.yaml

  ┌─────────────────────────────────────────────────────┐
  │ docker-compose.yaml                                 │
  │                                                     │
  │ services:                                           │
  │   corvus        — port 18789  (gateway)             │
  │   obsidian      — port 27124  (Obsidian Remote)     │
  │   redis         — port 6379   (session store)       │
  │                                                     │
  │ External connections:                               │
  │   Firefly III   → http://192.168.1.165:8080         │
  │                                                     │
  │ Volumes: corvus-data, obsidian-vault                │
  └─────────────────────────────────────────────────────┘

Setup complete!
  → Edit config/prompts/*.md to customize your agent personas
  → Add API keys to .env (template generated at .env.example)
  → Run: docker compose up -d
```

### Generated files:
- `config/corvus.yaml` — agents, plugins, auth, memory backends
- `config/models.yaml` — model assignments per agent
- `config/schedules.yaml` — default cron schedules
- `config/prompts/*.md` — customizable agent persona templates
- `docker-compose.yaml` — Corvus + all selected backing services
- `.env.example` — required env vars (API keys, tokens) with placeholder values

### How compose generation works:

Each plugin declares a `compose_manifest()` classmethod that returns the Docker service definition for its backing service (image, ports, volumes, env vars, healthcheck). During setup:

1. Wizard collects which plugins are enabled
2. For each plugin with a `compose_manifest()`, asks: deploy with Corvus or use existing?
3. If **deploy**: adds the service from the manifest to `docker-compose.yaml`, auto-wires the connection config (e.g., `url: http://paperless:8000` using Docker network DNS)
4. If **use existing**: prompts for the URL/port, writes it to `corvus.yaml` plugin config
5. If **no backing service**: skips (plugin only needs API keys, no container)
6. Generates the final `docker-compose.yaml` with all services, correct ports, volumes, and inter-service networking

Port conflicts are detected automatically — if the user's host already uses port 8000, the wizard suggests an alternative (8001, etc.).

### Re-running setup:

`corvus setup` can be re-run at any time. It detects existing config and offers:
- **Add plugins** — enable new plugins, add their services to compose
- **Remove plugins** — disable plugins, remove their compose services
- **Reconfigure** — change model provider, memory backends, etc.
- **Regenerate compose** — rebuild docker-compose.yaml from current config

Existing customizations (edited prompts, tweaked compose settings) are preserved — the wizard only touches sections it manages, marked with `# managed by corvus setup` comments.

---

## 4. Branding: Huginn & Muninn

Odin's two ravens — **Huginn** (thought) and **Muninn** (memory) — serve as conceptual names for Corvus's two core subsystems.

Used in: README, architecture docs, diagrams, marketing.
NOT used in: code, file names, module paths, plugin names.

- **Huginn** — The routing and agent orchestration layer. Intent classification, agent dispatch, model selection, tool policy enforcement, confirm-gating.
- **Muninn** — The memory and knowledge layer. Pluggable memory backends, semantic search, vault storage, session fact extraction, cross-domain recall.

---

## 5. Config Loading Order

Corvus resolves config with this precedence (highest wins):

1. **Environment variables** — `CORVUS_*` prefix overrides everything
2. **`corvus.yaml`** in `CORVUS_CONFIG_DIR` — user's main config
3. **`config.example/`** defaults — shipped with Corvus, used if no user config exists

Config dir discovery:
1. `CORVUS_CONFIG_DIR` env var (explicit path)
2. `./config/` relative to CWD
3. `~/.corvus/config/` (user home)
4. Fall back to built-in defaults

---

## 6. Migration Path (Current Repo → Split)

### Phase 1: Prepare Corvus public repo
1. Rename `corvus/` → `corvus/` (Python module)
2. Update all imports, pyproject.toml, Dockerfile, compose
3. Extract personal data from prompts → example templates
4. Extract personal config (models.yaml, schedules.yaml) → `config.example/`
5. Remove hardcoded values from `config.py` (patanet7, specific URLs)
6. Implement plugin base classes and loader
7. Extract each tool (obsidian, email, etc.) into plugin packages
8. Extract SQLite FTS5 into `corvus-memory-sqlite` plugin
9. Build setup wizard CLI
10. Write README with Huginn/Muninn branding

### Phase 2: Create corvus-infra private repo
1. Init new repo on Forgejo
2. Move `infra/` tree
3. Move `docs/plans/`, `docs/claude-memory/`
4. Create `config/` with your real prompts, models.yaml, schedules.yaml
5. Create `docker-compose.override.yaml` that mounts config into Corvus
6. Move `.sops.yaml`, `.forgejo/`, `renovate.json`
7. Update CLAUDE.md for the private repo context

### Phase 3: Verify
1. Corvus public repo runs standalone with `corvus setup` → `corvus serve`
2. Your private deployment works with `CORVUS_CONFIG_DIR` pointed at corvus-infra/config
3. All tests pass in both repos
4. No personal data remains in public repo (audit)
5. Hot-loading works for plugins
