# Voice Assistant Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Home Assistant with Google Home (device control via Matter), local voice pipeline (ReSpeaker + Speaches), and TTS announcements on Google Home speakers.

**Architecture:** Three layers — (1) Matterbridge add-on exposes HA entities as Matter devices to Google Home, (2) wyoming-openai bridges Speaches GPU STT/TTS into HA's Assist pipeline for the ReSpeaker satellite, (3) Cast integration + openai_tts sends Speaches audio to Nest speakers.

**Tech Stack:** Home Assistant 2026.2.3 (HAOS), Matterbridge, wyoming-openai, Speaches (Whisper STT + Kokoro TTS), ESPHome, Google Cast, HACS

**Design doc:** `docs/plans/2026-02-28-voice-assistant-integration-design.md`

---

### Task 1: Update wyoming-openai Compose Config

The container runs but is missing explicit STT/TTS model config — it works because Speaches auto-selects defaults, but we should be explicit for reliability.

**Files:**
- Modify: `infra/stacks/laptop-server/mlstack/compose.yaml:30-45`

**Step 1: Update wyoming-openai environment block**

Replace the current environment section with explicit model/voice configuration:

```yaml
  wyoming-openai:
    image: ghcr.io/roryeckel/wyoming_openai:latest
    container_name: wyoming-openai
    restart: unless-stopped
    ports:
      - "10300:10300"
    environment:
      - WYOMING_URI=tcp://0.0.0.0:10300
      - WYOMING_LOG_LEVEL=INFO
      - WYOMING_LANGUAGES=en
      # STT via Speaches Whisper
      - STT_BACKEND=OPENAI
      - STT_OPENAI_URL=http://speaches:8000/v1
      - STT_OPENAI_KEY=dummy
      - STT_MODELS=Systran/faster-distil-whisper-large-v3
      - STT_TEMPERATURE=0.0
      # TTS via Speaches Kokoro
      - TTS_BACKEND=OPENAI
      - TTS_OPENAI_URL=http://speaches:8000/v1
      - TTS_OPENAI_KEY=dummy
      - TTS_MODELS=kokoro
      - TTS_VOICES=af_heart,af_bella,af_nova,am_adam,am_michael,am_echo
      - TTS_STREAMING_MODELS=kokoro
      - TTS_STREAMING_MIN_WORDS=3
      - TTS_SPEED=1.0
```

**Step 2: Deploy to laptop-server**

Run:
```bash
# Push to Forgejo (Komodo will autodeploy)
GIT_SSH_COMMAND="ssh -o ProxyCommand='ssh -W localhost:2222 patanet7@100.116.213.55'" git push forgejo main
```

Or manual deploy:
```bash
ssh patanet7@192.168.1.200 "cd /etc/komodo/stacks/mlstack && docker compose pull wyoming-openai && docker compose up -d wyoming-openai"
```

**Step 3: Verify wyoming-openai restarts cleanly**

Run:
```bash
ssh patanet7@192.168.1.200 "docker logs wyoming-openai --tail 30"
```

Expected: See `STT Model:` and `TTS Voice Model:` entries listing the configured models, ending with `Starting server at tcp://0.0.0.0:10300`.

**Step 4: Commit**

```bash
git add infra/stacks/laptop-server/mlstack/compose.yaml
git commit -m "feat(voice): add explicit STT/TTS model config to wyoming-openai"
```

---

### Task 2: Configure HA External/Internal URL

Cast devices resolve URLs via Google public DNS (8.8.8.8). TTS audio URLs must use a publicly resolvable hostname with a valid cert. Your SWAG proxy at `homeassistant.absolvbass.com` handles this.

**Step 1: Set URLs via HA API**

This requires the HA UI since the network settings aren't exposed via REST API. Do it manually:

- HA UI → Settings → System → Network
- Set **Home Assistant URL** (external): `https://homeassistant.absolvbass.com`
- Set **Local network** (internal): `http://192.168.1.49:8123`

**Step 2: Verify**

Run:
```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -H "Authorization: Bearer $HA_T" "http://192.168.1.49:8123/api/config" | \
python3 -c "import sys,json; d=json.load(sys.stdin); print('external_url:', d.get('external_url')); print('internal_url:', d.get('internal_url'))"
```

Expected:
```
external_url: https://homeassistant.absolvbass.com
internal_url: http://192.168.1.49:8123
```

---

### Task 3: Set Wake Words on ReSpeaker Lite

The ReSpeaker has two wake word slots, both currently `no_wake_word`. We'll set:
- Slot 1: "Okay Nabu" (primary, local pipeline)
- Slot 2: "Hey Jarvis" (secondary, for future cloud fallback pipeline)

**Step 1: Set wake word via HA API**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/select/select_option" \
  -d '{"entity_id": "select.respeaker_lite_wake_word", "option": "Okay Nabu"}'
```

**Step 2: Set second wake word**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/select/select_option" \
  -d '{"entity_id": "select.respeaker_lite_wake_word_2", "option": "Hey Jarvis"}'
```

**Step 3: Verify**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -H "Authorization: Bearer $HA_T" "http://192.168.1.49:8123/api/states/select.respeaker_lite_wake_word" | \
python3 -c "import sys,json; d=json.load(sys.stdin); print('Wake word 1:', d['state'])"
```

Expected: `Wake word 1: Okay Nabu`

**Step 4: Test wake word detection**

Say "Okay Nabu" near the ReSpeaker Lite. The LED should light up and the satellite should enter listening mode. Check HA logs or the satellite entity state:

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -H "Authorization: Bearer $HA_T" "http://192.168.1.49:8123/api/states/assist_satellite.respeaker_lite_assist_satellite" | \
python3 -c "import sys,json; d=json.load(sys.stdin); print('State:', d['state'])"
```

Expected during listening: `State: listening` (returns to `idle` after timeout)

---

### Task 4: Configure/Verify Assist Voice Pipeline

The Wyoming STT and TTS are registered in HA (`stt.faster_whisper`, `tts.openai`). Need to ensure a pipeline exists that uses them.

**Step 1: Check existing pipelines via WebSocket API**

HA pipelines are managed via WebSocket, not REST. Use the HA UI:

- HA UI → Settings → Voice Assistants
- Check if a pipeline exists that uses "openai" STT and "openai" TTS
- If not, click "Add Assistant":
  - Name: `Local — Speaches`
  - Language: English
  - Conversation agent: Home Assistant
  - Speech-to-text: `openai` (the Wyoming STT entity)
  - Text-to-speech: `openai` (the Wyoming TTS entity)
  - Wake word: (handled by satellite, not pipeline)

**Step 2: Set as preferred pipeline for ReSpeaker**

- HA UI → Settings → Devices & Services → ESPHome
- Find "respeaker-lite" device → Configure
- Or set via entity: `select.respeaker_lite_assistant` → select "Home Assistant" (which points to the configured pipeline)

Alternatively via API:
```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/select/select_option" \
  -d '{"entity_id": "select.respeaker_lite_assistant", "option": "Home Assistant"}'
```

Note: The `preferred` option auto-selects the default pipeline. If there's only one pipeline with Wyoming, `preferred` should work.

**Step 3: End-to-end test**

Say "Okay Nabu" → wait for beep/LED → say "What time is it?"

Expected: ReSpeaker LED activates, audio is sent to HA, processed through Wyoming STT (Speaches Whisper), HA responds with the time, Wyoming TTS (Speaches Kokoro) generates audio, plays back through ReSpeaker speaker.

If it fails, check:
```bash
# Wyoming-openai logs
ssh patanet7@192.168.1.200 "docker logs wyoming-openai --tail 50"

# Speaches logs
ssh patanet7@192.168.1.200 "docker logs speaches --tail 50"
```

---

### Task 5: Install Matterbridge Add-on

**Step 1: Install Matterbridge in HA**

This must be done through the HA UI (add-on installation isn't available via REST API):

- HA UI → Settings → Add-ons → Add-on Store
- Click three-dot menu (top right) → Repositories
- Add: `https://github.com/Luligu/matterbridge-home-assistant-addon`
- Refresh the page
- Find "Matterbridge" in the list → Install
- Start the add-on
- Enable "Show in sidebar" for easy access

**Step 2: Configure Matterbridge**

- Open Matterbridge from the sidebar
- It auto-discovers HA entities
- Select which entity domains to expose:
  - Lights
  - Switches
  - Covers/blinds
  - Locks
  - Scenes (if desired)
- A QR code appears on the config page

**Step 3: Pair with Google Home**

- Open Google Home app on phone
- Devices tab → Add → New device → Matter-enabled device
- Scan the QR code from Matterbridge UI
- Google Home discovers and adds the Matter devices
- Say "Hey Google, sync my devices"

**Step 4: Test**

- "Hey Google, turn on [light name]" (from phone)
- "Hey Google, turn off [light name]" (from Google Home Hub)
- Verify the command executes in HA (check entity state changes)

**Step 5: Verify phone control works away from speakers**

- On your phone (same network), say "OK Google, what lights are on?"
- Should list HA-exposed lights via Matter

---

### Task 6: Test TTS to Google Home Hub via Cast

The Google Cast integration should have auto-discovered `media_player.home_hub`.

**Step 1: Test Google Translate TTS to Home Hub**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/tts/speak" \
  -d '{
    "entity_id": "tts.google_translate_en_com",
    "media_player_entity_id": "media_player.home_hub",
    "message": "Hello, this is a test announcement from Home Assistant."
  }'
```

Expected: The Google Home Hub speaks the message aloud.

If it fails with a URL resolution error, verify:
- `external_url` is set (Task 2)
- The Home Hub can reach `homeassistant.absolvbass.com` (it resolves via Google DNS 8.8.8.8 to your SWAG proxy)

**Step 2: Test Wyoming/Speaches TTS to Home Hub**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/tts/speak" \
  -d '{
    "entity_id": "tts.openai",
    "media_player_entity_id": "media_player.home_hub",
    "message": "Hello, this is Kokoro speaking through Speaches on the GPU."
  }'
```

Expected: The Home Hub speaks the message using Kokoro's voice (noticeably more natural than Google Translate).

---

### Task 7: (Optional) Install HACS + openai_tts Integration

If Wyoming TTS works for Cast announcements (Task 6 Step 2), this task is optional. The `openai_tts` HACS integration provides a dedicated `tts.*` entity pointing directly at Speaches, useful if you want more control over voices/models independent of the Wyoming bridge.

**Step 1: Install HACS**

This requires HA UI + terminal access:

- HA UI → Settings → Add-ons → Add-on Store
- Search for "Terminal & SSH" or "Advanced SSH & Web Terminal" → Install and start
- In the terminal, run:
  ```bash
  wget -O - https://get.hacs.xyz | bash -
  ```
- Restart HA: Settings → System → Restart
- After restart: Settings → Devices & Services → Add Integration → HACS
- Authorize with GitHub account

**Step 2: Install openai_tts custom integration**

- HACS → Integrations → Explore & Download Repositories
- Search: "OpenAI TTS"
- Install `sfortis/openai_tts`
- Restart HA

**Step 3: Configure openai_tts**

- Settings → Devices & Services → Add Integration → OpenAI TTS
- Endpoint URL: `http://192.168.1.200:8000` (Speaches direct — not through Wyoming)
- API Key: `dummy` (or any string — Speaches doesn't require one)
- Model: `kokoro`
- Voice: `af_heart`

**Step 4: Test**

```bash
HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-) && \
curl -s -X POST -H "Authorization: Bearer $HA_T" -H "Content-Type: application/json" \
  "http://192.168.1.49:8123/api/services/tts/speak" \
  -d '{
    "entity_id": "tts.openai_tts",
    "media_player_entity_id": "media_player.home_hub",
    "message": "This is Speaches Kokoro speaking directly through the OpenAI TTS integration."
  }'
```

---

### Task 8: Create a TTS Announcement Helper Automation

Create a reusable HA automation that other automations can call for announcements with Speaches primary / Google Translate fallback.

**Step 1: Create script in HA**

HA UI → Settings → Automations & Scenes → Scripts → Add Script → Edit in YAML:

```yaml
alias: "Announce on Speakers"
description: "TTS announcement with Speaches primary, Google Translate fallback"
mode: queued
max: 5
fields:
  message:
    description: "The message to announce"
    required: true
    selector:
      text:
  target_speaker:
    description: "Target media player entity"
    required: false
    default: "media_player.home_hub"
    selector:
      entity:
        domain: media_player
sequence:
  - choose:
      - conditions:
          - condition: state
            entity_id: tts.openai
            state: "unknown"
            # Wyoming TTS is available (state is "unknown" when idle, which is fine)
            # If it were truly unavailable, the entity wouldn't exist
        sequence:
          - action: tts.speak
            target:
              entity_id: tts.openai
            data:
              media_player_entity_id: "{{ target_speaker }}"
              message: "{{ message }}"
    default:
      - action: tts.speak
        target:
          entity_id: tts.google_translate_en_com
        data:
          media_player_entity_id: "{{ target_speaker }}"
          message: "{{ message }}"
```

Note: The fallback logic may need adjustment based on how the TTS entity behaves when Speaches/Wyoming is down. A more robust check would be a `binary_sensor` that pings the Speaches health endpoint.

**Step 2: Test the script**

HA UI → Settings → Automations & Scenes → Scripts → "Announce on Speakers" → Run with message: "Testing the announcement system."

---

### Task 9: Commit and Document

**Step 1: Commit compose changes**

```bash
git add infra/stacks/laptop-server/mlstack/compose.yaml
git add docs/plans/2026-02-28-voice-assistant-integration-design.md
git add docs/plans/2026-02-28-voice-assistant-implementation.md
git commit -m "feat(voice): voice assistant integration plan + wyoming-openai config"
```

**Step 2: Push to Forgejo**

```bash
GIT_SSH_COMMAND="ssh -o ProxyCommand='ssh -W localhost:2222 patanet7@100.116.213.55'" git push forgejo main
```

---

## Execution Order & Dependencies

```
Task 1 (wyoming-openai config) ──┐
Task 2 (external URL)  ──────────┤
Task 3 (wake words) ─────────────┼──→ Task 4 (verify pipeline) ──→ Task 6 (test Cast TTS)
                                  │                                        │
Task 5 (Matterbridge) ───────────┘                               Task 7 (HACS + openai_tts, optional)
                                                                           │
                                                                  Task 8 (announcement automation)
                                                                           │
                                                                  Task 9 (commit + push)
```

Tasks 1-3 and 5 are independent and can be done in parallel.
Task 4 depends on Tasks 1 and 3.
Task 6 depends on Tasks 2 and 4.
Tasks 7-8 are optional enhancements.

## Notes

- **HA UI required** for Tasks 2, 4 (partially), 5, 7 — these involve add-on installation and pipeline configuration that can't be done purely via REST API.
- **No mocks** — all testing is behavioral (talk to the ReSpeaker, listen for responses, verify via API state changes).
- **Credential safety** — all API calls use `HA_T=$(grep '^HA_TOKEN=' ~/.secrets/claw.env | cut -d= -f2-)` pattern. Token never echoed or exported.
