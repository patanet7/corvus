---
subsystem: gateway/routing
last_verified: 2026-03-09
---

# Agent Routing and Dispatch

Agent routing resolves which domain agent(s) handle a user message. It spans two stages: intent classification (RouterAgent) and task planning (TaskPlanner). The resolution pipeline lives in `corvus/gateway/chat_engine.py` and produces a `ChatDispatchResolution` consumed by the dispatch orchestrator.

## Ground Truths

- Three dispatch modes exist: `router` (backend chooses agent via classification), `direct` (explicit single target), `parallel` (fan-out to multiple agents).
- `RouterAgent` (`corvus/router.py`) uses Claude Haiku via direct Anthropic API call (not the SDK) for speed. Default model: `claude-haiku-4-5-20251001`.
- `RouterAgent.classify()` returns a single agent name; falls back to `"general"` on rate limit, connection error, or unexpected failure. Authentication errors are re-raised.
- `RouterAgent` builds its routing prompt dynamically from `AgentRegistry.list_enabled()` when a registry is attached; otherwise uses a hardcoded fallback prompt.
- `resolve_chat_dispatch()` in `chat_engine.py` handles: `target_agents` list (wins over `target_agent`), `@all` expansion, case-insensitive agent lookup, deduplication, and validation against enabled agents.
- If no explicit agent is requested, `resolve_chat_dispatch` calls `router_agent.classify()` for intent classification.
- `TaskPlanner` (`corvus/gateway/task_planner.py`) reads `config/task_routing.yaml` for decomposition rules. It detects task types via keyword matching and optionally decomposes into subtask routes.
- Each `TaskRoute` carries: `agent`, `prompt`, `requested_model`, `task_type`, `subtask_id`, `skill`, `instruction`.
- `DispatchPlan` includes: `task_type`, `decomposed` (bool), `strategy` ("direct" or "parallel"), `routes` list, `rationale`.
- `dispatch_mode="direct"` truncates to the first route if multiple exist.
- Per-agent model/backend resolution happens in `run_executor.py` via `resolve_backend_and_model()`, not during routing.
- Parallel dispatch is bounded by `MAX_PARALLEL_AGENT_RUNS` with semaphore enforcement in `dispatch_runtime.py`.

## Boundaries

- **Depends on:** `corvus/router.py` (RouterAgent), `corvus/agents/registry.py` (AgentRegistry), `config/task_routing.yaml`, `corvus/model_router.py`
- **Consumed by:** `ChatSession`, `DispatchOrchestrator`, `background_dispatch`
- **Does NOT:** execute agent runs, manage SDK clients, persist events
