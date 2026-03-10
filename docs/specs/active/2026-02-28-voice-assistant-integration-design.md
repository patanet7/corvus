---
title: "Voice Assistant Integration Design"
type: spec
status: approved
date: 2026-02-28
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Voice Assistant Integration Design

**Date:** 2026-02-28
**Status:** Approved
**Scope:** Home Assistant + Google Assistant + Speaches + ReSpeaker Lite

---

## Current State (discovered via HA API, 2026-02-28)

**HA Version:** 2026.2.3 (HAOS)

**Already Working:**
- ReSpeaker Lite — ESPHome assist satellite (XMOS firmware v1.1.0), dual wake word slots, media player
- Wyoming STT — `stt.faster_whisper` registered as OpenAI-compatible provider
- Wyoming TTS — `tts.openai` registered as OpenAI-compatible provider (Kokoro voices: af_nova, am_echo, etc.)
- wyoming-openai container — Up 5 days, healthy, listening on tcp://0.0.0.0:10300
- Speaches container — Up 3 days, healthy, GPU-accelerated
- Google Cast — Home Hub discovered (`media_player.home_hub`) — this IS the Matter controller
- Google Translate TTS — `tts.google_translate_en_com` active
- Matter Server add-on — running
- Assist Pipeline + Conversation agent — configured
- Additional Cast devices: Denon AVR-X4700H, LG TV, SHIELD, JBL Charge 5 Wi-Fi

**Needs Configuration:**
- Wake words not set — both `select.respeaker_lite_wake_word` and `wake_word_2` are `no_wake_word`
- External/internal URL not configured (both null) — needed for Cast TTS
- STT/TTS entities show "unknown" state — may need pipeline wiring

---

## Goals

1. **Google Home device control** — "Hey Google / OK Google" from phone and Nest speakers controls HA entities (lights, switches, etc.) via Matter protocol, fully local
2. **Local voice pipeline** — ReSpeaker Lite (ESPHome) as a voice satellite using Speaches (GPU-accelerated STT/TTS) through HA's Assist pipeline
3. **TTS to Google Home speakers** — HA announces/speaks through Nest speakers using Speaches TTS (primary) and Google Translate TTS (fallback)
4. **Phone control** — "OK Google" from Android phone controls HA devices when on home network (same Matterbridge integration)

---

## Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │         Google Home Ecosystem        │
                    │  Phone (OK Google) ←→ Google Home    │
                    │  Nest Speaker ←→ Google Home         │
                    │          ↕ Matter (LAN)              │
                    │    Matterbridge (HA add-on)          │
                    └─────────────┬───────────────────────┘
                                  │
┌────────────┐    ┌───────────────┴───────────────────────┐
│  ReSpeaker │    │       Home Assistant (192.168.1.49)    │
│    Lite    │◄──►│  Assist Pipeline (Local — Speaches)    │
│  (ESPHome) │    │  Cast Integration (Nest speakers)      │
│  microWW   │    │  TTS: Speaches + Google Translate      │
└────────────┘    └───────────────┬───────────────────────┘
                                  │ Wyoming TCP :10300
                    ┌─────────────┴───────────────────────┐
                    │    laptop-server (192.168.1.200)     │
                    │  wyoming-openai → Speaches (GPU)     │
                    │  STT: Whisper  |  TTS: Kokoro        │
                    └─────────────────────────────────────┘
```

---

## Layer 1: Google Home ↔ HA Device Control (Matterbridge)

### What
Expose HA entities as Matter devices to Google Home — 100% local, no cloud, no Nabu Casa subscription.

### Why Matterbridge (not alternatives)
- **Nabu Casa Cloud** ($6.50/mo) adds cloud dependency and latency — rejected for self-hosted setup
- **Manual Google Actions Console** — Google deprecated the old console (Dec 2024), new console at console.home.google.com has broken/stale HA docs, extremely complex setup — rejected
- **Matterbridge** — actively maintained (github.com/Luligu/matterbridge-home-assistant-addon), local-only, free, fast, community standard

### Prerequisites
- A Google Home Hub device (Nest Hub, Nest Mini, or Nest Audio supporting Matter) on the LAN
- HA Matter Server add-on (already installed)

### Setup
1. Install Matterbridge add-on in HA:
   - Settings > Add-ons > Add-on Store > Repositories > add `https://github.com/Luligu/matterbridge-home-assistant-addon`
   - Install "Matterbridge"
2. Configure exposed entity domains (lights, switches, scenes, covers, locks)
3. Pair in Google Home app: Devices > Add device > Matter-enabled device > scan QR code from Matterbridge UI
4. "Hey Google, sync my devices"

### Result
- "Hey Google, turn off the living room lights" — works from phone, speakers, any Google surface
- All commands are LAN-local via Matter protocol
- Google Home routines can include HA devices

### Limitations
- Complex entities (multi-attribute sensors, media players) may not map to Matter device types
- Requires Google Home Hub to stay powered and on-network
- Matter protocol still maturing — some edge cases with entity types

---

## Layer 2: Local Voice Pipeline (ReSpeaker → Speaches → HA Assist)

### Existing State
- **ReSpeaker Lite** — already in HA as ESPHome device (ESP32-S3 + XMOS XU316 DSP)
- **Speaches** — running on laptop-server:8000 with NVIDIA T1200 GPU (CUDA), OpenAI-compatible API
- **wyoming-openai** — defined in mlstack/compose.yaml at port 10300, but was historically in a restart loop

### Pipeline Flow
```
ReSpeaker Lite (ESP32-S3)
    | microWakeWord: "Okay Nabu" (on-device, zero pre-wake audio leaves device)
    | XMOS XU316: hardware AEC + beamforming + noise suppression
    | ESPHome voice_assistant component over Wi-Fi
    v
Home Assistant (192.168.1.49)
    | Assist pipeline → Wyoming TCP to 192.168.1.200:10300
    v
wyoming-openai (laptop-server)
    | HTTP to speaches:8000/v1
    v
Speaches (laptop-server, GPU)
    |- STT: Systran/faster-distil-whisper-large-v3
    |- TTS: Kokoro-82M-v1.0-ONNX (voices: af_heart, af_bella, am_adam, am_michael)
```

### Step 1: Fix and stabilize wyoming-openai

Update compose config (either in mlstack/compose.yaml or break out to separate compose):

```yaml
wyoming-openai:
  image: ghcr.io/roryeckel/wyoming_openai:latest
  container_name: wyoming-openai
  restart: unless-stopped
  ports:
    - "10300:10300"
  environment:
    WYOMING_URI: "tcp://0.0.0.0:10300"
    WYOMING_LOG_LEVEL: "INFO"
    WYOMING_LANGUAGES: "en"
    STT_OPENAI_KEY: "dummy"
    STT_OPENAI_URL: "http://speaches:8000/v1"
    STT_MODELS: "Systran/faster-distil-whisper-large-v3"
    STT_BACKEND: "openai"
    STT_TEMPERATURE: "0.0"
    TTS_OPENAI_KEY: "dummy"
    TTS_OPENAI_URL: "http://speaches:8000/v1"
    TTS_MODELS: "kokoro"
    TTS_VOICES: "af_heart,af_bella,am_adam,am_michael"
    TTS_STREAMING_MODELS: "kokoro"
    TTS_STREAMING_MIN_WORDS: "3"
    TTS_SPEED: "1.0"
```

Debug the restart loop by checking:
- Container logs (`docker logs wyoming-openai`)
- Whether Speaches is reachable from the wyoming-openai container
- HA version compatibility (known issue with HA 2026.1.0, see github.com/roryeckel/wyoming_openai/issues)

### Step 2: Register Wyoming in HA
- Settings > Devices & Services > Add Integration > Wyoming Protocol
- Host: `192.168.1.200`, Port: `10300`

### Step 3: Create Local Assist Pipeline
- Settings > Voice Assistants > Add Assistant
- Name: "Local — Speaches"
- Wake word: "Okay Nabu" (via satellite microWakeWord)
- STT: "Systran/faster-distil-whisper-large-v3 (Wyoming)"
- Conversation agent: "Home Assistant" (built-in NLU)
- TTS: "kokoro (Wyoming)" → Voice: "af_heart"

### Step 4: Verify ReSpeaker ESPHome config
- ESPHome firmware >= 2025.6.2
- voice_assistant component configured with pipeline targeting "Local — Speaches"
- microWakeWord enabled for "okay_nabu"
- XMOS hardware noise suppression means ESPHome `noise_suppression_level: 0` and `auto_gain: 0`

### Optional: Dual Pipeline (Cloud Fallback)
HA 2025.10+ supports two wake word/pipeline pairs per satellite:
- "Okay Nabu" → Local pipeline (Speaches)
- "Hey Jarvis" → Cloud pipeline (Google Cloud STT + Google Translate TTS)

Requires:
- Google Cloud project with Speech-to-Text API enabled
- Service account JSON key in HA /config/
- Google Cloud integration added in HA
- Second pipeline created with cloud STT/TTS
- ESPHome pipeline_selector entity mapping wake words to pipeline IDs

Free tier: 60 min/month (~1,200 short commands).

---

## Layer 3: TTS to Google Home Speakers

### Goal
HA announces through Nest speakers — notifications, alerts, automations.

### Prerequisites
- Google Cast integration (auto-discovered, no config needed)
- Nest speakers visible as `media_player.*` entities in HA

### Critical: External URL Configuration
Cast devices resolve URLs via Google's public DNS (8.8.8.8), not local DNS. Must set:

```yaml
# configuration.yaml
homeassistant:
  external_url: "https://homeassistant.absolvbass.com"
  internal_url: "http://192.168.1.49:8123"
```

The SWAG proxy at `homeassistant.absolvbass.com` with valid wildcard cert ensures Cast devices can fetch TTS audio.

### TTS Engines (in priority order)

**Primary: Speaches TTS via HACS `openai_tts` integration**
- Install `sfortis/openai_tts` from HACS
- Configure: endpoint `http://192.168.1.200:8000`, model `kokoro`, voice `af_heart`
- Creates a standard `tts.openai_tts` entity usable with Cast

**Fallback: Google Translate TTS (built-in)**
- Zero config, already available as `tts.google_en_com`
- Lower quality but works when laptop-server is down

### Example Automation

```yaml
# Announce on Nest speaker with fallback
action: choose
  - conditions:
      - condition: state
        entity_id: binary_sensor.speaches_healthy
        state: "on"
    sequence:
      - action: tts.speak
        target:
          entity_id: tts.openai_tts
        data:
          media_player_entity_id: media_player.nest_speaker
          message: "{{ message }}"
  default:
    - action: tts.speak
      target:
        entity_id: tts.google_en_com
      data:
        media_player_entity_id: media_player.nest_speaker
        message: "{{ message }}"
```

### Nest Audio Quirk
Nest Audio may skip the first portion of audio sampled at 22050 Hz. If experiencing this, ensure TTS output is 44100 Hz (Kokoro via Speaches should default to this, but verify).

---

## Key Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| wyoming-openai restart loop | Blocks local voice pipeline | Debug logs, check Speaches connectivity, pin known-good version |
| HA 2026.1.0 incompatibility | wyoming-openai errors on latest HA | Monitor github.com/roryeckel/wyoming_openai/issues before upgrading |
| Cast TTS URL resolution | Announcements fail on Nest speakers | Set external_url with valid SWAG cert |
| Matterbridge entity mapping | Some HA entities don't expose to Google | Start with simple domains (lights, switches), expand incrementally |
| Speaches downtime | No local STT/TTS | Google Translate TTS fallback + optional Google Cloud STT fallback pipeline |

---

## References

- [Matterbridge HA add-on](https://github.com/Luligu/matterbridge-home-assistant-addon)
- [wyoming-openai](https://github.com/roryeckel/wyoming_openai)
- [Speaches](https://github.com/speaches-ai/speaches)
- [openai_tts HACS integration](https://github.com/sfortis/openai_tts)
- [HA Wyoming integration](https://www.home-assistant.io/integrations/wyoming/)
- [HA Assist pipeline docs](https://developers.home-assistant.io/docs/voice/pipelines/)
- [HA Google Cast integration](https://www.home-assistant.io/integrations/cast/)
- [HA Google Cloud integration](https://www.home-assistant.io/integrations/google_cloud/)
- [ESPHome voice_assistant component](https://esphome.io/components/voice_assistant/)
- [HA Voice Chapter 11 (dual wake word)](https://www.home-assistant.io/blog/2025/10/22/voice-chapter-11)
- [ReSpeaker Lite ESPHome guide](https://smarthomecircle.com/local-voice-assistant-with-seeed-studio-respeaker-lite)
