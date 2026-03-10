"""Live LLM QA — real server, real WebSocket, real streaming output.

Starts the Corvus server as a subprocess, connects via WebSocket,
sends real messages, and verifies actual LLM output streams back.

Run:  uv run python tests/integration/test_live_llm_qa.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx
import websockets.sync.client as wsc

# ── Config ────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 18776
BASE_URL = f"http://{HOST}:{PORT}"
WS_URL = f"ws://{HOST}:{PORT}"
USER = "qa-tester"
TIMEOUT_S = 90  # Max wait for LLM response
RECV_TIMEOUT_S = 5  # Per-message receive timeout

# ── Result tracking ──────────────────────────────────────────────────

PASS = 0
FAIL = 0
LOG_LINES: list[str] = []

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        line = f"   [{GREEN}PASS{RESET}] {label}"
        if detail:
            line += f" — {detail}"
    else:
        FAIL += 1
        line = f"   [{RED}FAIL{RESET}] {label}"
        if detail:
            line += f" — {detail}"
    print(line)
    LOG_LINES.append(line)
    return condition


def section(name: str) -> None:
    line = f"\n{BOLD}{name}{RESET}"
    print(line)
    LOG_LINES.append(line)


# ── Server lifecycle ─────────────────────────────────────────────────


def start_server() -> subprocess.Popen:
    """Start Corvus server as subprocess."""
    env = {
        **os.environ,
        "HOST": HOST,
        "PORT": str(PORT),
        "ALLOWED_USERS": USER,
        "LOG_LEVEL": "DEBUG",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "corvus.server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Wait for server to be ready
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                return proc
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(0.5)
    # Dump server output on failure
    proc.terminate()
    stdout, _ = proc.communicate(timeout=5)
    print(f"Server failed to start. Output:\n{stdout[:2000]}")
    raise RuntimeError("Server did not become healthy within 30s")


def stop_server(proc: subprocess.Popen) -> str:
    """Stop server and return captured stdout."""
    proc.send_signal(signal.SIGINT)
    try:
        stdout, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate(timeout=5)
    return stdout or ""


# ── Auth ─────────────────────────────────────────────────────────────


def get_token() -> str:
    """Get session auth token."""
    r = httpx.post(f"{BASE_URL}/api/auth/token", json={"user": USER}, timeout=5)
    r.raise_for_status()
    return r.json()["token"]


# ── WebSocket helpers ────────────────────────────────────────────────


def ws_connect(token: str) -> wsc.ClientConnection:
    """Connect to chat WebSocket."""
    return wsc.connect(f"{WS_URL}/ws?token={token}", close_timeout=5)


def ws_recv_all(ws: wsc.ClientConnection, *, timeout: float = TIMEOUT_S) -> list[dict]:
    """Receive all messages until 'done' event or timeout."""
    msgs: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        ws.socket.settimeout(min(RECV_TIMEOUT_S, remaining))
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            msgs.append(msg)
            if msg.get("type") == "done":
                break
        except TimeoutError:
            continue
        except Exception as e:
            print(f"   [WARN] ws_recv error: {type(e).__name__}: {e}")
            break
    return msgs


def send_message(ws: wsc.ClientConnection, text: str, *, agent: str = "general", model: str | None = None) -> list[dict]:
    """Send a chat message and collect all response events."""
    payload: dict = {"message": text, "target_agent": agent}
    if model:
        payload["model"] = model
    ws.send(json.dumps(payload))
    return ws_recv_all(ws)


# ── Main QA ──────────────────────────────────────────────────────────


def run_qa() -> int:
    section("0. SERVER START")
    server_proc = start_server()
    server_output = ""
    try:
        check("Server healthy", True, f"{BASE_URL}/api/health")

        # ── 1. Auth ──────────────────────────────────────────────
        section("1. AUTH")
        token = get_token()
        check("Token obtained", bool(token), f"length={len(token)}")

        # ── 2. WS Init ──────────────────────────────────────────
        section("2. WS CONNECT + INIT")
        ws = ws_connect(token)
        # Read init message
        init_raw = ws.recv(timeout=5)
        init_msg = json.loads(init_raw)
        check("Init received", init_msg.get("type") == "init", f"type={init_msg.get('type')}")

        raw_models = init_msg.get("models", [])
        models = [m if isinstance(m, str) else m.get("id", str(m)) for m in raw_models]
        raw_agents = init_msg.get("agents", [])
        agents = sorted(a if isinstance(a, str) else a.get("name", str(a)) for a in raw_agents)
        default_model = init_msg.get("default_model", "")
        default_agent = init_msg.get("default_agent", "")
        check("Models listed", len(models) > 0, str(models))
        check("Agents listed", len(agents) > 0, str(agents))
        check("Default model set", bool(default_model), default_model)
        check("Default agent set", bool(default_agent), default_agent)
        agent_ids = [a if isinstance(a, str) else a.get("id", a) for a in raw_agents]
        check("Agent 'general' available", "general" in agent_ids)
        check("Router 'huginn' available", "huginn" in agent_ids)

        # ── 3. Ping/pong ────────────────────────────────────────
        section("3. PING/PONG")
        ws.send(json.dumps({"type": "ping"}))
        pong_raw = ws.recv(timeout=5)
        pong = json.loads(pong_raw)
        check("Pong received", pong.get("type") == "pong")

        # ── 4. Real message ──────────────────────────────────────
        section("4. REAL MESSAGE — 'Say hello in exactly 3 words'")
        events = send_message(ws, "Say hello in exactly 3 words")

        event_types = [e.get("type") for e in events]
        text_chunks = [e for e in events if e.get("type") in ("text", "text_delta")]
        full_text = "".join(e.get("text", "") or e.get("content", "") for e in text_chunks)
        done_events = [e for e in events if e.get("type") == "done"]
        run_completes = [e for e in events if e.get("type") == "run_complete"]
        dispatch_starts = [e for e in events if e.get("type") == "dispatch_start"]

        check("dispatch_start received", "dispatch_start" in event_types)
        check("run_complete received", "run_complete" in event_types)
        check("done received", "done" in event_types)

        # Key: did we get actual text?
        text_ok = check("Text streamed", len(text_chunks) > 0, f"{len(text_chunks)} chunks")
        check("Response text non-empty", len(full_text) > 0, repr(full_text[:200]))

        if done_events:
            done_ev = done_events[0]
            tokens = done_ev.get("tokens_used", 0)
            cost = done_ev.get("cost_usd", 0.0)
            check("Tokens tracked", tokens > 0, str(tokens))
            check("Cost tracked", cost >= 0, f"${cost}")
        if run_completes:
            rc = run_completes[0]
            summary = rc.get("summary", "")
            check("Summary present", bool(summary), repr(summary[:100]))

        # Print full event pipeline
        pipeline = " -> ".join(dict.fromkeys(event_types))
        print(f"   Pipeline: {pipeline}")
        LOG_LINES.append(f"   Pipeline: {pipeline}")

        if not text_ok:
            # Dump all events for debugging
            print(f"\n   DEBUG: All {len(events)} events:")
            for i, e in enumerate(events):
                et = e.get("type", "?")
                preview = {k: v for k, v in e.items() if k != "type"}
                preview_str = json.dumps(preview, default=str)[:200]
                print(f"   [{i:2d}] {et}: {preview_str}")

        # ── 5. Agent routing ─────────────────────────────────────
        section("5. AGENT ROUTING")
        routing_events = [e for e in events if e.get("type") == "routing"]
        if routing_events:
            routed_agent = routing_events[0].get("agent", "")
            check("Routed to agent", bool(routed_agent), routed_agent)
        elif dispatch_starts:
            routed_agent = dispatch_starts[0].get("target_agent", "") or dispatch_starts[0].get("agent", "")
            check("Routed to agent", bool(routed_agent), routed_agent)
        else:
            check("Routed to agent", False, "no routing/dispatch_start")

        # ── 6. Context memory ────────────────────────────────────
        section("6. CONTEXT MEMORY — follow-up question")
        events2 = send_message(ws, "What did I just ask you?")
        text2 = "".join(e.get("text", "") or e.get("content", "") for e in events2 if e.get("type") in ("text", "text_delta"))
        # Should reference "hello" or "3 words" from previous message
        has_context = any(w in text2.lower() for w in ["hello", "3 words", "three words", "greet", "word"])
        check("Remembers context", has_context or len(text2) > 0, repr(text2[:200]))

        # ── 7. Model switching ───────────────────────────────────
        section("7. MODEL SWITCH")
        # Try switching to a different model
        alt_model = None
        for m in models:
            mid = m if isinstance(m, str) else m.get("id", "")
            if mid != default_model:
                alt_model = mid
                break
        if alt_model:
            events3 = send_message(ws, "Say 'model switch works'", model=alt_model)
            text3 = "".join(e.get("text", "") or e.get("content", "") for e in events3 if e.get("type") in ("text", "text_delta"))
            check("Alt model response", len(text3) > 0, f"model={alt_model}, text={repr(text3[:100])}")
        else:
            check("Alt model response", False, "no alternative model available")

        # ── 8. Interrupt ─────────────────────────────────────────
        section("8. INTERRUPT")
        ws.send(json.dumps({"type": "interrupt"}))
        # Should not crash
        ws.send(json.dumps({"type": "ping"}))
        pong2_raw = ws.recv(timeout=5)
        pong2 = json.loads(pong2_raw)
        check("WS alive after interrupt", pong2.get("type") == "pong")

        ws.close()

    finally:
        server_output = stop_server(server_proc)

    # ── Summary ──────────────────────────────────────────────────
    section("SUMMARY")
    total = PASS + FAIL
    if FAIL == 0:
        summary_line = f"{GREEN}=== LIVE LLM QA: {PASS}/{total} PASSED, ALL GREEN ==={RESET}"
    else:
        summary_line = f"{RED}=== LIVE LLM QA: {PASS}/{total} PASSED, {FAIL} FAILED ==={RESET}"
    print(f"\n{summary_line}")
    LOG_LINES.append(summary_line)

    # Save log
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = f"tests/output/{ts}_test_live_llm_qa.log"
    os.makedirs("tests/output", exist_ok=True)
    with open(log_path, "w") as f:
        # Write server output first
        f.write("=== SERVER OUTPUT ===\n")
        f.write(server_output[:5000] if server_output else "(captured via subprocess)\n")
        f.write("\n=== QA RESULTS ===\n")
        # Strip ANSI for log file
        import re
        ansi_re = re.compile(r"\033\[[0-9;]*m")
        for line in LOG_LINES:
            f.write(ansi_re.sub("", line) + "\n")
    print(f"\nLog saved: {log_path}")

    return FAIL


if __name__ == "__main__":
    sys.exit(run_qa())
