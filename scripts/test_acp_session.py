#!/usr/bin/env python3
"""Live test: full ACP session with codex-acp — init, auth, new session, prompt.

Usage: uv run python scripts/test_acp_session.py
"""

import asyncio
import json
import os
import sys

REQ_ID = 0


def make_request(method: str, params: dict) -> dict:
    global REQ_ID
    REQ_ID += 1
    return {"jsonrpc": "2.0", "id": REQ_ID, "method": method, "params": params}


async def send(proc: asyncio.subprocess.Process, msg: dict) -> None:
    line = json.dumps(msg, separators=(",", ":")) + "\n"
    print(f"\n>>> {msg['method']} (id={msg.get('id', 'notif')})")
    assert proc.stdin is not None
    proc.stdin.write(line.encode("utf-8"))
    await proc.stdin.drain()


async def read_messages(proc: asyncio.subprocess.Process, timeout: float = 15.0) -> list[dict]:
    """Read all available messages within timeout."""
    messages = []
    assert proc.stdout is not None
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
                messages.append(msg)
                # Print summary
                if "id" in msg and "result" in msg:
                    print(f"<<< Response id={msg['id']}: {json.dumps(msg['result'], indent=2)[:500]}")
                elif "id" in msg and "error" in msg:
                    print(f"<<< Error id={msg['id']}: {msg['error']}")
                elif "method" in msg:
                    params = msg.get("params", {})
                    kind = params.get("kind", params.get("type", ""))
                    print(f"<<< Notification: {msg['method']} kind={kind}")
                    # Print content for text chunks
                    if "content" in params:
                        content = params["content"]
                        if isinstance(content, str):
                            print(f"    content: {content[:200]}")
                else:
                    print(f"<<< Unknown: {json.dumps(msg)[:300]}")

                # If this is a response (has id), return after getting it
                if "id" in msg:
                    return messages
            except json.JSONDecodeError:
                print(f"<<< non-JSON: {text[:200]}")
    except TimeoutError:
        if not messages:
            print("<<< (timeout, no messages)")
    return messages


async def main() -> None:
    cmd = ["npx", "-y", "@zed-industries/codex-acp"]
    workspace = "/tmp/corvus-acp-test"
    os.makedirs(workspace, exist_ok=True)

    print(f"Spawning codex-acp...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )

    # Drain stderr
    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            print(f"  [stderr] {line.decode('utf-8', errors='replace').rstrip()}")
    stderr_task = asyncio.create_task(drain_stderr())

    # Step 1: Initialize
    print("\n=== Step 1: Initialize ===")
    await send(proc, make_request("initialize", {
        "protocolVersion": 1,
        "clientInfo": {"name": "corvus-test", "version": "0.1.0"},
        "capabilities": {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": {"create": True, "resize": True, "input": True},
        },
    }))
    init_msgs = await read_messages(proc)

    if not init_msgs:
        print("✗ No init response")
        proc.terminate()
        return

    # Check auth methods
    init_result = init_msgs[0].get("result", {})
    auth_methods = init_result.get("authMethods", [])
    print(f"\nAuth methods: {[m['id'] for m in auth_methods]}")

    # Step 2: Try to create session (may need auth first)
    print("\n=== Step 2: New Session ===")
    await send(proc, make_request("session/new", {
        "cwd": workspace,
        "mcpServers": [],
    }))
    session_msgs = await read_messages(proc, timeout=20.0)

    if session_msgs:
        last = session_msgs[-1]
        if "result" in last:
            session_id = last["result"].get("sessionId", "")
            print(f"\n✓ Session created: {session_id}")

            # Step 3: Send a simple prompt
            print("\n=== Step 3: Send Prompt ===")
            await send(proc, make_request("session/prompt", {
                "sessionId": session_id,
                "message": "What is 2+2? Reply with just the number.",
            }))

            # Read streaming updates
            print("\nReading streaming updates (20s)...")
            all_msgs = await read_messages(proc, timeout=20.0)
            # Keep reading for more updates
            while True:
                more = await read_messages(proc, timeout=5.0)
                if not more:
                    break
                all_msgs.extend(more)

            print(f"\nTotal messages received: {len(all_msgs)}")
        elif "error" in last:
            print(f"\n✗ Session error: {last['error']}")
            # May need authentication first
            err = last["error"]
            if isinstance(err, dict):
                print(f"  Code: {err.get('code')}, Message: {err.get('message')}")

    # Terminate
    print("\n=== Cleanup ===")
    assert proc.stdin is not None
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
