#!/usr/bin/env python3
"""Live test: spawn codex-acp and verify ACP handshake.

Usage: uv run python scripts/test_acp_handshake.py
"""

import asyncio
import json
import os
import sys


async def main() -> None:
    cmd = ["npx", "-y", "@zed-industries/codex-acp"]
    workspace = "/tmp/corvus-acp-test"
    os.makedirs(workspace, exist_ok=True)

    print(f"Spawning: {' '.join(cmd)}")
    print(f"Workspace: {workspace}")
    print()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )
    print(f"PID: {proc.pid}")

    # Drain stderr in background
    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            print(f"  [stderr] {line.decode('utf-8', errors='replace').rstrip()}")

    stderr_task = asyncio.create_task(drain_stderr())

    # Send initialize request
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "0.1",
            "clientInfo": {"name": "corvus-test", "version": "0.1.0"},
            "capabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": {"create": True, "resize": True, "input": True},
            },
        },
    }

    print(">>> Sending initialize request...")
    line = json.dumps(init_req, separators=(",", ":")) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line.encode("utf-8"))
    await proc.stdin.drain()

    # Read response with timeout
    print("<<< Waiting for response...")
    try:
        assert proc.stdout is not None
        resp_line = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
        if resp_line:
            resp = json.loads(resp_line.decode("utf-8"))
            print(f"<<< Response: {json.dumps(resp, indent=2)}")

            if "result" in resp:
                print("\n  ✓ ACP handshake SUCCESS!")
                server_info = resp["result"].get("serverInfo", {})
                print(f"  Server: {server_info.get('name', '?')} v{server_info.get('version', '?')}")
                caps = resp["result"].get("capabilities", {})
                print(f"  Capabilities: {list(caps.keys())}")
            elif "error" in resp:
                print(f"\n  ✗ ACP handshake FAILED: {resp['error']}")
        else:
            print("  ✗ No response received (stdout closed)")
    except TimeoutError:
        print("  ✗ Timeout waiting for response (30s)")

    # Terminate
    print("\nTerminating...")
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
