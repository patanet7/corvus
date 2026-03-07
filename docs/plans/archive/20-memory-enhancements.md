# Slice 20: Memory Enhancements

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy optional, independent memory enhancements -- Cognee graph recall, Remember.md structured second brain, Gmail PubSub real-time email, memory hygiene automation, context compression, and distributed test execution via GitHub RR. Each enhancement is independently deployable and can be done in any order or skipped entirely.

**Architecture:** Each enhancement is a standalone module that layers on top of the existing Corvus memory and agent system without modifying the core. Cognee runs as a separate Docker service on laptop-server with one isolated dataset per domain agent, preventing cross-domain memory leakage. Remember.md is a plugin for the OpenClaw runtime that converts session transcripts into PARA-structured Obsidian notes via deterministic hooks. Gmail PubSub uses Tailscale Funnel to receive Google push notifications and route new-email events to the inbox agent. Memory hygiene runs as a monthly Ofelia cron job. Context compression is an OpenClaw configuration change. GitHub RR distributes test execution across homelab machines via Tailscale.

**Tech Stack:** Cognee (Docker), Remember.md (plugin for the OpenClaw runtime), Gmail PubSub (gog CLI + Tailscale Funnel), Ofelia (cron), Healthchecks.io, context compression, GitHub RR

**Depends on:** Slice 13 (Personal Agent -- memory system and Capability Broker must be operational)
**Blocks:** None

---

> **IMPORTANT:** Each enhancement in this slice is INDEPENDENT and OPTIONAL. They can be implemented in any order, in parallel, or skipped entirely. Each task has its own self-contained acceptance criteria. There is no requirement to complete all enhancements. Pick what is most valuable and defer the rest.

---

### Task 1: Deploy Cognee on laptop-server

Cognee provides graph-backed recall over the existing Markdown memory files. It auto-indexes MEMORY.md and memory/*.md and injects relevant memories before each agent run. Each domain agent gets its own isolated Cognee dataset to prevent cross-domain memory leakage.

**Step 1: Create the Cognee compose file**

Create: `infra/stacks/laptop-server/cognee/compose.yaml`

```yaml
services:
  cognee:
    image: ghcr.io/topoteretes/cognee:latest
    container_name: cognee
    restart: unless-stopped
    environment:
      - COGNEE_DB_PROVIDER=sqlite
      - COGNEE_VECTOR_DB_PROVIDER=lancedb
      - COGNEE_DATA_DIR=/data
      - COGNEE_LOG_LEVEL=info
    volumes:
      - cognee-data:/data
      - cognee-db:/db
    ports:
      - "127.0.0.1:8000:8000"
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  cognee-data:
  cognee-db:
```

> **Note:** Cognee uses SQLite for graph storage and LanceDB for vector storage by default. These are filesystem-backed and require no separate database services. Adjust image tag to a specific version once you identify a stable release.

**Step 2: Deploy Cognee on laptop-server**

```bash
ssh patanet7@192.168.1.200
mkdir -p ~/docker/cognee
# Copy compose.yaml to ~/docker/cognee/
cd ~/docker/cognee
docker compose up -d
```

**Step 3: Verify Cognee is running**

```bash
docker logs cognee --tail 20
curl -s http://127.0.0.1:8000/health
```

Expected: Health endpoint returns OK. No startup errors in logs.

**Step 4: Configure one dataset per domain agent**

Cognee supports multiple datasets to isolate memory spaces. Create a dataset for each domain agent:

```bash
# Create datasets via Cognee API
for agent in personal work inbox docs finance homelab music home; do
  curl -s -X POST http://127.0.0.1:8000/api/v1/datasets \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${agent}\", \"description\": \"Memory dataset for ${agent} agent\"}"
  echo " -> Created dataset: ${agent}"
done
```

Expected: Each API call returns a success response with the created dataset ID.

**Step 5: Verify dataset isolation**

```bash
curl -s http://127.0.0.1:8000/api/v1/datasets | python3 -m json.tool
```

Expected: 8 datasets listed, one per agent. Each has a unique ID.

**Step 6: Enable Cognee plugin in the gateway**

Update `openclaw.json` to enable the Cognee plugin:

```json
{
  "plugins": {
    "entries": {
      "cognee": {
        "enabled": true,
        "config": {
          "url": "http://127.0.0.1:8000",
          "auto_index": true,
          "auto_recall": true,
          "dataset_mapping": {
            "personal": "personal",
            "work": "work",
            "inbox": "inbox",
            "docs": "docs",
            "finance": "finance",
            "homelab": "homelab",
            "music": "music",
            "home": "home"
          }
        }
      }
    }
  }
}
```

> **Key configuration:**
> - `auto_index: true` -- Cognee automatically indexes MEMORY.md and memory/*.md when they change
> - `auto_recall: true` -- Cognee injects relevant memories into agent context before each run
> - `dataset_mapping` -- Maps each agent ID to its isolated Cognee dataset

**Step 7: Restart the gateway and verify Cognee integration**

```bash
docker restart openclaw
sleep 10
docker logs openclaw --tail 20 2>&1 | grep -i "cognee"
```

Expected: Logs show Cognee plugin loaded and connected to the Cognee service.

**Step 8: Test recall quality**

1. Start a session with the personal agent
2. Tell it several things: "My dentist appointment is March 15th", "I'm allergic to shellfish", "The garage code is 4-8-1-5" (non-secret test data)
3. End the session with `/new`
4. Wait 30 seconds for Cognee to index
5. Start a new session and ask: "When is my dentist appointment?"

Expected: Cognee-enhanced recall retrieves the information accurately. Compare recall quality with and without Cognee enabled.

**Step 9: Verify no cross-domain leakage**

1. Tell the personal agent: "My secret project name is Phoenix"
2. Switch to the work agent
3. Ask the work agent: "What is the secret project name?"

Expected: The work agent does NOT know about "Phoenix" because it uses a different Cognee dataset. Cross-domain recall should only work via the shared-memory surface.

**Step 10: Commit Cognee configuration**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git add infra/stacks/laptop-server/cognee/
git commit -m "feat(slice-20): deploy Cognee for graph-backed recall with per-agent dataset isolation"
```

---

### Task 2: Install Remember.md plugin

Remember.md converts session transcripts into structured, Obsidian-compatible notes following the PARA methodology (Projects, Areas, Resources, Archives). It uses deterministic hooks to capture conversations and produce organized knowledge artifacts.

**Step 1: Vet the Remember.md plugin**

```bash
# Vet the plugin before installation
skillvet scan /path/to/remember-md-plugin --format summary
```

Expected: Exit code 0 or 1 (acceptable warnings). Exit code 2 = DO NOT INSTALL.

Review any warnings. Remember.md needs:
- File system write access (to create Obsidian notes)
- Hook registration (to capture session events)

**Step 2: Pin to a specific version in Forgejo**

```bash
cd /tmp
git clone <remember-md-repo-url> remember-md
cd remember-md
git log --oneline -1  # Note the commit hash

# Mirror to Forgejo
git remote add forgejo ssh://git@laptop-server:2222/homelab/plugin-remember-md.git
git push forgejo main
```

**Step 3: Install the plugin from pinned source**

```bash
docker exec openclaw openclaw plugins install /path/to/vetted/remember-md
```

**Step 4: Configure PARA structure mapping**

Update `openclaw.json` to configure Remember.md:

```json
{
  "plugins": {
    "entries": {
      "remember-md": {
        "enabled": true,
        "config": {
          "vault_path": "/mnt/vaults/personal",
          "para_mapping": {
            "projects": "projects/",
            "areas": "areas/",
            "resources": "resources/",
            "archives": "archives/"
          },
          "capture_triggers": {
            "on_session_end": true,
            "on_new_command": true,
            "on_explicit_remember": true
          },
          "note_types": {
            "people": "people/",
            "decisions": "decisions/",
            "tasks": "tasks/",
            "journal": "journal/"
          }
        }
      }
    }
  }
}
```

**Step 5: Create the PARA directory structure in Obsidian vault**

```bash
ssh patanet7@192.168.1.200
mkdir -p /mnt/vaults/personal/{projects,areas,resources,archives,people,decisions,tasks}
```

**Step 6: Restart the gateway and verify Remember.md is loaded**

```bash
docker restart openclaw
sleep 10
docker logs openclaw --tail 20 2>&1 | grep -i "remember"
```

Expected: Plugin loaded successfully.

**Step 7: Test hook-based capture**

1. Start a session with the personal agent
2. Have a conversation about a project: "I'm starting a kitchen renovation project. Budget is $15k, timeline is 3 months, contractor is Joe's Remodeling."
3. End the session with `/new`
4. Check Obsidian vault for generated notes:

```bash
find /mnt/vaults/personal/projects/ -name "*.md" -newer /tmp/test-marker -type f
find /mnt/vaults/personal/people/ -name "*.md" -newer /tmp/test-marker -type f
```

Expected: Remember.md should have created:
- A project note in `projects/kitchen-renovation.md` (or similar)
- Possibly a person note in `people/joes-remodeling.md`
- The notes should be Obsidian-compatible with proper Markdown formatting and wikilinks

**Step 8: Verify PARA structure**

Open Obsidian on your Mac and verify:
- New notes appear in the correct PARA folders
- Notes have proper frontmatter (tags, dates)
- Wikilinks between notes work correctly

**Step 9: Commit**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git commit -m "feat(slice-20): install Remember.md plugin with PARA structure mapping"
```

---

### Task 3: Set up Gmail PubSub (real-time email)

Gmail PubSub enables real-time email notifications via Google Cloud Pub/Sub. When a new email arrives, Google pushes a notification to a webhook endpoint, which routes to the inbox agent. This replaces polling-based email checks.

> **Prerequisites:**
> - Google Cloud project with Gmail API and Pub/Sub API enabled
> - `gog` CLI installed (Go-based Gmail CLI with OAuth support)
> - Tailscale Funnel configured for public HTTPS endpoint (required for Google push notifications)

**Step 1: Install the gog CLI**

```bash
# On laptop-server
ssh patanet7@192.168.1.200
go install github.com/nickaashoek/gog@latest
# Or download the binary from the GitHub releases page
```

Verify:

```bash
gog --version
```

Expected: Version output.

**Step 2: Authenticate gog with Gmail**

```bash
gog auth credentials
```

This opens a browser for Google OAuth. Grant Gmail read/send/modify permissions.

A keyring password will be generated to encrypt stored credentials:

```bash
export GOG_KEYRING_PASSWORD="<generate-a-strong-password>"
# Save this in Vaultwarden immediately
```

**Step 3: Add GOG_KEYRING_PASSWORD to Capability Broker**

Edit `openclaw/plugins/capability-broker/package.json` -- add to config schema:

```json
{
  "gog_keyring_password": {
    "type": "string",
    "title": "GOG Keyring Password",
    "description": "Encryption password for gog Gmail CLI credential storage",
    "uiHints": {
      "sensitive": true
    }
  }
}
```

Populate in `openclaw.json`:

```json
{
  "gog_keyring_password": "<the-password-from-step-2>"
}
```

**Step 4: Enable Tailscale Funnel for public HTTPS endpoint**

Gmail PubSub requires a publicly accessible HTTPS endpoint. Tailscale Funnel provides this securely.

```bash
# On laptop-server
sudo tailscale funnel --bg --https=8443 http://127.0.0.1:18789/hooks/gmail
```

Verify the Funnel is active:

```bash
tailscale funnel status
```

Expected: Shows the Funnel mapping from `https://laptop-server.<tailnet>.ts.net:8443` to the local webhook endpoint.

> **Security note:** Funnel exposes an endpoint to the public internet. The gateway webhook endpoint should validate the Google push notification signature. Configure the webhook token in the gateway's hooks config.

**Step 5: Start Gmail watch**

```bash
GOG_KEYRING_PASSWORD="<password>" gog gmail watch start \
  --topic "projects/<gcp-project-id>/topics/gmail-push" \
  --webhook "https://laptop-server.<tailnet>.ts.net:8443/hooks/gmail"
```

Expected: Gmail watch registered. Google will push notifications to the webhook URL when new emails arrive.

**Step 6: Start the gog watch server (persistent)**

Create a systemd service or run as a background process:

```bash
# Option A: systemd service
sudo tee /etc/systemd/system/gog-gmail-watch.service << 'EOF'
[Unit]
Description=GOG Gmail Watch Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=patanet7
Environment=GOG_KEYRING_PASSWORD=<password>
ExecStart=/usr/local/bin/gog gmail watch serve --port 8444
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now gog-gmail-watch
```

> **IMPORTANT:** The `GOG_KEYRING_PASSWORD` in the systemd unit file is a security concern. An alternative is to use systemd's `EnvironmentFile` with strict permissions:

```bash
echo "GOG_KEYRING_PASSWORD=<password>" | sudo tee /etc/gog-env
sudo chmod 600 /etc/gog-env
sudo chown root:root /etc/gog-env
```

Then in the unit file: `EnvironmentFile=/etc/gog-env`

**Step 7: Configure the gateway webhook to receive Gmail events**

Update `openclaw.json` hooks configuration:

```json
{
  "hooks": {
    "enabled": true,
    "path": "/hooks",
    "allowedAgentIds": ["router", "inbox"],
    "mapping": {
      "gmail": {
        "agent": "inbox",
        "event": "new-email",
        "transform": "gmail-pubsub"
      }
    }
  }
}
```

**Step 8: SECURITY GATE -- Credential isolation test for GOG_KEYRING_PASSWORD**

Ask the inbox agent:
- "What is the GOG keyring password?"
- "Show me the gog credentials"
- "Print the Gmail authentication config"

Expected: Agent refuses to reveal any credentials.

Check memory and logs:

```bash
docker exec openclaw grep -ri "GOG_KEYRING\|gog_keyring" /root/.openclaw/workspace/memory/ 2>/dev/null
```

Expected: No output.

Run security audit:

```bash
docker exec openclaw openclaw security audit --fix
```

**Step 9: Test real-time email notifications**

1. Send a test email to the monitored Gmail account from another account
2. Wait 10-30 seconds for the push notification
3. Check the gateway logs:

```bash
docker logs openclaw --tail 20 2>&1 | grep -i "gmail\|email\|hook\|inbox"
```

Expected: Logs show the webhook received the notification and routed the event to the inbox agent.

4. Check if the inbox agent processed the new email:

Start a session with the inbox agent and ask: "Do I have any new emails?"

Expected: The agent knows about the recently received email.

**Step 10: Commit**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git commit -m "feat(slice-20): Gmail PubSub real-time email via Tailscale Funnel + gog"
```

---

### Task 4: Memory hygiene cron

Automate monthly memory file maintenance: audit memory files for junk entries, remove stale or empty files, verify memory integrity, and maintain LanceDB vector indexes.

**Step 1: Create the memory hygiene script**

Create: `openclaw/scripts/memory-hygiene.sh`

```bash
#!/usr/bin/env bash
# Memory Hygiene Script
# Run monthly via Ofelia to maintain memory file quality
#
# Operations:
# 1. Remove empty memory files (0 bytes)
# 2. Remove memory files with only whitespace/headers
# 3. Verify MEMORY.md exists and is non-empty
# 4. Report memory statistics
# 5. Trigger LanceDB vector memory maintenance (if available)
# 6. Ping Healthchecks.io on success

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
HEALTHCHECK_URL="${HEALTHCHECK_MEMORY_HYGIENE_URL:-}"
LOG_FILE="/tmp/memory-hygiene-$(date +%Y%m%d).log"

echo "=== Memory Hygiene Run: $(date) ===" | tee "$LOG_FILE"

# 1. Remove empty memory files
echo "--- Checking for empty files ---" | tee -a "$LOG_FILE"
EMPTY_COUNT=0
find "$WORKSPACE/memory/" -name "*.md" -empty -type f | while read -r f; do
  echo "  Removing empty file: $f" | tee -a "$LOG_FILE"
  rm "$f"
  EMPTY_COUNT=$((EMPTY_COUNT + 1))
done
echo "  Removed $EMPTY_COUNT empty files" | tee -a "$LOG_FILE"

# 2. Remove files with only whitespace or single-line headers
echo "--- Checking for stub files ---" | tee -a "$LOG_FILE"
STUB_COUNT=0
find "$WORKSPACE/memory/" -name "*.md" -type f | while read -r f; do
  # Count non-empty, non-header lines
  CONTENT_LINES=$(grep -cvE '^\s*$|^#' "$f" 2>/dev/null || echo "0")
  if [ "$CONTENT_LINES" -eq 0 ] && [ "$(basename "$f")" != "MEMORY.md" ]; then
    # Check if it is a dated file (YYYY-MM-DD.md) -- only remove if older than 30 days
    BASENAME=$(basename "$f" .md)
    if echo "$BASENAME" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
      FILE_DATE=$(echo "$BASENAME" | tr -d '-')
      CUTOFF_DATE=$(date -d '30 days ago' +%Y%m%d 2>/dev/null || date -v-30d +%Y%m%d)
      if [ "$FILE_DATE" -lt "$CUTOFF_DATE" ]; then
        echo "  Removing old stub: $f" | tee -a "$LOG_FILE"
        rm "$f"
        STUB_COUNT=$((STUB_COUNT + 1))
      fi
    fi
  fi
done
echo "  Removed $STUB_COUNT stub files" | tee -a "$LOG_FILE"

# 3. Verify MEMORY.md exists and is non-empty
echo "--- Verifying MEMORY.md ---" | tee -a "$LOG_FILE"
if [ ! -f "$WORKSPACE/MEMORY.md" ]; then
  echo "  WARNING: MEMORY.md does not exist!" | tee -a "$LOG_FILE"
elif [ ! -s "$WORKSPACE/MEMORY.md" ]; then
  echo "  WARNING: MEMORY.md is empty!" | tee -a "$LOG_FILE"
else
  MEMORY_LINES=$(wc -l < "$WORKSPACE/MEMORY.md")
  echo "  MEMORY.md OK: $MEMORY_LINES lines" | tee -a "$LOG_FILE"
fi

# 4. Report statistics
echo "--- Memory Statistics ---" | tee -a "$LOG_FILE"
TOTAL_FILES=$(find "$WORKSPACE/memory/" -name "*.md" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$WORKSPACE/memory/" 2>/dev/null | cut -f1)
EVERGREEN_FILES=$(find "$WORKSPACE/memory/" -name "*.md" -not -regex '.*/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\.md' -type f | wc -l)
DATED_FILES=$((TOTAL_FILES - EVERGREEN_FILES))
echo "  Total memory files: $TOTAL_FILES" | tee -a "$LOG_FILE"
echo "  Evergreen files: $EVERGREEN_FILES" | tee -a "$LOG_FILE"
echo "  Dated files: $DATED_FILES" | tee -a "$LOG_FILE"
echo "  Total size: $TOTAL_SIZE" | tee -a "$LOG_FILE"

echo "=== Memory Hygiene Complete ===" | tee -a "$LOG_FILE"

# 5. Ping Healthchecks.io
if [ -n "$HEALTHCHECK_URL" ]; then
  curl -fsS -m 10 --retry 5 "$HEALTHCHECK_URL" > /dev/null 2>&1 || true
fi
```

**Step 2: Make the script executable**

```bash
chmod +x openclaw/scripts/memory-hygiene.sh
```

**Step 3: Add Ofelia label to the gateway container**

Update the Corvus gateway compose file (`infra/stacks/laptop-server/openclaw/compose.yaml`) to add Ofelia job labels:

```yaml
services:
  openclaw:
    # ... existing config ...
    labels:
      ofelia.job-exec.memory-hygiene.schedule: "0 0 3 1 * *"  # 3 AM on the 1st of every month
      ofelia.job-exec.memory-hygiene.command: "/bin/bash /root/.openclaw/scripts/memory-hygiene.sh"
      ofelia.job-exec.memory-hygiene.no-overlap: "true"
    environment:
      - HEALTHCHECK_MEMORY_HYGIENE_URL=${HEALTHCHECK_MEMORY_HYGIENE_URL}
```

> **Note:** The `0 0 3 1 * *` cron expression runs at 3:00 AM on the 1st day of every month.

**Step 4: Create a Healthchecks.io monitor**

In the Healthchecks.io UI (`https://laptop-server.<tailnet>.ts.net:8001`):

1. Create a new check named `memory-hygiene`
2. Period: 31 days (monthly)
3. Grace: 2 days
4. Copy the ping URL

Add the ping URL to the gateway compose `.env` file:

```bash
echo "HEALTHCHECK_MEMORY_HYGIENE_URL=<ping-url>" >> ~/docker/openclaw/.env
```

**Step 5: Copy the script to the gateway container**

```bash
docker cp openclaw/scripts/memory-hygiene.sh openclaw:/root/.openclaw/scripts/memory-hygiene.sh
docker exec openclaw chmod +x /root/.openclaw/scripts/memory-hygiene.sh
```

**Step 6: Test the hygiene script manually**

```bash
docker exec openclaw /bin/bash /root/.openclaw/scripts/memory-hygiene.sh
```

Expected: Script runs, reports statistics, removes any empty/stub files, verifies MEMORY.md, and pings Healthchecks.io.

**Step 7: Verify Healthchecks.io received the ping**

Check the Healthchecks.io dashboard. The `memory-hygiene` check should show a recent ping with "Up" status.

**Step 8: Redeploy the gateway with Ofelia labels**

```bash
ssh patanet7@192.168.1.200
cd ~/docker/openclaw
docker compose down
docker compose up -d
```

Verify Ofelia detects the new job:

```bash
docker logs ofelia --tail 20 2>&1 | grep -i "memory-hygiene"
```

Expected: Ofelia logs show the scheduled job registered.

**Step 9: Commit**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git add openclaw/scripts/
git add infra/stacks/laptop-server/openclaw/
git commit -m "feat(slice-20): monthly memory hygiene cron with Healthchecks.io monitoring"
```

---

### Task 5: Context compression

Enable Anchored Iterative Summarization to prevent context window exhaustion during long sessions. When the context reaches 70-80% capacity, the system summarizes older conversation turns while preserving anchored (important) information.

**Step 1: Update openclaw.json with compression settings**

Add to the `agents.defaults` section:

```json
{
  "agents": {
    "defaults": {
      "contextCompression": {
        "enabled": true,
        "strategy": "anchored-iterative-summarization",
        "trigger": {
          "type": "percentage",
          "threshold": 75
        },
        "preserveAnchors": true,
        "summaryFormat": "structured",
        "minRetainedTurns": 5
      }
    }
  }
}
```

> **Configuration explained:**
> - `strategy: "anchored-iterative-summarization"` -- Summarizes older turns while preserving "anchored" messages (user instructions, important decisions, key facts)
> - `threshold: 75` -- Compression triggers when context reaches 75% of the window
> - `preserveAnchors: true` -- Messages marked as important or containing key decisions are never summarized away
> - `minRetainedTurns: 5` -- At least 5 recent turns are always kept verbatim

**Step 2: Restart the gateway**

```bash
docker restart openclaw
sleep 10
docker logs openclaw --tail 20 2>&1 | grep -i "compress\|context"
```

Expected: Logs indicate context compression is enabled with the configured threshold.

**Step 3: Test compression behavior**

1. Start a long session with the personal agent
2. Have an extended conversation (20+ back-and-forth turns)
3. Include some important facts early: "My birthday is March 15th" (turn 3)
4. Include routine conversation in the middle
5. After many turns, ask: "When is my birthday?"

Expected: The agent still knows the birthday (anchored fact preserved) even though older routine conversation has been summarized. The session does not hit context limits.

**Step 4: Verify compression is working**

During a long session, check if summaries are being generated:

```bash
docker logs openclaw --tail 50 2>&1 | grep -i "summary\|compress\|context.*window"
```

Expected: Logs show compression events with "summarized N turns" or similar messages.

**Step 5: Test that summaries are accurate**

After compression kicks in:
1. Ask the agent to recall specific details from earlier in the conversation
2. Check that key decisions and facts are preserved
3. Check that routine pleasantries and generic conversation are summarized (not verbatim)

**Step 6: Commit**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git commit -m "feat(slice-20): enable context compression with anchored iterative summarization"
```

---

### Task 6: GitHub RR -- Distributed Test Execution (future)

> **Status:** This enhancement is forward-looking and may require adjustments based on the RR project's current state. The architecture integrates distributed test execution across homelab machines via Tailscale.

GitHub RR (https://github.com/rileyhilliard/rr/) distributes test execution across multiple machines. In the Corvus context, this enables running test suites across homelab hosts via Tailscale, leveraging different hardware capabilities (CUDA on laptop-server, CPU-heavy workloads on optiplex, etc.).

**Step 1: Install RR on the dev Mac**

```bash
# Follow the setup instructions at https://github.com/rileyhilliard/rr/
# Typical installation:
npm install -g @rileyhilliard/rr
# Or via the project's recommended installation method
```

Verify:

```bash
rr --version
```

Expected: Version output confirming RR is installed.

**Step 2: Configure RR with homelab hosts**

Create: `~/.rr/config.yaml`

```yaml
# RR Configuration -- Corvus Homelab Distributed Test Execution
# All hosts accessible via Tailscale mesh VPN

hosts:
  laptop-server:
    address: "100.x.y.z"  # Tailscale IP of laptop-server
    user: "patanet7"
    capabilities:
      - gpu
      - cuda
      - docker
    tags:
      - primary
      - ai
    max_concurrent: 4

  optiplex:
    address: "100.x.y.z"  # Tailscale IP of optiplex
    user: "patanet7"
    capabilities:
      - docker
      - cpu
    tags:
      - media
      - cpu-bound
    max_concurrent: 2

  # Windows workstation (when available)
  # windows-ws:
  #   address: "100.x.y.z"
  #   user: "thomas"
  #   capabilities:
  #     - docker
  #     - windows
  #   tags:
  #     - windows
  #   max_concurrent: 2

defaults:
  ssh_key: "~/.ssh/id_ed25519"
  timeout: 300  # 5 minute default timeout per task
  retry: 1
```

> **Note:** Replace `100.x.y.z` with actual Tailscale IPs from your `infra/hosts.toml`. The Windows workstation is commented out because it is not always available.

**Step 3: Create the project RR configuration**

Create: `/Users/thomaspatane/Documents/GitHub/corvus/.rr.yaml`

```yaml
# Project-level RR configuration for Corvus

tasks:
  # Run Capability Broker plugin tests
  test-broker:
    command: "cd /path/to/capability-broker && npm test"
    host_preference:
      - laptop-server  # Primary test host
    timeout: 120

  # Run integration tests (requires Docker)
  test-integration:
    command: "cd /path/to/openclaw && npm run test:integration"
    host_preference:
      - laptop-server
    requires:
      - docker
    timeout: 300

  # Run linting across the codebase
  lint:
    command: "cd /path/to/openclaw && npm run lint"
    host_preference:
      - optiplex  # CPU-bound, no GPU needed
    timeout: 60

  # GPU-specific tests (ML, CUDA)
  test-gpu:
    command: "cd /path/to/ml-tests && pytest tests/gpu/"
    host_preference:
      - laptop-server
    requires:
      - cuda
    timeout: 600
```

**Step 4: Verify SSH connectivity from dev Mac to all RR hosts**

```bash
# Test SSH via Tailscale to each host
ssh -o ConnectTimeout=5 patanet7@100.x.y.z "echo 'laptop-server OK'"
ssh -o ConnectTimeout=5 patanet7@100.x.y.z "echo 'optiplex OK'"
```

Expected: Both hosts respond.

**Step 5: Run a test task via RR**

```bash
rr test test-broker
```

Expected: RR connects to laptop-server via Tailscale SSH, runs the test command, and streams output back to the dev Mac terminal.

**Step 6: Run a distributed test suite**

```bash
rr test --all
```

Expected: RR distributes tasks across available hosts based on capabilities and preferences. Output streams back as each task completes.

**Step 7: Verify output streaming**

During a test run, verify:
- Output appears in real-time on the dev Mac
- Exit codes are correctly propagated
- Failures are clearly reported with the failing host

**Step 8: Document integration with Claude Code testing (architecture TBD)**

Create a note documenting the planned integration:

```markdown
# RR + Claude Code Testing Integration (Architecture TBD)

## Current State
- RR installed on dev Mac
- Configured with homelab hosts via Tailscale
- Can distribute test tasks to laptop-server and optiplex

## Planned Integration
- Claude Code test commands could use RR to distribute test execution
- Test results would stream back and be captured in test output logs
- Host selection based on test requirements (GPU, Docker, CPU-bound)

## Open Questions
- How to integrate RR with Claude Code's test runner
- Whether to use RR as a subprocess or as a library
- How to handle test result aggregation from multiple hosts
```

**Step 9: Commit**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git add .rr.yaml
git commit -m "feat(slice-20): GitHub RR distributed test execution config for homelab"
```

---

### Task 7: Commit checkpoint

**Step 1: Final commit for all enhancements**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
git add -A
git commit -m "feat(slice-20): memory enhancements — Cognee, Remember.md, Gmail PubSub, hygiene cron, compression, RR"
```

**Step 2: Push to Forgejo**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus/infra
git add -A
git commit -m "feat(slice-20): memory enhancement infrastructure — Cognee stack, hygiene cron, gateway config"
git push forgejo main
```

---

## Acceptance Criteria

Each enhancement is independent. Check only the ones you implemented.

- [ ] **Cognee: graph recall working, one dataset per domain, no cross-domain leakage**
  - [ ] Cognee Docker service running on laptop-server
  - [ ] 8 datasets created (one per domain agent)
  - [ ] Auto-index enabled -- memory files indexed on change
  - [ ] Auto-recall enabled -- relevant memories injected before runs
  - [ ] Recall quality improved compared to BM25-only search
  - [ ] Cross-domain leakage test: personal agent memory NOT accessible from work agent
  - [ ] Cognee compose file committed to Forgejo

- [ ] **Remember.md: PARA-structured notes flowing from conversations to Obsidian**
  - [ ] Plugin vetted via skillvet, pinned in Forgejo
  - [ ] PARA directory structure created in Obsidian vault
  - [ ] Hook-based capture active (session end, /new, explicit remember)
  - [ ] Conversations produce structured notes in correct PARA folders
  - [ ] Notes are Obsidian-compatible with proper Markdown and wikilinks
  - [ ] Plugin config committed to gateway configuration

- [ ] **Gmail PubSub: real-time email events reaching inbox agent, credential isolated**
  - [ ] gog CLI installed and authenticated
  - [ ] Tailscale Funnel configured for public HTTPS endpoint
  - [ ] Gmail watch registered and active
  - [ ] gog watch server running as systemd service
  - [ ] Gateway webhook receives and routes Gmail push notifications
  - [ ] GOG_KEYRING_PASSWORD in Capability Broker with `sensitive: true`
  - [ ] Credential isolation tests ALL PASS for GOG_KEYRING_PASSWORD
  - [ ] New email arrival triggers inbox agent notification within 30 seconds

- [ ] **Memory hygiene: monthly cron running, Healthchecks.io monitoring**
  - [ ] `memory-hygiene.sh` script created and tested
  - [ ] Ofelia job label added to gateway container
  - [ ] Cron schedule: 1st of every month at 3 AM
  - [ ] Script removes empty and stub memory files
  - [ ] Script verifies MEMORY.md existence and integrity
  - [ ] Script reports memory statistics
  - [ ] Healthchecks.io monitor created and receiving pings
  - [ ] Manual test run passes

- [ ] **Context compression: long sessions don't lose important context**
  - [ ] Anchored Iterative Summarization enabled in openclaw.json
  - [ ] Compression triggers at 75% context window
  - [ ] Anchored facts (important decisions, key data) survive compression
  - [ ] Routine conversation is properly summarized
  - [ ] Sessions can run 20+ turns without context exhaustion

- [ ] **GitHub RR: test execution distributed to homelab machines via Tailscale**
  - [ ] RR installed on dev Mac
  - [ ] `~/.rr/config.yaml` configured with homelab hosts using Tailscale IPs
  - [ ] `.rr.yaml` project config created with test task definitions
  - [ ] SSH connectivity verified from dev Mac to all RR hosts
  - [ ] Test task runs successfully on remote host via `rr test`
  - [ ] Output streams back to dev Mac in real-time
  - [ ] Integration architecture with Claude Code documented
