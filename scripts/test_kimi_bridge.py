"""Test: Full ACP protocol lifecycle with Kimi bridge.

Connects to Kimi bridge and drives the full protocol:
  1. Connect (X-Kimi-Bot-Token)
  2. Send initialize → get capabilities
  3. Send session/new → create session
  4. Send session/prompt → send a user message to K2
  5. Receive session/update → streaming response
  6. Receive result → prompt complete

Run ON LAPTOP-SERVER:
    set -a && source ~/.secrets/claw.env && set +a
    source ~/claw-src/.venv/bin/activate
    python3 ~/claw-src/scripts/test_kimi_bridge.py
"""

import asyncio
import json
import os
import sys
import uuid

import websockets

BRIDGE_URL = "wss://www.kimi.com/api-claw/bots/agent-ws"
PING_INTERVAL = 15


class KimiBridgeClient:
    """Full ACP protocol client for talking to Kimi K2 via the bridge."""

    def __init__(self, ws):
        self.ws = ws
        self.request_seq = 0
        self.session_id = None
        self.responses = {}  # request_id → asyncio.Event + data
        self.session_updates = []  # collected session updates
        self._listener_task = None

    def next_request_id(self):
        self.request_seq += 1
        return f"req_{self.request_seq}"

    async def send(self, data: dict):
        """Send a JSON-RPC message."""
        raw = json.dumps(data, ensure_ascii=False)
        await self.ws.send(raw)
        display = json.dumps(data, indent=2, ensure_ascii=False)
        if len(display) > 1000:
            display = display[:1000] + "\n... (truncated)"
        print(f"\n>> SEND:\n{display}")

    async def send_rpc(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self.next_request_id()
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        # Create a future for this request
        future = asyncio.get_event_loop().create_future()
        self.responses[req_id] = future

        await self.send(msg)

        # Wait for response (30s timeout)
        try:
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except TimeoutError:
            del self.responses[req_id]
            print(f"[TIMEOUT] No response for {method} (id={req_id})")
            return {"error": "timeout"}

    async def send_prompt_and_stream(self, session_id: str, text: str, timeout: float = 60) -> list:
        """Send session/prompt and collect all streaming updates until result."""
        req_id = self.next_request_id()
        self.session_updates = []

        future = asyncio.get_event_loop().create_future()
        self.responses[req_id] = future

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {"sessionId": session_id, "prompt": {"content": [{"type": "text", "text": text}]}},
        }
        await self.send(msg)

        # Wait for the final result
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return {"result": result, "updates": list(self.session_updates)}
        except TimeoutError:
            del self.responses[req_id]
            return {"error": "timeout", "updates": list(self.session_updates)}

    def handle_message(self, data: dict):
        """Handle an incoming message — route to response futures or collect updates."""
        # JSON-RPC response (has "id")
        if "id" in data and ("result" in data or "error" in data):
            req_id = data["id"]
            if req_id in self.responses:
                future = self.responses.pop(req_id)
                if not future.done():
                    future.set_result(data)
            return

        # JSON-RPC notification (no "id")
        method = data.get("method")
        if method == "session/update":
            params = data.get("params", {})
            update = params.get("update", {})
            update_type = update.get("sessionUpdate", "unknown")

            # Collect the update
            self.session_updates.append(update)

            # Display based on type
            if update_type == "agent_message_chunk":
                content = update.get("content", {})
                text = content.get("text", "")
                if text:
                    print(f"[K2] {text}", end="", flush=True)
            elif update_type == "agent_thought_chunk":
                content = update.get("content", {})
                text = content.get("text", "")
                if text:
                    print(f"[K2 thinking] {text}", end="", flush=True)
            elif update_type == "tool_call":
                title = update.get("title", "tool")
                print(f"\n[K2 tool call] {title}")
            elif update_type == "tool_call_update":
                title = update.get("title", "tool")
                print(f"\n[K2 tool result] {title}")
            elif update_type == "user_message_chunk":
                pass  # Echo, skip
            else:
                print(f"\n[update] {update_type}: {json.dumps(update, ensure_ascii=False)[:200]}")
            return

        # Other notifications
        if method == "_kimi.com/reconnect":
            print("\n[bridge] reconnect notification")
            return

        # Unknown
        print(f"\n[unknown] {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")

    # --- Also handle INCOMING requests from Kimi (Kimi asks US to do things) ---

    async def handle_incoming_request(self, data: dict):
        """Handle a request from Kimi (Kimi initiating contact with us)."""
        method = data.get("method")
        req_id = data.get("id")
        params = data.get("params")

        print(f"\n[INCOMING REQUEST] method={method} id={req_id}")

        if method == "initialize":
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": 1,
                        "agentCapabilities": {
                            "loadSession": True,
                            "promptCapabilities": {"embeddedContext": True, "image": True, "audio": False},
                            "sessionCapabilities": {"list": {}, "web-ssh": False},
                        },
                        "agentInfo": {"name": "corvus-gateway", "version": "0.1.0"},
                    },
                }
            )
        elif method == "session/new":
            session_id = "agent:main:main"
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "sessionId": session_id,
                        "modes": {
                            "availableModes": [
                                {"id": "default", "name": "Default", "description": "Default agent mode"}
                            ],
                            "currentModeId": "default",
                        },
                    },
                }
            )
        elif method == "session/load":
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": None,
                }
            )
        elif method == "session/list":
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"sessions": [], "nextCursor": None},
                }
            )
        elif method == "session/prompt":
            # Kimi user sent us a message! Extract and respond.
            prompt = params.get("prompt", {}) if isinstance(params, dict) else {}
            user_text = extract_prompt_text(prompt)
            print(f"\n{'=' * 60}")
            print(f"[KIMI USER MESSAGE]: {user_text[:500]}")
            print(f"{'=' * 60}")

            session_id = "agent:main:main"

            # Echo user message
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "user_message_chunk",
                            "content": {"type": "text", "text": user_text},
                        },
                        "_meta": {"_debug_index": 100, "messageType": "normal", "requestId": req_id},
                    },
                }
            )

            # Send response
            response_text = f'Hello from Claw Gateway! You said: "{user_text[:200]}"'
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": response_text},
                        },
                        "_meta": {"_debug_index": 101, "messageType": "normal", "requestId": req_id},
                    },
                }
            )

            # Complete
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"stopReason": "end_turn"},
                }
            )
            print(">>> Responded to Kimi user")

        elif method == "session/cancel":
            if req_id is not None:
                await self.send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "session/set_model":
            if req_id is not None:
                await self.send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        else:
            print(f"[INCOMING] Unknown method: {method}")
            if req_id is not None:
                await self.send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"method not found: {method}"},
                    }
                )


def extract_prompt_text(prompt) -> str:
    """Extract text from various prompt formats."""
    if isinstance(prompt, str):
        return prompt

    if isinstance(prompt, dict):
        # Direct text
        if "text" in prompt:
            return prompt["text"]

        # Content blocks
        content = prompt.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)

        # Messages array
        messages = prompt.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                c = last.get("content", "")
                if isinstance(c, str):
                    return c

    return "(empty prompt)"


async def main():
    bot_token = os.environ.get("KIMI_BOT_TOKEN", "")
    if not bot_token:
        print("ERROR: KIMI_BOT_TOKEN not set")
        sys.exit(1)

    print(f"Bridge URL: {BRIDGE_URL}")
    print(f"Bot token: present (len={len(bot_token)})")

    headers = {
        "X-Kimi-Claw-Version": "0.7.4",
        "X-Kimi-Bot-Token": bot_token,
    }

    async def keepalive(ws):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.send(json.dumps({"type": "ping"}))
            except Exception:
                break

    print("\nConnecting (ACP mode)...")
    try:
        async with websockets.connect(
            BRIDGE_URL,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            print("CONNECTED!\n")

            client = KimiBridgeClient(ws)
            ping_task = asyncio.create_task(keepalive(ws))

            # Start background listener
            async def listener():
                try:
                    while True:
                        msg = await ws.recv()

                        # Text heartbeats
                        if isinstance(msg, str):
                            stripped = msg.strip().lower()
                            if stripped == "ping":
                                await ws.send("pong")
                                continue
                            if stripped == "pong":
                                continue

                        # Parse JSON
                        try:
                            data = json.loads(msg) if isinstance(msg, str) else json.loads(msg.decode())
                        except json.JSONDecodeError:
                            continue

                        # JSON pings
                        if data.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                            continue

                        # Check if this is a request from Kimi (has method + id, no result/error)
                        if "method" in data and "id" in data and "result" not in data and "error" not in data:
                            await client.handle_incoming_request(data)
                        else:
                            client.handle_message(data)

                except websockets.exceptions.ConnectionClosed:
                    pass

            listener_task = asyncio.create_task(listener())

            # --- DRIVE THE PROTOCOL ---

            # Step 1: Initialize
            print("=" * 60)
            print("Step 1: initialize")
            print("=" * 60)
            resp = await client.send_rpc("initialize", {"protocolVersion": 1})
            if "result" in resp:
                print(f"<< Capabilities: {json.dumps(resp['result'], indent=2, ensure_ascii=False)[:500]}")
            elif "error" in resp:
                print(f"<< Error: {resp['error']}")

            # Step 2: Create session
            print("\n" + "=" * 60)
            print("Step 2: session/new")
            print("=" * 60)
            resp = await client.send_rpc(
                "session/new", {"cwd": ".", "_meta": {"sessionId": f"claw-test-{uuid.uuid4().hex[:8]}"}}
            )
            if "result" in resp:
                result = resp.get("result", {})
                session_id = result.get("sessionId", "unknown")
                client.session_id = session_id
                print(f"<< Session created: {session_id}")
                print(f"<< Full response: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
            elif "error" in resp:
                print(f"<< Error: {resp['error']}")
                session_id = None

            # Step 3: Send a prompt
            if session_id:
                print("\n" + "=" * 60)
                print("Step 3: session/prompt — sending message to K2")
                print("=" * 60)
                result = await client.send_prompt_and_stream(
                    session_id,
                    "Hello! What model are you? Reply in one short sentence.",
                    timeout=60,
                )
                print()  # newline after streaming
                if "error" in result and result["error"] != "timeout":
                    print(f"<< Error: {result['error']}")
                else:
                    updates = result.get("updates", [])
                    print(f"\n<< Received {len(updates)} session updates")
                    final = result.get("result", {})
                    if "result" in final:
                        print(f"<< Stop reason: {final['result'].get('stopReason', 'unknown')}")

            # Step 4: Listen for more (including Kimi users sending us messages)
            print("\n" + "=" * 60)
            print("Step 4: Listening for incoming messages (2 min)...")
            print("  Send a message from the Kimi app to test bidirectional flow.")
            print("=" * 60)

            try:
                await asyncio.wait_for(listener_task, timeout=120)
            except TimeoutError:
                print("\n(listen timeout)")

            ping_task.cancel()
            listener_task.cancel()

    except websockets.exceptions.InvalidStatus as e:
        print(f"HTTP {e.response.status_code} — Connection failed")
        body = getattr(e.response, "body", None)
        if body:
            print(f"Response: {body.decode('utf-8', errors='replace')}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
