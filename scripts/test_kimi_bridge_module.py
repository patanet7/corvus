"""Test: KimiBridgeClient module -- full ACP lifecycle.

Connects to the Kimi bridge using the production module and drives both roles:

  CLIENT MODE (model inference):
    1. Connect (X-Kimi-Bot-Token via env var)
    2. Initialize -- exchange capabilities
    3. Create session -- get session ID
    4. Send prompt (streaming) -- stream K2's response
    5. Send prompt (blocking) -- collect full response

  SERVER MODE (incoming Kimi users):
    6. Listen for incoming messages from the Kimi app

Run ON LAPTOP-SERVER:
    set -a && source ~/.secrets/claw.env && set +a
    source ~/claw-src/.venv/bin/activate
    python3 ~/claw-src/scripts/test_kimi_bridge_module.py

Requires: KIMI_BOT_TOKEN environment variable.
"""

import asyncio
import json
import logging
import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from corvus.kimi_bridge import (
    AcpCapabilities,
    AcpErrorCode,
    AgentInfo,
    KimiBridgeClient,
    PromptBlock,
    PromptResponse,
    PromptResult,
    SessionInfo,
    SessionMode,
    SessionUpdate,
    SessionUpdateType,
    StopReason,
    build_error,
    build_meta,
    build_result,
    build_session_update,
    extract_prompt_text,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test-kimi-bridge")


# ---------------------------------------------------------------------------
# Offline unit-style tests (no network needed)
# ---------------------------------------------------------------------------


def test_extract_prompt_text() -> None:
    """Test extract_prompt_text with various input formats."""
    print("\n--- test_extract_prompt_text ---")
    errors = []

    # Plain string
    result = extract_prompt_text("hello")
    if result != "hello":
        errors.append(f"Plain string: expected 'hello', got '{result}'")

    # Dict with text
    result = extract_prompt_text({"text": "world"})
    if result != "world":
        errors.append(f"Dict text: expected 'world', got '{result}'")

    # Dict with content string
    result = extract_prompt_text({"content": "direct"})
    if result != "direct":
        errors.append(f"Content string: expected 'direct', got '{result}'")

    # Dict with content blocks
    result = extract_prompt_text(
        {
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "image", "data": "..."},
                {"type": "text", "text": "line2"},
            ]
        }
    )
    if result != "line1\nline2":
        errors.append(f"Content blocks: expected 'line1\\nline2', got '{result}'")

    # Dict with messages
    result = extract_prompt_text(
        {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "user", "content": "last"},
            ]
        }
    )
    if result != "last":
        errors.append(f"Messages: expected 'last', got '{result}'")

    # Empty/invalid
    result = extract_prompt_text({})
    if result != "(empty prompt)":
        errors.append(f"Empty dict: expected '(empty prompt)', got '{result}'")

    result = extract_prompt_text(42)
    if result != "(empty prompt)":
        errors.append(f"Int: expected '(empty prompt)', got '{result}'")

    result = extract_prompt_text(None)
    if result != "(empty prompt)":
        errors.append(f"None: expected '(empty prompt)', got '{result}'")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"  {len(errors)} failures")
    else:
        print("  PASS: all assertions passed")
    return len(errors) == 0


def test_data_models() -> None:
    """Test data model serialization/deserialization round-trips."""
    print("\n--- test_data_models ---")
    errors = []

    # AcpCapabilities
    caps = AcpCapabilities()
    caps_dict = caps.to_dict()
    if caps_dict["loadSession"] is not True:
        errors.append(f"caps loadSession: {caps_dict['loadSession']}")
    if caps_dict["promptCapabilities"]["image"] is not True:
        errors.append("caps prompt image should be True")
    if caps_dict["sessionCapabilities"]["web-ssh"] is not False:
        errors.append("caps web-ssh should be False")

    caps2 = AcpCapabilities.from_dict(caps_dict)
    if caps2.load_session != caps.load_session:
        errors.append("Round-trip caps.load_session mismatch")
    if caps2.prompt_capabilities.image != caps.prompt_capabilities.image:
        errors.append("Round-trip caps.prompt.image mismatch")

    # AgentInfo
    info = AgentInfo(name="test", version="1.0.0")
    info_dict = info.to_dict()
    if info_dict != {"name": "test", "version": "1.0.0"}:
        errors.append(f"AgentInfo to_dict: {info_dict}")
    info2 = AgentInfo.from_dict(info_dict)
    if info2.name != "test" or info2.version != "1.0.0":
        errors.append("AgentInfo round-trip failed")

    # SessionInfo
    session = SessionInfo(
        session_id="agent:main:main",
        available_modes=[SessionMode(id="default", name="Default", description="Test")],
        current_mode_id="default",
    )
    s_dict = session.to_dict()
    if s_dict["sessionId"] != "agent:main:main":
        errors.append(f"SessionInfo sessionId: {s_dict['sessionId']}")
    s2 = SessionInfo.from_dict(s_dict)
    if s2.session_id != "agent:main:main":
        errors.append("SessionInfo round-trip sessionId failed")
    if len(s2.available_modes) != 1:
        errors.append(f"SessionInfo modes count: {len(s2.available_modes)}")

    # PromptBlock
    block = PromptBlock(type="text", text="hello")
    b_dict = block.to_dict()
    if b_dict != {"type": "text", "text": "hello"}:
        errors.append(f"PromptBlock text to_dict: {b_dict}")
    b2 = PromptBlock.from_dict(b_dict)
    if b2.text != "hello":
        errors.append("PromptBlock round-trip text failed")

    # Image block
    img = PromptBlock(type="image", source="base64data", media_type="image/png")
    i_dict = img.to_dict()
    if i_dict.get("source") != "base64data":
        errors.append(f"Image block source: {i_dict}")

    # SessionUpdate
    params = {
        "sessionId": "agent:main:main",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Hello"},
        },
        "_meta": {"_debug_index": 1, "requestId": "req_1"},
    }
    update = SessionUpdate.from_params(params)
    if update.session_id != "agent:main:main":
        errors.append(f"SessionUpdate session_id: {update.session_id}")
    if update.update_type != "agent_message_chunk":
        errors.append(f"SessionUpdate type: {update.update_type}")
    if update.text != "Hello":
        errors.append(f"SessionUpdate text: {update.text}")

    # Tool call update
    tool_params = {
        "sessionId": "agent:main:main",
        "update": {
            "sessionUpdate": "tool_call",
            "toolCallId": "tc_1",
            "title": "Bash",
            "status": "in_progress",
            "content": [{"type": "content", "content": {"type": "text", "text": '{"command": "ls"}'}}],
        },
        "_meta": {"_debug_index": 2, "requestId": "req_1"},
    }
    tool_update = SessionUpdate.from_params(tool_params)
    if tool_update.tool_call_id != "tc_1":
        errors.append(f"Tool update call_id: {tool_update.tool_call_id}")
    if tool_update.title != "Bash":
        errors.append(f"Tool update title: {tool_update.title}")
    if tool_update.status != "in_progress":
        errors.append(f"Tool update status: {tool_update.status}")

    # PromptResult
    pr = PromptResult.from_result({"stopReason": "end_turn", "_meta": {"requestId": "req_1"}})
    if pr.stop_reason != "end_turn":
        errors.append(f"PromptResult stop_reason: {pr.stop_reason}")

    pr2 = PromptResult.from_result({"stopReason": "cancelled"})
    if pr2.stop_reason != "cancelled":
        errors.append(f"PromptResult cancelled: {pr2.stop_reason}")

    # PromptResponse
    response = PromptResponse(
        updates=[
            SessionUpdate(
                session_id="s",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK,
                content={"type": "text", "text": "Hello "},
            ),
            SessionUpdate(
                session_id="s",
                update_type=SessionUpdateType.AGENT_THOUGHT_CHUNK,
                content={"type": "text", "text": "thinking..."},
            ),
            SessionUpdate(
                session_id="s",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK,
                content={"type": "text", "text": "world"},
            ),
            SessionUpdate(
                session_id="s", update_type=SessionUpdateType.TOOL_CALL, content=[], tool_call_id="tc_1", title="Bash"
            ),
            SessionUpdate(
                session_id="s",
                update_type=SessionUpdateType.TOOL_CALL_UPDATE,
                content=[],
                tool_call_id="tc_1",
                title="Bash",
            ),
        ],
        result=PromptResult(stop_reason="end_turn"),
    )
    if response.full_text != "Hello world":
        errors.append(f"PromptResponse full_text: '{response.full_text}'")
    if response.thought_text != "thinking...":
        errors.append(f"PromptResponse thought_text: '{response.thought_text}'")
    if len(response.tool_calls) != 1:
        errors.append(f"PromptResponse tool_calls count: {len(response.tool_calls)}")
    if len(response.tool_results) != 1:
        errors.append(f"PromptResponse tool_results count: {len(response.tool_results)}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"  {len(errors)} failures")
    else:
        print("  PASS: all assertions passed")
    return len(errors) == 0


def test_message_builders() -> None:
    """Test the build_* helper functions produce valid JSON-RPC messages."""
    print("\n--- test_message_builders ---")
    errors = []

    # build_meta
    meta = build_meta(debug_index=1, request_id="req_42")
    if meta["_debug_index"] != 1:
        errors.append(f"meta debug_index: {meta['_debug_index']}")
    if meta["requestId"] != "req_42":
        errors.append(f"meta requestId: {meta['requestId']}")
    if meta["messageType"] != "normal":
        errors.append(f"meta messageType: {meta['messageType']}")
    if "timestamp" not in meta:
        errors.append("meta missing timestamp")
    if "sessionId" in meta:
        errors.append("meta should not have sessionId when not provided")

    # build_meta with session_id
    meta_s = build_meta(debug_index=2, request_id="req_1", session_id="agent:main:main")
    if meta_s.get("sessionId") != "agent:main:main":
        errors.append(f"meta with sessionId: {meta_s}")

    # build_session_update -- text
    msg = build_session_update(
        session_id="agent:main:main",
        update_type="agent_message_chunk",
        content={"type": "text", "text": "hello"},
        request_id="req_1",
        meta_index=5,
    )
    if msg["jsonrpc"] != "2.0":
        errors.append("update jsonrpc wrong")
    if msg["method"] != "session/update":
        errors.append(f"update method: {msg['method']}")
    if msg["params"]["sessionId"] != "agent:main:main":
        errors.append("update sessionId wrong")
    if msg["params"]["update"]["sessionUpdate"] != "agent_message_chunk":
        errors.append("update type wrong")
    if msg["params"]["update"]["content"]["text"] != "hello":
        errors.append("update content text wrong")
    if "toolCallId" in msg["params"]["update"]:
        errors.append("text update should not have toolCallId")

    # build_session_update -- tool_call
    tool_msg = build_session_update(
        session_id="agent:main:main",
        update_type="tool_call",
        content=[{"type": "content", "content": {"type": "text", "text": "ls"}}],
        request_id="req_1",
        meta_index=6,
        tool_call_id="tc_1",
        title="Bash",
        status="in_progress",
    )
    if tool_msg["params"]["update"]["toolCallId"] != "tc_1":
        errors.append("tool_call missing toolCallId")
    if tool_msg["params"]["update"]["title"] != "Bash":
        errors.append("tool_call missing title")
    if tool_msg["params"]["update"]["status"] != "in_progress":
        errors.append("tool_call missing status")

    # build_result -- with dict result
    result_msg = build_result("req_1", {"stopReason": "end_turn"}, meta_index=7)
    if result_msg["id"] != "req_1":
        errors.append(f"result id: {result_msg['id']}")
    if result_msg["result"]["stopReason"] != "end_turn":
        errors.append("result stopReason wrong")
    if "_meta" not in result_msg["result"]:
        errors.append("result missing _meta")

    # build_result -- with None result (session/load)
    null_msg = build_result("req_2", None, meta_index=8)
    if null_msg["id"] != "req_2":
        errors.append(f"null result id: {null_msg['id']}")
    # Should be empty dict (normalized from None) with _meta injected
    if not isinstance(null_msg["result"], dict):
        errors.append(f"null result type: {type(null_msg['result'])}")
    if "_meta" not in null_msg["result"]:
        errors.append("null result missing _meta")

    # build_result -- with session_id in _meta
    session_msg = build_result(
        "req_3",
        {"stopReason": "end_turn"},
        session_id="agent:main:main",
        meta_index=9,
    )
    if session_msg["result"]["_meta"].get("sessionId") != "agent:main:main":
        errors.append("result _meta missing sessionId")

    # build_error
    err_msg = build_error("req_1", -32001, "gateway unavailable", meta_index=10)
    if err_msg["id"] != "req_1":
        errors.append(f"error id: {err_msg['id']}")
    if err_msg["error"]["code"] != -32001:
        errors.append(f"error code: {err_msg['error']['code']}")
    if err_msg["error"]["message"] != "gateway unavailable":
        errors.append("error message wrong")
    if "data" not in err_msg["error"]:
        errors.append("error missing data envelope for _meta")
    if "_meta" not in err_msg["error"]["data"]:
        errors.append("error data missing _meta")

    # build_error without meta
    err_no_meta = build_error("req_2", -32601, "not found")
    if "data" in err_no_meta["error"]:
        errors.append("error without meta_index should not have data")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"  {len(errors)} failures")
    else:
        print("  PASS: all assertions passed")
    return len(errors) == 0


def test_enum_values() -> None:
    """Test enum values match the protocol spec."""
    print("\n--- test_enum_values ---")
    errors = []

    # AcpErrorCode
    if AcpErrorCode.GATEWAY_UNAVAILABLE != -32001:
        errors.append(f"GATEWAY_UNAVAILABLE: {AcpErrorCode.GATEWAY_UNAVAILABLE}")
    if AcpErrorCode.GATEWAY_ERROR != -32020:
        errors.append(f"GATEWAY_ERROR: {AcpErrorCode.GATEWAY_ERROR}")
    if AcpErrorCode.LIFECYCLE_ERROR != -32021:
        errors.append(f"LIFECYCLE_ERROR: {AcpErrorCode.LIFECYCLE_ERROR}")
    if AcpErrorCode.PROMPT_TIMEOUT != -32022:
        errors.append(f"PROMPT_TIMEOUT: {AcpErrorCode.PROMPT_TIMEOUT}")
    if AcpErrorCode.METHOD_NOT_FOUND != -32601:
        errors.append(f"METHOD_NOT_FOUND: {AcpErrorCode.METHOD_NOT_FOUND}")
    if AcpErrorCode.INVALID_PARAMS != -32602:
        errors.append(f"INVALID_PARAMS: {AcpErrorCode.INVALID_PARAMS}")

    # StopReason
    if StopReason.END_TURN != "end_turn":
        errors.append(f"END_TURN: {StopReason.END_TURN}")
    if StopReason.CANCELLED != "cancelled":
        errors.append(f"CANCELLED: {StopReason.CANCELLED}")

    # SessionUpdateType
    if SessionUpdateType.USER_MESSAGE_CHUNK != "user_message_chunk":
        errors.append(f"USER_MESSAGE_CHUNK: {SessionUpdateType.USER_MESSAGE_CHUNK}")
    if SessionUpdateType.AGENT_MESSAGE_CHUNK != "agent_message_chunk":
        errors.append(f"AGENT_MESSAGE_CHUNK: {SessionUpdateType.AGENT_MESSAGE_CHUNK}")
    if SessionUpdateType.AGENT_THOUGHT_CHUNK != "agent_thought_chunk":
        errors.append(f"AGENT_THOUGHT_CHUNK: {SessionUpdateType.AGENT_THOUGHT_CHUNK}")
    if SessionUpdateType.TOOL_CALL != "tool_call":
        errors.append(f"TOOL_CALL: {SessionUpdateType.TOOL_CALL}")
    if SessionUpdateType.TOOL_CALL_UPDATE != "tool_call_update":
        errors.append(f"TOOL_CALL_UPDATE: {SessionUpdateType.TOOL_CALL_UPDATE}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"  {len(errors)} failures")
    else:
        print("  PASS: all assertions passed")
    return len(errors) == 0


def test_client_construction() -> None:
    """Test KimiBridgeClient construction with various parameters."""
    print("\n--- test_client_construction ---")
    errors = []

    # Default construction
    client = KimiBridgeClient(bot_token="test-token-123")
    if client.bot_token != "test-token-123":
        errors.append(f"bot_token: {client.bot_token}")
    if client.bridge_url != "wss://www.kimi.com/api-claw/bots/agent-ws":
        errors.append(f"bridge_url: {client.bridge_url}")
    if client.agent_info.name != "corvus-gateway":
        errors.append(f"agent name: {client.agent_info.name}")
    if client.agent_info.version != "0.1.0":
        errors.append(f"agent version: {client.agent_info.version}")
    if client.auto_reconnect is not True:
        errors.append(f"auto_reconnect: {client.auto_reconnect}")
    if client.connected:
        errors.append("Should not be connected on construction")
    if client.auth_failed:
        errors.append("auth_failed should be False on construction")

    # Custom construction
    caps = AcpCapabilities(load_session=False)
    client2 = KimiBridgeClient(
        bot_token="token2",
        bridge_url="wss://custom.example.com/ws",
        agent_name="my-agent",
        agent_version="2.0.0",
        capabilities=caps,
        auto_reconnect=False,
    )
    if client2.bridge_url != "wss://custom.example.com/ws":
        errors.append(f"custom bridge_url: {client2.bridge_url}")
    if client2.agent_info.name != "my-agent":
        errors.append(f"custom agent name: {client2.agent_info.name}")
    if client2.capabilities.load_session is not False:
        errors.append("Custom caps load_session should be False")
    if client2.auto_reconnect is not False:
        errors.append("auto_reconnect should be False")

    # Request ID generation
    id1 = client._next_request_id()
    id2 = client._next_request_id()
    if id1 == id2:
        errors.append("Request IDs should be unique")
    if not id1.startswith("req_"):
        errors.append(f"Request ID format: {id1}")

    # Meta index generation
    idx1 = client._next_meta_index()
    idx2 = client._next_meta_index()
    if idx2 != idx1 + 1:
        errors.append(f"Meta index not sequential: {idx1}, {idx2}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"  {len(errors)} failures")
    else:
        print("  PASS: all assertions passed")
    return len(errors) == 0


# ---------------------------------------------------------------------------
# Server-side handler for incoming Kimi user messages
# ---------------------------------------------------------------------------


async def handle_incoming_prompt(
    request_id: str,
    params: dict,
    bridge: KimiBridgeClient,
) -> None:
    """Handle a message sent by a Kimi user through the bridge.

    This is the server-side callback: Kimi user types something in the Kimi app,
    the bridge forwards it to us as a session/prompt request.
    """
    prompt = params.get("prompt", {}) if isinstance(params, dict) else {}
    user_text = extract_prompt_text(prompt)
    session_id = params.get("sessionId", "agent:main:main") if isinstance(params, dict) else "agent:main:main"

    print()
    print("=" * 60)
    print(f"INCOMING KIMI USER MESSAGE: {user_text[:500]}")
    print("=" * 60)

    # Echo user message back
    await bridge.send_session_update(
        session_id=session_id,
        update_type=SessionUpdateType.USER_MESSAGE_CHUNK,
        content={"type": "text", "text": user_text},
        request_id=request_id,
    )

    # Send a response
    response_text = (
        f"Hello from Claw Gateway (KimiBridgeClient module test)! "
        f'You said: "{user_text[:200]}"\n\n'
        f"This message confirms bidirectional communication is working."
    )
    await bridge.send_agent_message(
        session_id=session_id,
        text=response_text,
        request_id=request_id,
    )

    # Complete the request
    await bridge.send_result(
        request_id,
        {"stopReason": "end_turn"},
        session_id=session_id,
    )
    print(">>> Responded to Kimi user successfully")


# ---------------------------------------------------------------------------
# Online tests (require KIMI_BOT_TOKEN and network access)
# ---------------------------------------------------------------------------


async def run_online_tests(bot_token: str) -> bool:
    """Run the full online test suite against the live Kimi bridge."""
    all_passed = True

    print(f"Bot token: present (length={len(bot_token)})")
    print()

    # Create the bridge client with our server-side handler
    bridge = KimiBridgeClient(
        bot_token=bot_token,
        auto_reconnect=True,
        on_session_prompt=handle_incoming_prompt,
    )

    try:
        async with bridge:
            # Step 1: Initialize
            print("=" * 60)
            print("Step 1: initialize")
            print("=" * 60)
            try:
                caps = await bridge.initialize()
                print(f"Server capabilities: {json.dumps(caps, indent=2, ensure_ascii=False)[:500]}")
            except Exception as e:
                print(f"Initialize failed: {e}")
                # Non-fatal: some bridge configs skip initialize

            # Step 2: Create session
            print()
            print("=" * 60)
            print("Step 2: session/new")
            print("=" * 60)
            try:
                session = await bridge.create_session()
                print(f"Session created: {session.session_id}")
                print(f"Available modes: {[m.name for m in session.available_modes]}")
            except Exception as e:
                print(f"session/new failed: {e}")
                print("Using fallback session ID: agent:main:main")
                session = None

            session_id = session.session_id if session else "agent:main:main"

            # Step 3: Send a prompt and stream the response (model inference)
            print()
            print("=" * 60)
            print("Step 3: session/prompt -- send message to K2 (streaming)")
            print("=" * 60)
            print()
            print("Streaming K2 response:")
            print("-" * 40)

            try:
                chunk_count = 0
                tool_count = 0
                thought_count = 0
                async for item in bridge.send_prompt_stream(
                    session_id=session_id,
                    text="Hello! What model are you? Reply in one short sentence.",
                    timeout=60,
                ):
                    if isinstance(item, SessionUpdate):
                        if item.update_type == SessionUpdateType.AGENT_MESSAGE_CHUNK:
                            print(item.text, end="", flush=True)
                            chunk_count += 1
                        elif item.update_type == SessionUpdateType.AGENT_THOUGHT_CHUNK:
                            print(f"[thinking] {item.text}", end="", flush=True)
                            thought_count += 1
                        elif item.update_type == SessionUpdateType.TOOL_CALL:
                            print(f"\n[tool call] {item.title} (id={item.tool_call_id})")
                            tool_count += 1
                        elif item.update_type == SessionUpdateType.TOOL_CALL_UPDATE:
                            print(f"\n[tool result] {item.title} (status={item.status})")
                        elif item.update_type == SessionUpdateType.USER_MESSAGE_CHUNK:
                            pass  # Echo of our own message
                        else:
                            print(f"\n[{item.update_type}]", end="")
                    elif isinstance(item, PromptResult):
                        print()
                        print("-" * 40)
                        print(f"Stop reason: {item.stop_reason}")
                        print(
                            f"Received: {chunk_count} message chunks, "
                            f"{thought_count} thought chunks, "
                            f"{tool_count} tool calls"
                        )

                print()
            except TimeoutError:
                print("\n(prompt timed out)")
                all_passed = False
            except Exception as e:
                print(f"\nPrompt error: {e}")
                all_passed = False

            # Step 4: Non-streaming send_prompt
            print()
            print("=" * 60)
            print("Step 4: session/prompt (non-streaming) -- second test")
            print("=" * 60)

            try:
                response = await bridge.send_prompt(
                    session_id=session_id,
                    text="What is 2 + 2? Reply with just the number.",
                    timeout=30,
                )
                if response.error:
                    print(f"Error: {response.error}")
                    all_passed = False
                else:
                    print(f"Full text: {response.full_text}")
                    if response.thought_text:
                        print(f"Thought: {response.thought_text[:200]}")
                    print(f"Stop reason: {response.result.stop_reason if response.result else 'N/A'}")
                    print(f"Updates received: {len(response.updates)}")
                    print(f"Tool calls: {len(response.tool_calls)}")
                    print(f"Tool results: {len(response.tool_results)}")
            except TimeoutError:
                print("(prompt timed out)")
                all_passed = False
            except Exception as e:
                print(f"Error: {e}")
                all_passed = False

            # Step 5: Listen for incoming messages from Kimi users
            print()
            print("=" * 60)
            print("Step 5: Listening for incoming Kimi user messages (2 min)...")
            print("  Open the Kimi app and send a message to test bidirectional flow.")
            print("=" * 60)

            try:
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                pass

            print()
            print("Listen period ended.")

    except ConnectionError as e:
        print(f"Connection error: {e}")
        all_passed = False
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        all_passed = False

    return all_passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("KimiBridgeClient Module Test Suite")
    print("=" * 60)
    print()

    # --- Offline tests (always run) ---
    print("PHASE 1: Offline tests (no network)")
    print("-" * 40)

    offline_results = {
        "extract_prompt_text": test_extract_prompt_text(),
        "data_models": test_data_models(),
        "message_builders": test_message_builders(),
        "enum_values": test_enum_values(),
        "client_construction": test_client_construction(),
    }

    print()
    offline_passed = all(offline_results.values())
    offline_count = sum(1 for v in offline_results.values() if v)
    print(f"Offline: {offline_count}/{len(offline_results)} passed")
    for name, passed in offline_results.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")

    # --- Online tests (require KIMI_BOT_TOKEN) ---
    print()
    print("PHASE 2: Online tests (live Kimi bridge)")
    print("-" * 40)

    bot_token = os.environ.get("KIMI_BOT_TOKEN", "")
    if not bot_token:
        print("KIMI_BOT_TOKEN not set -- skipping online tests.")
        print("To run online tests:")
        print("  export KIMI_BOT_TOKEN='your-token-here'")
        print()
    else:
        online_passed = await run_online_tests(bot_token)
        print()
        print(f"Online: {'PASSED' if online_passed else 'FAILED'}")

    # --- Summary ---
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if offline_passed:
        print("All offline tests PASSED.")
    else:
        print("Some offline tests FAILED.")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
