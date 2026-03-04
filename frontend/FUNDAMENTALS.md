# Corvus Frontend Fundamentals

> Ground truths. One-line statements. If it contradicts this file, it's wrong.
> This is the constitution. Read it before touching any frontend code.

## Identity

- Corvus is a crow. Intelligent, tool-using, security-aware.
- The general/router agent IS a crow character — not abstract, not geometric, a crow.
- Each domain agent has its own distinct identity, personality, and portrait.
- The system feels alive. Agents are beings with state, not stateless functions.
- The welcome screen features the Corvus crow prominently — it is the brand.

## Architecture

- Theme controls ALL visual expression. Components never hardcode colors, fonts, borders, radii, or shadows.
- Every visual property flows through CSS custom properties set by the active theme.
- Three font slots: `--font-sans`, `--font-mono`, `--font-display`. Components reference slots, never families.
- Fonts are loaded dynamically by the ThemeProvider. No silent system font fallbacks.
- Portrait frame (shape, border, glow) comes from the theme. Portrait content comes from the agent config.
- Portrait system is format-agnostic: sprite sheet, SVG, static image, GIF/APNG, Lottie — any agent can use any format.
- Missing state assets fall back to idle. Missing idle falls back to accent color + initial letter.
- Agent accent color is defined ONCE per theme. No duplication between CSS and TypeScript.
- Tailwind utility classes reference theme variables, never raw hex values.

## Themes

- Default theme: Modern Ops Cockpit — clean, data-dense, professional, IBM Plex fonts.
- Retro Terminal theme: CRT scanlines, phosphor glow, VT323/Press Start 2P, amber/green on black.
- Dark Fantasy theme: Textured surfaces, warm gold borders, Cinzel/EB Garamond, candlelight glow.
- Themes are not just color swaps. They change typography, textures, borders, radii, shadows, animation style, icon weight, code highlighting, scrollbars, selection color, kbd styling, and portrait frames.
- Theme switching is instant via CSS variable swap. No re-render, no page reload.
- Theme preference persists in localStorage.

## Aesthetic

- Every theme must feel intentional and complete. No half-measures.
- Atmosphere (texture, grain, glow, borders) is what separates a theme from a color swap.
- Agent portraits are the one playful element in an otherwise serious tool.
- No generic AI slop: no Inter, no purple-gradient-on-white, no cookie-cutter layouts.
- Typography choices must be distinctive and loaded explicitly.

## Agents

- 9 agents: personal, work, homelab, finance, email, docs, music, home, general.
- General is the router and the Corvus crow. It appears on the welcome screen and during routing.
- Each agent has: accent color, portrait config, display name, description.
- Agent portraits animate per state: idle, thinking, streaming, done, error.
- Portraits are configured per-agent, not per-theme — though the frame around them is themed.
- Custom portraits can be dropped in as static images, sprite sheets, or animation files.
- New agents can be created from the Config UI with custom portraits and tool policies.

## Modes

- Chat: Primary conversation surface. Routes through general to domain agents.
- Tasks: Live agent dispatch monitoring. Parallel agent streams, per-agent interrupt.
- Timeline: Per-agent event streams. Sparklines, filtering, event linking, payload search, traces.
- Memory: Search across all memory domains. Filter by domain, audit trail, link to sessions.
- Config: Agent management, model selection, tool policies, skill editing, cost dashboard, theme picker.

## Interaction

- Chat is the primary surface. Messages route through general, then fork to domain agents.
- Agents can be dispatched on tasks and monitored in parallel via the Tasks sidebar tab.
- Each agent conversation is isolated — switching agents switches the visible stream.
- Confirm requests are modal, focus-trapped, keyboard-accessible, with countdown timer.
- Interrupt targets a specific agent, not all agents.
- Re-route a conversation to a different agent mid-stream.
- Retry a failed tool call or agent response.
- Fork a conversation — branch from any message into a new session.
- Inline feedback — thumbs up/down on agent responses for future tuning.

## Agent Management (Config Mode)

- Create new agents from the UI: name, description, accent color, portrait, allowed tools.
- Edit existing agents: change portrait, color, model, tool policy.
- Create and edit skills from the UI — skills are text files, provide an editor.
- Tool policy is default-deny. Each agent has an explicit allow-list visible in Config.
- Allow/disallow specific tools per agent via toggle. Persists to backend config.

## Timeline & Traces

- Every agent action produces a trace event: tool call, routing decision, memory access, confirm decision.
- Timeline view shows events chronologically with agent-colored markers and per-agent sparklines.
- Click an event to see full payload, duration, input/output.
- Filter by agent, event type, time range, cost threshold, session, payload text search.
- Link related events (e.g., PreToolUse + PostToolUse for the same call_id).
- Aggregate stats: P50/P95 latency, error count and rate.

## Layout

- Four-zone layout: mode rail (48px) + contextual sidebar (240px resizable) + center panel (flex, max 900px content) + inspector (260px resizable, collapsible).
- Mode rail is always visible. Sidebar content changes per mode.
- Inspector auto-collapses below 1440px viewport.
- Below 1024px: single-panel with bottom nav.
- Status bar (36px) is always visible at top.

## Quality (Non-Negotiable)

- No raw `{@html}` without DOMPurify sanitization.
- All modals trap focus (WCAG 2.4.3).
- All streaming content has aria-live regions.
- `prefers-reduced-motion` disables ALL animation — show static state labels instead.
- Color is never the sole indicator — always paired with icon shape or text label.
- All text meets 4.5:1 contrast (WCAG AA).
- Visible 2px focus rings on all focusable elements.
- No dead buttons. If it's not wired up, don't render it.
- No silently dropped messages. Queue or surface feedback.
- No duplicated constants. One source of truth for agent colors, icons, font families.

## Security (UI Layer)

- No credentials ever displayed in the UI. Tool outputs sanitized server-side.
- Confirm gates are mandatory for destructive operations — UI cannot bypass.
- Agent permissions visible but not editable without explicit "edit mode" toggle.
- Audit log for all confirm/deny decisions, visible in Timeline.
- No frontend auth — Authelia SSO at SWAG layer provides X-Remote-User transparently.

## WebSocket Protocol

- Client sends: chat, confirm_response, interrupt, ping.
- Server sends: routing, agent_status, text, tool_start, tool_result, confirm_request, subagent_start, subagent_stop, memory_changed, done, error, pong.
- Task dispatch adds: task_start, task_progress, task_complete.
- All message types must be handled. No silent drops.
- Reconnection: exponential backoff 1s→30s cap, 5 retries, then error state with manual retry.
- Messages queued during reconnection, delivered on reconnect.

## Tech Stack

- SvelteKit 2 + Svelte 5 (runes: $state, $derived, $effect, $props).
- TailwindCSS 4 with @theme directive for design tokens.
- pnpm for package management.
- marked + DOMPurify for markdown. Shiki for code highlighting (theme-aware).
- Static adapter with fallback for SPA. Served by nginx in Docker.
- Playwright for E2E tests. Vitest for unit tests.
- No component library. Everything custom, fully owned.
