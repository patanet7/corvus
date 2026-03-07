# Slice 10: Corvus Gateway

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy the Corvus Gateway on laptop-server with sandbox-by-default, Moltbot Security 5-step hardening applied, and a clean security audit. This is the foundation for every subsequent slice — nothing else runs without it.

**Architecture:** The Corvus Gateway runs as a Docker container (using the third-party OpenClaw runtime) on laptop-server, bound exclusively to `127.0.0.1:18789`. Tailscale Serve exposes it as HTTPS on the tailnet — no port is reachable from the LAN or internet. The gateway enforces sandbox-by-default for all agents: no workspace access, no network, no shell execution. NFS-mounted Obsidian vaults from NAS (Slice 06) are bind-mounted read/write into the container for future agent use. The `openclaw.json` configuration establishes the security posture that every subsequent agent inherits.

**Tech Stack:** Third-party OpenClaw runtime, Docker Compose, Tailscale Serve, OpenSSL

**Depends on:** Slice 01 (Tailscale mesh), Slice 09 (Cleanup & Renovate -- clean slate)
**Blocks:** Slice 11 (Memory System)

---

### Task 1: Create the Corvus Gateway compose file

**Step 1: Create the stack directory in the infra repo**

```bash
mkdir -p /Users/thomaspatane/Documents/GitHub/corvus/infra/stacks/laptop-server/openclaw
```

**Step 2: Create the compose file**

Create: `infra/stacks/laptop-server/openclaw/compose.yaml`

```yaml
services:
  openclaw:
    image: openclaw/openclaw:latest
    container_name: openclaw
    restart: always
    environment:
      - OPENCLAW_HOST=127.0.0.1
      - OPENCLAW_PORT=18789
    volumes:
      - openclaw-data:/root/.openclaw
      - /mnt/vaults:/mnt/vaults:ro
    ports:
      - "127.0.0.1:18789:18789"
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://127.0.0.1:18789/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    labels:
      - "komodo.skip"
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 1G

volumes:
  openclaw-data:
```

> **Security notes:**
> - `127.0.0.1:18789:18789` ensures the gateway is ONLY reachable from localhost. No LAN or internet exposure.
> - `/mnt/vaults` is the NFS mount from NAS (Slice 06) containing Obsidian vaults. It is mounted **read-only (`:ro`)** — the gateway itself never writes to the vaults. All vault writes are handled by the Capability Broker plugin (Slice 12) via its REST API, which runs with the appropriate elevated permissions in its own container. Agents access vaults through the Capability Broker, NOT directly via filesystem tools.
> - `openclaw-data` is a named volume for persistent state (config, memory, session data, extensions) used by the third-party OpenClaw runtime.
> - `restart: always` ensures the gateway recovers automatically after host reboots and unexpected crashes.
> - `healthcheck` enables Docker (and Komodo) to track container health; the `/health` endpoint is polled every 30 seconds.
> - `komodo.skip` label prevents Komodo from auto-managing this container via ResourceSync — the stack is deployed manually and managed explicitly.
> - Resource limits (`memory: 4G`) cap the container to prevent runaway memory growth from large model contexts.

> **NFS failure mode:** If the NAS goes offline, the `/mnt/vaults` NFS mount returns
> errors (fstab uses `soft` option). The Capability Broker's Obsidian tools will fail
> gracefully (return errors, not hang). The gateway continues operating — memory tools
> and non-Obsidian agents remain functional. Monitor via Healthchecks and Grafana.

---

### Task 2: Deploy the Corvus Gateway on laptop-server

**Step 1: SSH into laptop-server**

```bash
ssh patanet7@192.168.1.200
```

**Step 2: Verify the NFS vault mount is active**

This mount was set up in Slice 06. Verify it is present:

```bash
df -h /mnt/vaults
ls /mnt/vaults
```

Expected: The NFS mount is active and shows the Obsidian vault directories (personal, work, shared, etc.). If not mounted, run `sudo mount /mnt/vaults` (it should be in fstab from Slice 06).

**Step 3: Create the Docker directory and copy the compose file**

```bash
mkdir -p ~/docker/openclaw
```

Copy `compose.yaml` into `~/docker/openclaw/compose.yaml` via scp from your Mac:

```bash
# From your Mac:
scp /Users/thomaspatane/Documents/GitHub/corvus/infra/stacks/laptop-server/openclaw/compose.yaml patanet7@192.168.1.200:~/docker/openclaw/compose.yaml
```

**Step 4: Pull the image and start the container**

```bash
ssh patanet7@192.168.1.200
cd ~/docker/openclaw
docker compose pull
docker compose up -d
```

**Step 5: Verify the container is running**

```bash
docker ps --filter "name=openclaw" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected: `openclaw` container running, ports show `127.0.0.1:18789->18789/tcp`.

```bash
docker logs openclaw --tail 30
```

Expected: Startup messages with no errors. Should show the gateway listening on port 18789.

**Step 6: Verify local HTTP access**

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18789
```

Expected: `200` (or `302` redirect to login/setup).

---

### Task 3: Moltbot Security 5-step hardening

This is the standard security checklist that must be applied before the gateway goes into use. Every step is mandatory.

**Step 1: Verify binding is loopback only**

```bash
docker exec openclaw netstat -tlnp 2>/dev/null | grep 18789 || docker exec openclaw ss -tlnp | grep 18789
```

Expected: Listening address shows `127.0.0.1:18789` (NOT `0.0.0.0:18789`).

Also verify from the host:

```bash
netstat -tlnp 2>/dev/null | grep 18789 || ss -tlnp | grep 18789
```

Expected: `127.0.0.1:18789` only. No `0.0.0.0` binding.

> **If you see `0.0.0.0:18789`:** Stop immediately. Edit `compose.yaml` to ensure `ports` uses the `127.0.0.1:` prefix. Redeploy before continuing.

**Step 2: Generate a 64-character authentication token**

```bash
OPENCLAW_TOKEN=$(openssl rand -hex 32)
echo "Token generated (64 hex chars): ${#OPENCLAW_TOKEN} characters"
echo "$OPENCLAW_TOKEN"
```

Expected: Outputs a 64-character hex string.

Save the token:

```bash
# Write to .env for docker compose (if the OpenClaw runtime supports env-based auth)
echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> ~/docker/openclaw/.env
chmod 600 ~/docker/openclaw/.env

# Store the token in Vaultwarden for safekeeping
echo "IMPORTANT: Save $OPENCLAW_TOKEN in Vaultwarden under 'Corvus Gateway Auth Token'"
```

Configure the token in the OpenClaw runtime. The method depends on the OpenClaw version — either via the CLI:

```bash
docker exec openclaw openclaw config set auth.token "$OPENCLAW_TOKEN"
```

Or by editing the config file directly (see Task 6 for the full `openclaw.json`).

**Step 3: File permissions**

```bash
docker exec openclaw chmod 600 /root/.openclaw/openclaw.json 2>/dev/null || echo "Config file not yet created (will be set in Task 6)"
docker exec openclaw chmod 700 /root/.openclaw/
```

Verify:

```bash
docker exec openclaw ls -la /root/.openclaw/
```

Expected: `.openclaw/` directory is `drwx------` (700). Config files inside are `-rw-------` (600).

**Step 4: Disable mDNS/Bonjour broadcasting**

Verify that mDNS is not enabled in the OpenClaw runtime config:

```bash
docker exec openclaw cat /root/.openclaw/openclaw.json 2>/dev/null | grep -i mdns || echo "No config yet — will be set in Task 6"
```

If mDNS is enabled, disable it. In the config file, set:

```json
{
  "network": {
    "mdns": false
  }
}
```

Or via CLI:

```bash
docker exec openclaw openclaw config set network.mdns false 2>/dev/null || echo "Will configure in Task 6"
```

**Step 5: Verify Node.js version**

```bash
docker exec openclaw node --version
```

Expected: `v22.12.0` or newer. If the version is older, the third-party `openclaw/openclaw:latest` image may need to be updated. Check for a newer tag:

```bash
docker exec openclaw node -e "console.log(process.version)"
```

> **If Node.js is below v22.12.0:** Do not proceed. Check for a newer third-party OpenClaw image or report the issue. Older Node.js versions have known security vulnerabilities.

**Step 6: Record hardening status**

Verify all 5 steps passed:

```
Moltbot Security 5-Step Hardening Results:
1. [PASS/FAIL] Loopback binding: 127.0.0.1:18789
2. [PASS/FAIL] 64-char auth token generated and configured
3. [PASS/FAIL] File permissions: 600 config, 700 directory
4. [PASS/FAIL] mDNS disabled
5. [PASS/FAIL] Node.js v22.12.0+
```

All 5 must show PASS before continuing.

---

### Task 4: Expose via Tailscale Serve

**Step 1: Configure Tailscale Serve**

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:18789
```

> **Note:** This maps `https://laptop-server.<tailnet>.ts.net` (port 443) to the local Corvus gateway port. Only authenticated Tailscale devices can reach it. No Funnel (no public internet exposure).

**Step 2: Verify Tailscale Serve is running**

```bash
tailscale serve status
```

Expected: Shows the HTTPS→HTTP proxy mapping for port 443→18789.

**Step 3: Verify HTTPS access from your Mac**

From your Mac (must be on the tailnet):

```bash
curl -sI https://laptop-server.<tailnet>.ts.net
```

Expected: HTTP 200 (or 302 redirect). The connection uses Tailscale's automatic TLS certificate.

**Step 4: Open in browser**

Navigate to `https://laptop-server.<tailnet>.ts.net` in your browser. The Corvus chat UI should load.

> **If Tailscale Serve was previously configured for Forgejo (Slice 02):** You will need to choose a different port for one of them. Options:
> - Move Forgejo to a different Tailscale Serve port (e.g., `--https=3000`)
> - Move the Corvus gateway to a different Tailscale Serve port (e.g., `--https=18789`)
> - Use Tailscale Serve path-based routing if supported

Adjust the serve command accordingly and record the final URL.

---

### Task 5: Run security audit

**Step 1: Run the built-in security audit**

```bash
docker exec openclaw openclaw security audit --fix
```

Expected: The audit runs, identifies any configuration issues, and applies fixes. Look for:
- Sandbox mode enforcement
- Permission checks
- Network binding checks
- Authentication requirements

**Step 2: Review the audit output**

Read the full output carefully. Every item should show PASS or FIXED. If any item shows FAIL without a fix:

1. Note the specific failure
2. Research the fix in the OpenClaw (third-party) documentation
3. Apply the fix manually
4. Re-run the audit

**Step 3: Re-run to confirm clean**

```bash
docker exec openclaw openclaw security audit
```

Expected: All checks pass. No warnings, no fixes needed. The audit report should be clean.

---

### Task 6: Configure sandbox defaults in openclaw.json

This is the core security configuration. It establishes the default posture for ALL agents.

**Step 1: Write the openclaw.json configuration**

```bash
docker exec openclaw cat /root/.openclaw/openclaw.json
```

Read the current config, then update it. The target configuration:

```json
{
  "agents": {
    "defaults": {
      "sandbox": {
        "mode": "all",
        "scope": "session",
        "workspaceAccess": "none",
        "docker": {
          "network": "none"
        }
      },
      "memorySearch": {
        "query": {
          "hybrid": {
            "enabled": true,
            "mmr": {
              "enabled": true,
              "lambda": 0.5
            },
            "temporalDecay": {
              "enabled": true,
              "halfLifeDays": 30
            }
          }
        },
        "extraPaths": ["~/shared-memory"]
      }
    },
    "list": []
  },
  "plugins": {
    "slots": {
      "memory": "memory-core"
    },
    "entries": {}
  },
  "hooks": {
    "enabled": true,
    "token": "FILL_IN_64_CHAR_HEX",
    "path": "/hooks",
    "allowRequestSessionKey": false,
    "allowedAgentIds": []
  }
}
```

> **Configuration explained:**
> - `sandbox.mode: "all"` -- ALL tool execution is sandboxed by default. No exceptions.
> - `sandbox.scope: "session"` -- Sandbox persists for the entire session (not per-tool-call)
> - `workspaceAccess: "none"` -- Agents cannot read/write any workspace files by default. Must be explicitly granted per agent.
> - `docker.network: "none"` -- No network access from sandboxed tools. Agents that need API access use the Capability Broker (in-process, trusted).
> - `memorySearch.hybrid` -- BM25 + vector search for memory retrieval. MMR (Maximal Marginal Relevance) with lambda 0.5 balances relevance and diversity (lower lambda = more diversity). Temporal decay with 30-day half-life prioritizes recent memories.
> - `plugins.slots.memory: "memory-core"` -- The built-in memory plugin is active.
> - `hooks.token` -- Must be replaced with the actual 64-char hex token from Task 3.
> - `hooks.allowRequestSessionKey: false` -- Webhooks cannot request session keys (security hardening).
> - `hooks.allowedAgentIds: []` -- No agents can be triggered by webhooks yet (will be configured in later slices).

> **Tuning note:** The 30-day half-life applies to all dated memory files equally.
> Consider adding a two-tier model in Slice 11:
> - 30-day half-life for daily session logs (ephemeral)
> - 90-day half-life for entries tagged `<!-- importance: high -->` (decisions, milestones)
> - No decay for evergreen files (already the default)

**Step 2: Apply the configuration**

Replace `FILL_IN_64_CHAR_HEX` with the actual token from Task 3, then write the config:

```bash
# Option A: Via CLI (if supported)
docker exec openclaw openclaw config import < /path/to/openclaw.json

# Option B: Direct file edit (copy config into container)
docker cp openclaw.json openclaw:/root/.openclaw/openclaw.json
docker exec openclaw chmod 600 /root/.openclaw/openclaw.json
```

**Step 3: Restart the gateway to apply**

```bash
cd ~/docker/openclaw
docker compose restart
```

**Step 4: Verify config was applied**

```bash
docker exec openclaw openclaw config get agents.defaults.sandbox.mode
```

Expected: `all`

```bash
docker exec openclaw openclaw config get agents.defaults.sandbox.workspaceAccess
```

Expected: `none`

**Step 5: Re-run security audit after config change**

```bash
docker exec openclaw openclaw security audit --fix
```

Expected: Clean pass. The new sandbox configuration should satisfy all audit checks.

---

### Task 7: Test sandbox enforcement

These tests verify that the sandbox actually prevents unauthorized actions. Each test should FAIL (that is the desired outcome -- the sandbox is blocking the action).

**Step 1: Test file read outside workspace**

Start a session with the gateway (via browser at `https://laptop-server.<tailnet>.ts.net` or via CLI):

Ask the agent:
> "Read the file /etc/passwd"

Expected: The agent either refuses to attempt it or the tool execution fails with a sandbox violation error. The file contents should NOT be returned.

**Step 2: Test network request**

Ask the agent:
> "Make an HTTP request to https://httpbin.org/get"

Expected: The request fails. The sandbox blocks all outbound network access (`network: "none"`).

**Step 3: Test shell command execution**

Ask the agent:
> "Run the command: ls -la /"

Expected: Shell execution fails or is blocked by the sandbox. No command output is returned.

**Step 4: Test workspace file read**

Ask the agent:
> "List all files in your workspace"

Expected: Either an empty result (no workspace access) or a sandbox violation. `workspaceAccess: "none"` means agents cannot browse or read workspace files by default.

**Step 5: Record test results**

```
Sandbox Enforcement Test Results:
1. [BLOCKED] File read outside workspace (/etc/passwd)
2. [BLOCKED] Network request (https://httpbin.org/get)
3. [BLOCKED] Shell command execution (ls -la /)
4. [BLOCKED] Workspace file read
```

All 4 must show BLOCKED. If any succeed, the sandbox configuration is incorrect -- fix before proceeding.

---

### Task 8: Verify HTTPS access from Mac via Tailscale

**Step 1: Test from Mac terminal**

```bash
curl -s https://laptop-server.<tailnet>.ts.net | head -20
```

Expected: HTML response from the Corvus web UI.

**Step 2: Test from browser**

Open `https://laptop-server.<tailnet>.ts.net` in your browser. The Corvus chat interface should load.

**Step 3: Test from mobile (optional)**

If your phone is on the Tailscale network, open the same URL in your mobile browser. The UI should be accessible.

**Step 4: Verify NOT accessible from LAN**

From a device NOT on the Tailscale network (or with Tailscale disabled), try:

```bash
curl -s http://192.168.1.200:18789
```

Expected: Connection refused. The port is bound to `127.0.0.1` only -- it is not reachable from the LAN.

---

### Task 9: Commit checkpoint

**Step 1: Add the compose file to the corvus repo**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git add infra/stacks/laptop-server/openclaw/
```

**Step 2: Commit**

```bash
git add -A
git commit -m "feat(slice-10): Corvus Gateway deployed on laptop-server, hardened, sandbox-by-default, security audit clean"
```

**Step 3: Push the compose file to Forgejo infra repo**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus/infra
git add stacks/laptop-server/openclaw/
git commit -m "feat(slice-10): Corvus Gateway compose file"
git push forgejo main
```

**Step 4: Register the stack in Komodo Core (optional)**

In the Komodo Core UI (`https://laptop-server.<tailnet>.ts.net:9120`):

1. Go to **Stacks** -> **New Stack**
2. Name: `openclaw`
3. Server: `laptop-server`
4. Source: Git -> Repo: `homelab/infra` -> Path: `stacks/laptop-server/openclaw`
5. Tags: `host:laptop`, `role:ai`, `critical:true`
6. Save

**Step 5: Create Healthchecks ping for the Corvus Gateway**

In the Healthchecks UI (`https://laptop-server.tail51e72.ts.net:8001`):

1. Create new check: "openclaw-gateway"
2. Period: 5 minutes
3. Grace: 10 minutes
4. Copy the ping URL

Add a crontab entry:

```bash
*/5 * * * * curl -sf http://127.0.0.1:18789/health && curl -sf <HEALTHCHECKS_PING_URL>
```

---

## Acceptance Criteria

- [ ] Corvus Gateway container running on laptop-server (`docker ps | grep openclaw` shows running)
- [ ] Gateway bound to `127.0.0.1:18789` ONLY (not `0.0.0.0`)
- [ ] Accessible via Tailscale Serve HTTPS at `https://laptop-server.<tailnet>.ts.net`
- [ ] NOT accessible from LAN (`curl http://192.168.1.200:18789` fails)
- [ ] **Moltbot Security 5-step hardening applied:**
  - [ ] Step 1: Loopback binding verified (`127.0.0.1:18789`)
  - [ ] Step 2: 64-character auth token generated and configured
  - [ ] Step 3: File permissions set (`chmod 600` config, `chmod 700` directory)
  - [ ] Step 4: mDNS/Bonjour disabled
  - [ ] Step 5: Node.js v22.12.0+ verified
- [ ] `openclaw security audit --fix` (third-party CLI) passes with a clean report
- [ ] Sandbox defaults configured in `openclaw.json`:
  - [ ] `sandbox.mode: "all"` (all tool execution sandboxed)
  - [ ] `sandbox.workspaceAccess: "none"` (no file access by default)
  - [ ] `docker.network: "none"` (no network access by default)
- [ ] Memory search configured: hybrid (BM25 + vectors), MMR (lambda 0.5), temporal decay (30-day half-life)
- [ ] **Sandbox enforcement verified:**
  - [ ] Cannot read files outside workspace
  - [ ] Cannot make network requests
  - [ ] Cannot execute shell commands
  - [ ] Cannot access workspace files
- [ ] NFS vaults mount (`/mnt/vaults`) accessible inside the container
- [ ] Corvus gateway auth token stored in Vaultwarden
- [ ] Compose file committed to both corvus repo and Forgejo infra repo
