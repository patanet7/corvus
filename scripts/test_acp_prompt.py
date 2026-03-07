#!/usr/bin/env python3
"""Live test: send a prompt to codex-acp and stream the response.

Usage: uv run python scripts/test_acp_prompt.py
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


async def main() -> None:
    workspace = "/tmp/corvus-acp-test"
    os.makedirs(workspace, exist_ok=True)

    print("Spawning codex-acp...")
    proc = await asyncio.create_subprocess_exec(
        "npx", "-y", "@zed-industries/codex-acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"  [stderr] {text}")
    stderr_task = asyncio.create_task(drain_stderr())

    assert proc.stdout is not None
    assert proc.stdin is not None

    async def read_one(timeout: float = 30.0) -> dict | None:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            if line:
                return json.loads(line.decode("utf-8"))
        except (TimeoutError, json.JSONDecodeError):
            pass
        return None

    # Initialize
    print(">>> initialize")
    await send(proc, req("initialize", {
        "protocolVersion": 1,
        "clientInfo": {"name": "corvus-test", "version": "0.1.0"},
        "capabilities": {},
    }))
    init = await read_one()
    agent_info = init["result"]["agentInfo"] if init else {}
    print(f"  Agent: {agent_info.get('name')} v{agent_info.get('version')}")

    # New session
    print(">>> session/new")
    await send(proc, req("session/new", {"cwd": workspace, "mcpServers": []}))
    sess = await read_one()
    session_id = sess["result"]["sessionId"] if sess else ""
    modes = sess["result"].get("modes", {}) if sess else {}
    print(f"  Session: {session_id}")
    print(f"  Mode: {modes.get('currentModeId', '?')}")

    # Send prompt — using 'prompt' field (not 'message')
    print("\n>>> session/prompt: 'What is 2+2? Reply with just the number.'")
    await send(proc, req("session/prompt", {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": "What is 2+2? Reply with just the number."}],
    }))

    # Stream all updates until we get the response or timeout
    print("\n--- Streaming response ---")
    full_text = ""
    done = False
    while not done:
        msg = await read_one(timeout=30.0)
        if msg is None:
            print("(timeout)")
            break

        if "method" in msg:
            method = msg["method"]
            params = msg.get("params", {})

            if method == "session/update":
                update = params.get("update", {})
                update_type = update.get("sessionUpdate", "")
                if update_type == "agent_message_chunk":
                    content = update.get("content", {})
                    text = content.get("text", "") if isinstance(content, dict) else str(content)
                    full_text += text
                    sys.stdout.write(text)
                    sys.stdout.flush()
                elif update_type == "agent_thought_chunk":
                    content = update.get("content", {})
                    text = content.get("text", "") if isinstance(content, dict) else str(content)
                    sys.stdout.write(f"[think] {text}")
                    sys.stdout.flush()
                elif update_type == "tool_call":
                    print(f"\n  [tool] {update.get('title', '?')} (kind={update.get('kind', '?')})")
                elif update_type == "tool_call_update":
                    print(f"\n  [tool_update] {update.get('toolCallId', '?')} status={update.get('status', '?')}")
                else:
                    print(f"\n  [update] {update_type}: {json.dumps(update)[:200]}")
            else:
                print(f"\n  [notif] {method}: {json.dumps(params)[:200]}")

        elif "id" in msg:
            if "error" in msg:
                print(f"\n  [error] {msg['error']}")
                done = True
            elif "result" in msg:
                print(f"\n  [result] {json.dumps(msg['result'])[:200]}")
                done = True

    print(f"\n--- Full response: '{full_text.strip()}' ---")

    # Cleanup
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.terminate()
        await proc.wait()
    stderr_task.cancel()
    print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
