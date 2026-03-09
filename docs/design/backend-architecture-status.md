# Backend Architecture Status (Newest Plans First)

Date: 2026-03-03  
Owner: backend

## Source plans

- `docs/plans/2026-03-03-corvus-agent-surfaces-components-plan.md`
- `docs/plans/2026-03-03-backend-modularization-completion.md`
- `docs/plans/2026-03-02-legacy-removal-plan.md`
- `docs/plans/2026-03-01-corvus-hub-architecture-design.md`

## Deduped feature matrix

| Feature area | Status | Backend implementation |
|---|---|---|
| Multi-agent dispatch protocol (`target_agents`, `dispatch_mode`) | Complete | `corvus/api/chat.py`, `docs/design/agent-dispatch-protocol.md` |
| Dispatch/run/event persistence model | Complete | `dispatches`, `agent_runs`, `run_events` in `corvus/session_manager.py` |
| Dispatch/Run CRUD + replay APIs | Complete | `corvus/api/sessions.py` (`/api/dispatch*`, `/api/runs*`) |
| Bounded parallel fan-out for many agents | Complete | `MAX_PARALLEL_AGENT_RUNS` + semaphore in `corvus/api/chat.py` |
| In-flight interrupt handling | Complete (WS dispatch path) | `interrupt_ack`, run interruption states in `corvus/api/chat.py` |
| Hierarchical task decomposition + route planning | Complete | `config/task_routing.yaml`, `corvus/gateway/task_planner.py`, `dispatch_plan` emission in `corvus/api/chat.py` |
| Per-subtask run trace metadata (`task_type`, `subtask_id`, `skill`, `route_index`) | Complete | run lifecycle payloads in `corvus/api/chat.py` + persisted run metadata in `corvus/session_manager.py` |
| Planner-aware webhook/scheduler dispatch | Complete | `corvus/webhooks.py` planner execution + `corvus/scheduler.py` payload-driven dispatch controls |
| Shared non-WS dispatch runtime slice | Complete | `corvus/gateway/background_dispatch.py` reused by webhook + scheduler paths |
| Session persistence service split | Complete | `corvus/sessions/{schema,repositories,serializers}.py` + `SessionManager` facade |
| Session app service (user-scoped CRUD/access) | Complete | `corvus/sessions/service.py` + `corvus/api/sessions.py` integration |
| Shared dispatch runtime executor | Complete | `corvus/gateway/dispatch_runtime.py` reused by chat + background dispatch |
| Agents app service (enriched status/model/queue) | Complete | `corvus/agents/service.py` + `corvus/api/agents.py` integration |
| Per-agent model/backend routing | Complete | `corvus/model_router.py`, `corvus/gateway/options.py`, `corvus/client_pool.py` |
| Abstracted tool registry/security boundaries | Complete | `corvus/capabilities/registry.py`, `corvus/agents/hub.py` |
| Secret-protection on tool calls | Complete | `corvus/hooks.py` env/secret blocking + sanitize pipeline |
| Break-glass override for secret-block hooks | Complete (session-scoped API + env fallback) | `corvus/api/control.py`, `corvus/gateway/control_plane.py`, `corvus/gateway/options.py` |
| Frontend parity contracts for init/sessions/models/ws | Complete | `tests/gateway/test_frontend_backend_contracts.py` |
| Observability for dispatch/run lifecycle | Complete | event emission + replay endpoints + persisted run/session events |
| `/api/dispatch/active` route conflict guard | Complete | static route in `corvus/api/sessions.py` + regression test in `tests/gateway/test_dispatch_api.py` |
| Shared dispatch metrics aggregation | Complete | `corvus/gateway/dispatch_metrics.py` reused by chat + background dispatch paths |

## Remaining high-impact backend gaps

1. WS reconnect/rollback protocol for partial streams is not yet implemented end-to-end.
2. Autonomous long-running agent orchestration (background run queue + durable runner) is not yet first-class.
3. Cross-process dispatch interruption is not yet implemented (current control plane is per runtime instance).
4. Agent isolation still needs stronger execution sandbox partitioning per agent workspace/process.

## Next execution order

1. Add durable background run runner for autonomous tasks (separate from active WS request loop).
2. Add reconnect cursor protocol for streamed `run_output_chunk` replay continuity.
3. Add shared interrupt bus for multi-worker/multi-process deployments.
4. Add stricter per-agent sandbox/permission profiles with dedicated workdirs.
