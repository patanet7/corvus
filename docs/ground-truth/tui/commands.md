---
subsystem: tui/commands
last_verified: 2026-03-09
---

# TUI Command System

The TUI command system uses a three-tier classification (InputTier: SYSTEM, SERVICE, AGENT) with a CommandRegistry mapping slash-command names to SlashCommand definitions. CommandRouter classifies ParsedInput by looking up the command name in the registry; unknown commands and all non-command input (chat, mentions, tool calls) route to AGENT tier. Three handler classes own all dispatch logic.

## Ground Truths

- InputParser classifies raw input into 4 kinds: `command` (`/`-prefixed), `tool_call` (`!`-prefixed), `mention` (`@`-prefixed with known agent), `chat` (default).
- Bare `@agent` with no text is rewritten to a `/agent` switch command by the parser.
- SlashCommand dataclass: `name`, `description`, `tier`, `handler` (optional), `args_spec` (optional), `agent_scoped` (bool).
- **SYSTEM tier** (15 commands): help, quit, agents, agent, models, model, reload, setup, breakglass, focus, split, theme, login, panel, config. Handled by `SystemCommandHandler`.
- **SERVICE tier** (14 commands): sessions, session, memory, tools, tool, tool-history, view, edit, diff, workers, tokens, status, export, audit, policy. Handled by `ServiceCommandHandler`.
- **AGENT tier** (6 commands): spawn, enter, back, top, summon, kill. Handled by `AgentCommandHandler`. All are `agent_scoped=True`.
- SystemCommandHandler manages break-glass lifecycle (HMAC-SHA256 tokens with TTL cap), theme switching (deferred to app for renderer rebuild), login flow (pending token state for WebSocket auth), and split-pane mode.
- ServiceCommandHandler uses interactive Screen classes (AgentScreen, MemoryScreen, SessionScreen, ToolScreen, WorkerScreen, SetupScreen) for rich output.
- AgentCommandHandler manipulates AgentStack: push/pop/enter/spawn/kill for nested agent navigation with breadcrumb display.
- `/spawn <agent> "task"` spawns a background child and forwards the task text to the agent via gateway.
- Tool confirmation flow: pending confirm state in EventHandler; user responds with y(es), n(o), or a(lways) to approve/deny/always-allow.

## Boundaries

- **Depends on:** `corvus.tui.commands.registry`, `corvus.tui.input.parser`, `corvus.tui.core.command_router`, `corvus.tui.core.agent_stack`, `corvus.tui.protocol.base.GatewayProtocol`
- **Consumed by:** `corvus.tui.app.TuiApp` (main loop dispatch)
- **Does NOT:** execute agent runs, manage gateway connections, or handle streaming event rendering
