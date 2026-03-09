#!/usr/bin/env python3
"""Live integration test for ACP protocol against codex-acp.

Verifies the full ACP lifecycle: spawn → initialize → session/new → prompt → stream.
Requires codex-acp to be installed (npx @zed-industries/codex-acp) and a valid
Codex auth (ChatGPT subscription, CODEX_API_KEY, or OPENAI_API_KEY).

Usage: uv run python scripts/test_acp_live.py
"""

import asyncio
import json
import os
import sys

REQ_ID = 0


def req(method: str, params: dict) -> dict:
    global REQ_ID
    REQ_ID += 1
    return {"jsonrpc": "2.0", "id": REQ_ID, "method": method, "params": params}


async def send(proc: asyncio.subprocess.Process, msg: dict) -> None:
    line = json.dumps(msg, separators=(",", ":")) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line.encode("utf-8"))
    await proc.stdin.drain()


async def read_one(proc: asyncio.subprocess.Process, timeout: float = 30.0) -> dict | None:
    assert proc.stdout is not None
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        if line:
            return json.loads(line.decode("utf-8"))
    except (TimeoutError, json.JSONDecodeError):
        pass
    return None


async def main() -> None:
    workspace = "/tmp/corvus-acp-test"
    os.makedirs(workspace, exist_ok=True)
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name} — {detail}")

    print("=== ACP Live Integration Test ===\n")
    print("Spawning codex-acp...")

    proc = await asyncio.create_subprocess_exec(
        "npx", "-y", "@zed-industries/codex-acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )

    # Drain stderr silently
    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
    stderr_task = asyncio.create_task(drain_stderr())

    # --- Test 1: Initialize ---
    print("\n[1] Initialize")
    await send(proc, req("initialize", {
        "protocolVersion": 1,
        "clientInfo": {"name": "corvus-test", "version": "0.1.0"},
        "clientCapabilities": {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        },
    }))
    init = await read_one(proc)
    check("Response received", init is not None)
    if init:
        result = init.get("result", {})
        check("Has protocolVersion", "protocolVersion" in result, str(result.keys()))
        check("protocolVersion is int", isinstance(result.get("protocolVersion"), int))
        check("Has agentCapabilities", "agentCapabilities" in result)
        check("Has agentInfo", "agentInfo" in result)
        agent_info = result.get("agentInfo", {})
        print(f"         Agent: {agent_info.get('name')} v{agent_info.get('version')}")
        check("Has authMethods", "authMethods" in result)
        auth_ids = [m.get("id") for m in result.get("authMethods", [])]
        print(f"         Auth: {auth_ids}")

    # --- Test 2: Session Create ---
    print("\n[2] Session Create")
    await send(proc, req("session/new", {"cwd": workspace, "mcpServers": []}))
    sess = await read_one(proc)
    check("Response received", sess is not None)
    session_id = ""
    if sess:
        result = sess.get("result", {})
        session_id = result.get("sessionId", "")
        check("Has sessionId", bool(session_id), str(result.keys()))
        modes = result.get("modes", {})
        check("Has modes", bool(modes))
        current_mode = modes.get("currentModeId", "")
        available = [m.get("id") for m in modes.get("availableModes", [])]
        print(f"         Session: {session_id[:20]}...")
        print(f"         Mode: {current_mode} (available: {available})")

    # --- Test 3: Send Prompt ---
    print("\n[3] Send Prompt")
    if session_id:
        await send(proc, req("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "What is 2+2? Reply with just the number."}],
        }))

        # Read streaming updates
        got_update = False
        got_response = False
        update_types = set()
        full_text = ""

        for _ in range(50):  # max 50 messages
            msg = await read_one(proc, timeout=15.0)
            if msg is None:
                break

            if "method" in msg and msg["method"] == "session/update":
                got_update = True
                update = msg.get("params", {}).get("update", {})
                update_type = update.get("sessionUpdate", "")
                update_types.add(update_type)

                if update_type == "agent_message_chunk":
                    content = update.get("content", {})
                    text = content.get("text", "") if isinstance(content, dict) else str(content)
                    full_text += text

            elif "id" in msg:
                got_response = True
                if "error" in msg:
                    err = msg["error"]
                    err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    err_data = err.get("data", {}) if isinstance(err, dict) else {}
                    err_detail = err_data.get("message", "") if isinstance(err_data, dict) else str(err_data)
                    print(f"         Error: {err_msg}")
                    if err_detail:
                        print(f"         Detail: {err_detail}")
                    # Usage/auth limits are not protocol failures
                    full_err = f"{err_msg} {err_detail}".lower()
                    if any(k in full_err for k in ("usage", "limit", "auth", "subscription")):
                        check("Prompt accepted (auth/usage limit)", True)
                    else:
                        check("Prompt accepted", False, f"{err_msg}: {err_detail}")
                else:
                    check("Prompt completed", True)
                    if full_text:
                        print(f"         Response: {full_text.strip()[:100]}")
                break

        check("Got session/update notifications", got_update)
        if update_types:
            print(f"         Update types seen: {sorted(update_types)}")
    else:
        check("Prompt (skipped — no session)", False, "no session_id")

    # --- Cleanup ---
    print("\n=== Cleanup ===")
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.terminate()
        await proc.wait()
    stderr_task.cancel()

    # --- Summary ---
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
