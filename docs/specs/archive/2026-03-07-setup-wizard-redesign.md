---
title: "Setup Wizard Redesign: Dashboard-First Credential Management"
type: spec
status: implemented
date: 2026-03-07
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Setup Wizard Redesign — Dashboard-First Credential Management

**Date:** 2026-03-07
**Status:** Approved
**Replaces:** 2026-03-01-setup-wizard-redesign.md (multi-backend wizard)

## Problem

The current setup wizard has several issues:

1. **Nothing visibly happens** — enabling backends and clicking through screens gives no feedback
2. **Ugly** — minimal CSS, no visual hierarchy, looks unfinished
3. **Re-run wipes config** — forces break-glass re-entry, no existing config detection
4. **No masked display** — can't see what's configured without exposing secrets
5. **No per-provider editing** — must walk through all 5 screens to change one key
6. **No custom providers** — locked to hardcoded list
7. **Status screen incomplete** — missing codex, ollama, kimi, openai-compat

## Design

### Two Modes, One App

**First run** (no `~/.corvus/credentials.json`):
```
Welcome (with key backup) --> Dashboard (all unconfigured) --> Break-glass --> Exit
```

**Re-run** (credentials exist):
```
Dashboard (populated, keys masked) --> edit any provider --> auto-saved
```

Detection: check for `~/.corvus/credentials.json` existence at startup.

### Visual Style

Modern TUI inspired by Textual demo apps and Claude Code CLI:
- Dark background, bordered panels, cyan/green accents
- Green dot (configured) / dim dot (not configured) status indicators
- Footer keybinding bar (Textual built-in)
- Clean typography and spacing

### Welcome Screen (First Run Only)

```
+---------------------------------------------------+
|  CORVUS SETUP                                     |
|                                                   |
|  Welcome to Corvus -- your personal agent.        |
|                                                   |
|  This wizard will set up your credentials.        |
|  Everything is encrypted locally with SOPS+age.   |
|                                                   |
|  Back up your recovery key:                       |
|  +-------------------------------------------+   |
|  | age1abc123...xyz789                    [C] |   |
|  +-------------------------------------------+   |
|  Store this somewhere safe. If you lose            |
|  ~/.corvus/age-key.txt, your credentials           |
|  cannot be recovered.                              |
|                                                   |
|              [ Get Started ]                      |
+---------------------------------------------------+
```

- Generates age keypair if not present
- Shows public key with copy-to-clipboard button
- "Get Started" navigates to dashboard

### Dashboard Screen

```
+-------------------------------------------------------+
|  CORVUS                                          [?]   |
+-------------------------------------------------------+
|                                                       |
|  LLM Backends                                         |
|  +--------------------------------------------------+|
|  | * Claude          sk-ant-api3...    [ Edit ]      ||
|  | o OpenAI          not configured    [ Setup ]     ||
|  | * Codex           Authenticated     [ Re-auth ]   ||
|  | * Ollama          localhost:11434   [ Edit ]      ||
|  | o Kimi            not configured    [ Setup ]     ||
|  | o OpenAI-compat   not configured    [ Setup ]     ||
|  |                        [ + Add Provider ]         ||
|  +--------------------------------------------------+|
|                                                       |
|  Services                                             |
|  +--------------------------------------------------+|
|  | * Home Assistant   https://ha.lo... [ Edit ]      ||
|  | o Paperless        not configured   [ Setup ]     ||
|  | o Firefly III      not configured   [ Setup ]     ||
|  | o Obsidian         not configured   [ Setup ]     ||
|  |                        [ + Add Service ]          ||
|  +--------------------------------------------------+|
|                                                       |
|  Break-glass passphrase: set             [ Change ]   |
|                                                       |
|              [ Save & Exit ]                          |
+-------------------------------------------------------+
|  q quit  up/down navigate  enter select               |
+-------------------------------------------------------+
```

**Provider rows:**
- Green dot + masked value + [Edit] button for configured providers
- Dim dot + "not configured" + [Setup] button for unconfigured
- OAuth providers (Codex, Claude Code) show "Authenticated" + expiry if known, with [Re-auth] button

**Masking rules (security-first -- codebase is public):**
- API keys: first 8 chars + `...` (e.g. `sk-ant-a...`)
- URLs: show host, truncate path (e.g. `https://ha.local...`)
- OAuth tokens: "Authenticated" + expiry date if available
- Custom services: all values masked same as API keys
- Full values NEVER rendered to any widget or terminal scrollback

### Edit/Setup Modal

Opens as a Textual modal dialog when clicking Edit/Setup:

```
+-- Configure Claude ----------------------------+
|                                                |
|  API Key                                       |
|  +------------------------------------------+  |
|  | ........................................  |  |
|  +------------------------------------------+  |
|  Current: sk-ant-api3...                       |
|  Leave blank to keep existing.                 |
|                                                |
|        [ Cancel ]    [ Save ]                  |
+------------------------------------------------+
```

- Password input field (`password=True`)
- "Current: masked_value" hint below input
- Leave blank = keep existing value
- Save = immediate SOPS encrypt + write (atomic, per-provider)
- Cancel = discard, return to dashboard

**OAuth providers (Codex, Claude Code)** get a different modal:

```
+-- Codex (ChatGPT) -----------------------------+
|                                                 |
|  Status: Authenticated (expires Mar 10)         |
|                                                 |
|  [ Sign in with ChatGPT ]                       |
|                                                 |
|  Opens your browser. Tokens are stored           |
|  encrypted in your local credential store.       |
|                                                 |
|              [ Cancel ]                          |
+-------------------------------------------------+
```

### Custom Providers

"+ Add Provider" / "+ Add Service" opens a modal:

```
+-- Add Custom Provider -------------------------+
|                                                 |
|  Name                                           |
|  +-------------------------------------------+  |
|  |                                           |  |
|  +-------------------------------------------+  |
|                                                 |
|  Fields (name = value):                         |
|  +-------------------------------------------+  |
|  | api_key  |  ........................       |  |
|  +-------------------------------------------+  |
|  [ + Add Field ]                                |
|                                                 |
|        [ Cancel ]    [ Save ]                   |
+-------------------------------------------------+
```

- Prompts for name, then key/value pairs
- Stored under the custom name in credential store
- Appears in dashboard like any other provider
- Can be edited and deleted

### Save Behavior

**Per-provider atomic save.** Each "Save" in an edit modal immediately:
1. Updates `CredentialStore._data` in memory
2. Calls `_save()` which writes temp file, SOPS encrypts, atomic renames

"Save & Exit" on the dashboard just exits -- all changes are already persisted.

### Break-Glass Handling

- **First run:** After dashboard, navigate to break-glass passphrase screen (with Skip option)
- **Re-run with passphrase set:** Dashboard shows "set" + [Change] button. No forced re-entry.
- **Re-run without passphrase:** Dashboard shows "not set" + [Set] button.

### Data Flow

```
Launch
  |
  +-- credentials.json exists?
  |     |
  |     +-- YES: CredentialStore.load() --> Dashboard (populated, masked)
  |     |
  |     +-- NO: Generate age keypair --> Welcome (show key) --> Dashboard (empty)
  |
Dashboard
  |
  +-- [Edit/Setup] --> Modal --> Save --> SOPS encrypt --> back to Dashboard
  |
  +-- [+ Add] --> Custom modal --> Save --> SOPS encrypt --> back to Dashboard
  |
  +-- [Save & Exit] --> exit
```

### Predefined Providers

**LLM Backends:**

| ID | Label | Auth Type | Fields |
|----|-------|-----------|--------|
| claude | Anthropic Claude | claude_multi | Two paste methods in one modal (see below). Corvus stores its own isolated copy — no Keychain sharing. |
| openai | OpenAI | API key | api_key (password, sk- validation) |
| codex | Codex (ChatGPT) | OAuth | browser-based PKCE flow |
| ollama | Ollama (local) | URL | base_url (default: http://localhost:11434) |
| kimi | Kimi / Moonshot | API key | api_key (password) |
| openai_compat | OpenAI-compatible | URL + key | base_url, api_key (optional) |

**Claude auth methods (shown in the Claude edit modal):**

**Method 1: Setup token (paste) — recommended**
- User runs `claude setup-token` on any machine — generates a token string
- User pastes the token into the wizard
- Stored as `anthropic/setup_token` in credential store
- No automatic refresh — works like an API key
- Following OpenClaw's pattern

**Method 2: API key (paste)**
- User pastes `sk-ant-...` API key (from Anthropic Console)
- Stored as `anthropic/api_key` in credential store
- `inject()` sets `ANTHROPIC_API_KEY` env var (existing behavior)

**Services:**

| ID | Label | Fields |
|----|-------|--------|
| ha | Home Assistant | url, token |
| paperless | Paperless | url, token |
| firefly | Firefly III | url, token |
| obsidian | Obsidian | url, token |

### Security Constraints

The codebase is public (open source). No security through obscurity.

- Masked display only -- first 8 chars + `...`, never full values
- Password inputs for all secret fields (`password=True`)
- No credential values in terminal scrollback
- SOPS+age encryption at rest (AES-256-GCM)
- Age key file at `0o600` permissions
- Plaintext only in memory during session, never on disk unencrypted
- Atomic save: write temp -> SOPS encrypt in-place -> rename (no plaintext window)

## Files Changed

| File | Change |
|------|--------|
| `corvus/cli/setup.py` | Rewrite: detect first-run vs re-run, route to correct flow |
| `corvus/cli/screens/welcome.py` | Rewrite: age key backup display, copy button |
| `corvus/cli/screens/dashboard.py` | New: main dashboard with provider rows, sections |
| `corvus/cli/screens/provider_modal.py` | New: edit/setup modal for text-field providers |
| `corvus/cli/screens/oauth_modal.py` | New: OAuth modal for Codex/Claude Code |
| `corvus/cli/screens/custom_modal.py` | New: add custom provider/service modal |
| `corvus/cli/screens/passphrase.py` | Keep, minor styling updates |
| `corvus/cli/screens/backends.py` | Delete (replaced by dashboard) |
| `corvus/cli/screens/services.py` | Delete (replaced by dashboard) |
| `corvus/cli/screens/complete.py` | Delete (no longer needed) |
| `corvus/cli/screens/status.py` | Delete (dashboard replaces this) |
| `corvus/credential_store.py` | Add `mask_value()` helper, add `delete_key()` for single-key removal |
| `tests/unit/test_setup_dashboard.py` | New: behavioral tests |

## Testing

Behavioral tests only (no mocks):

- Dashboard renders all providers with correct status from real CredentialStore
- Masking shows only first N chars of real credential values
- Edit modal saves to real SOPS-encrypted store (temp age keypair in tmp_path)
- First-run path: no credentials file -> welcome screen shown
- Re-run path: existing credentials -> dashboard shown directly
- OAuth rows show auth button, not text input
- Custom provider add/edit/delete round-trips through real credential store
- No full credential value appears in any widget render output

## Out of Scope

- Multi-user credential isolation (future)
- Per-agent model assignment in wizard (stays in models.yaml)
- Frontend credential management UI
- Credential rotation / multi-key support
- Hot-reload of config changes
