"""ACP execution path — execute_acp_run for ACP-backed agent runs.

Called by run_executor.py when backend_name == "acp". Uses CorvusACPClient
to spawn the ACP agent, manage the session, and stream events through
Corvus's existing SessionEmitter pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from corvus.acp.client import ACPClientConfig, CorvusACPClient
from corvus.acp.events import translate_acp_update
from corvus.acp.sandbox import build_acp_env
from corvus.acp.session import AcpSessionTracker
from corvus.gateway.workspace_runtime import prepare_agent_workspace
from corvus.sanitize import sanitize

if TYPE_CHECKING:
    from corvus.acp.registry import AcpAgentRegistry
    from corvus.gateway.chat_session import TurnContext
    from corvus.gateway.confirm_queue import ConfirmQueue
    from corvus.gateway.runtime import GatewayRuntime
    from corvus.gateway.session_emitter import SessionEmitter
    from corvus.gateway.task_planner import TaskRoute
    from corvus.session import SessionTranscript

logger = logging.getLogger("corvus-gateway")

# Module-level session tracker (shared across runs)
_acp_session_tracker = AcpSessionTracker()


def _preview_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "\u2026"


def _route_payload(route: TaskRoute, *, route_index: int) -> dict:
    return {
        "task_type": route.task_type,
        "subtask_id": route.subtask_id,
        "skill": route.skill,
        "instruction": route.instruction,
        "route_index": route_index,
    }


async def execute_acp_run(
    *,
    emitter: SessionEmitter,
    runtime: GatewayRuntime,
    turn: TurnContext,
    route: TaskRoute,
    route_index: int,
    transcript: SessionTranscript,
    user: str,
    confirm_queue: ConfirmQueue | None,
    acp_registry: AcpAgentRegistry,
) -> dict[str, Any]:
    """Execute a single ACP agent run.

    Mirrors the structure of execute_agent_run() in run_executor.py
    but uses CorvusACPClient instead of ClaudeSDKClient.
    """
    session_id = emitter.session_id
    send = emitter.send
    emit_phase = emitter.emit_phase
    emit_run_failure = emitter.emit_run_failure
    emit_run_interrupted = emitter.emit_run_interrupted
    base_payload_fn = emitter.base_payload

    agent_name = route.agent
    run_id = str(uuid.uuid4())
    task_id = f"task-{run_id[:8]}"
    transcript.record_agent(agent_name)
    route_pay = _route_payload(route, route_index=route_index)
    run_message = route.prompt

    # Determine ACP agent from metadata
    agent_spec = runtime.agents_hub.get(agent_name)
    acp_agent_name = (agent_spec.metadata or {}).get("acp_agent") if agent_spec else None
    if not acp_agent_name:
        return await emit_run_failure(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            error_type="acp_config_missing",
            summary="Agent spec missing metadata.acp_agent",
            context_limit=0,
        )

    acp_entry = acp_registry.get(acp_agent_name)
    if acp_entry is None:
        return await emit_run_failure(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            error_type="acp_agent_unknown",
            summary=f"ACP agent '{acp_agent_name}' not found in config/acp_agents.yaml",
            context_limit=0,
        )

    workspace_cwd = prepare_agent_workspace(session_id=session_id, agent_name=agent_name)
    active_model_id = f"acp/{acp_agent_name}"

    # Determine parent policy from agent spec
    parent_allows_read = True
    parent_allows_write = True
    parent_allows_bash = True

    chunk_index = 0
    response_parts: list[str] = []
    assistant_summary = ""
    total_cost = 0.0
    tokens_used = 0

    # Persist run row
    try:
        runtime.session_mgr.start_agent_run(
            run_id,
            dispatch_id=turn.dispatch_id,
            session_id=session_id,
            turn_id=turn.turn_id,
            agent=agent_name,
            backend="acp",
            model=active_model_id,
            task_type=route.task_type,
            subtask_id=route.subtask_id,
            skill=route.skill,
            status="queued",
        )
    except Exception:
        logger.exception("Failed to persist run row run_id=%s", run_id)

    await send({"type": "routing", "agent": agent_name, "model": active_model_id, **route_pay})
    await send(
        {
            "type": "run_start",
            "dispatch_id": turn.dispatch_id,
            "run_id": run_id,
            "task_id": task_id,
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "agent": agent_name,
            "backend": "acp",
            "model": active_model_id,
            "workspace_cwd": str(workspace_cwd),
            "status": "queued",
            **route_pay,
        },
        persist=True,
        run_id=run_id,
        dispatch_id=turn.dispatch_id,
        turn_id=turn.turn_id,
    )
    await send(
        {
            "type": "task_start",
            "task_id": task_id,
            "agent": agent_name,
            "description": _preview_summary(run_message, limit=120),
            "session_id": session_id,
            "turn_id": turn.turn_id,
            **route_pay,
        },
        persist=True,
        run_id=run_id,
        dispatch_id=turn.dispatch_id,
        turn_id=turn.turn_id,
    )

    client: CorvusACPClient | None = None

    try:
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="routing",
            summary="Routing to ACP agent",
        )

        # Build and spawn ACP client
        config = ACPClientConfig(
            agent_entry=acp_entry,
            workspace=workspace_cwd,
            corvus_session_id=session_id,
            corvus_run_id=run_id,
            parent_agent=agent_name,
            parent_allows_read=parent_allows_read,
            parent_allows_write=parent_allows_write,
            parent_allows_bash=parent_allows_bash,
        )
        client = CorvusACPClient(config)

        pid = await client.spawn()
        _acp_session_tracker.create(
            corvus_run_id=run_id,
            corvus_session_id=session_id,
            acp_agent=acp_agent_name,
            parent_agent=agent_name,
            process_pid=pid,
        )

        # Initialize ACP protocol
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="planning",
            summary="Initializing ACP agent",
        )
        await client.initialize()
        _acp_session_tracker.update_status(run_id, "ready")

        # Create session
        acp_session_id = await client.new_session()
        _acp_session_tracker.set_acp_session_id(run_id, acp_session_id)

        # Send prompt
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="executing",
            summary="ACP agent executing",
        )
        _acp_session_tracker.update_status(run_id, "processing")
        await client.prompt(run_message, session_id=acp_session_id)

        # Stream responses
        async for msg in client.receive_updates():
            if turn.dispatch_interrupted.is_set():
                await client.cancel(session_id=acp_session_id)
                raise asyncio.CancelledError

            # Handle JSON-RPC responses (resolve pending futures)
            if client.resolve_response(msg):
                continue

            # Handle notifications
            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "session/update":
                events = translate_acp_update(
                    params,
                    run_id=run_id,
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    dispatch_id=turn.dispatch_id,
                    agent=agent_name,
                    model=active_model_id,
                    chunk_index=chunk_index,
                    route_payload=route_pay,
                )
                for event in events:
                    await send(
                        event,
                        persist=True,
                        run_id=run_id,
                        dispatch_id=turn.dispatch_id,
                        turn_id=turn.turn_id,
                    )
                    if event["type"] == "run_output_chunk":
                        response_parts.append(event.get("content", ""))
                        chunk_index += 1
                        assistant_summary = _preview_summary(" ".join(response_parts), limit=140)

            elif method == "fs/read_text_file":
                result = await client.handle_fs_read(params.get("path", ""))
                resp_id = msg.get("id")
                if resp_id is not None:
                    await client._write({"jsonrpc": "2.0", "id": resp_id, "result": result})

            elif method == "fs/write_text_file":
                if confirm_queue and acp_entry.default_permissions != "full-auto":
                    call_id = f"acp-write-{uuid.uuid4().hex[:8]}"
                    await send(
                        {
                            "type": "confirm_request",
                            "call_id": call_id,
                            "tool_name": "Write",
                            "description": f"ACP agent wants to write: {params.get('path', '')}",
                            "agent": agent_name,
                            **route_pay,
                        }
                    )
                    approved = await confirm_queue.wait_for_confirmation(call_id)
                    if not approved:
                        resp_id = msg.get("id")
                        if resp_id is not None:
                            await client._write(
                                {"jsonrpc": "2.0", "id": resp_id, "result": {"error": "User denied write"}}
                            )
                        continue

                result = await client.handle_fs_write(params.get("path", ""), params.get("content", ""))
                resp_id = msg.get("id")
                if resp_id is not None:
                    await client._write({"jsonrpc": "2.0", "id": resp_id, "result": result})

            elif method == "terminal/create":
                command = params.get("command", "")
                gate_result = await client.handle_terminal_create(command)
                if "error" in gate_result:
                    resp_id = msg.get("id")
                    if resp_id is not None:
                        await client._write({"jsonrpc": "2.0", "id": resp_id, "result": gate_result})
                    continue
                # Always confirm terminal commands
                if confirm_queue:
                    call_id = f"acp-bash-{uuid.uuid4().hex[:8]}"
                    await send(
                        {
                            "type": "confirm_request",
                            "call_id": call_id,
                            "tool_name": "Bash",
                            "description": f"ACP agent wants to run: {command}",
                            "agent": agent_name,
                            **route_pay,
                        }
                    )
                    approved = await confirm_queue.wait_for_confirmation(call_id)
                    if not approved:
                        resp_id = msg.get("id")
                        if resp_id is not None:
                            await client._write(
                                {"jsonrpc": "2.0", "id": resp_id, "result": {"error": "User denied command"}}
                            )
                        continue
                # Execute command in sandbox
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(workspace_cwd),
                    env=build_acp_env(workspace=workspace_cwd),
                )
                stdout, stderr = await proc.communicate()
                output = sanitize(stdout.decode(errors="replace") + stderr.decode(errors="replace"))
                resp_id = msg.get("id")
                if resp_id is not None:
                    await client._write(
                        {"jsonrpc": "2.0", "id": resp_id, "result": {"output": output, "exitCode": proc.returncode}}
                    )

            elif method == "session/request_permission":
                kind = params.get("kind", "")
                allowed = await client.handle_permission_request(kind)
                resp_id = msg.get("id")
                if resp_id is not None:
                    await client._write({"jsonrpc": "2.0", "id": resp_id, "result": {"allowed": allowed}})

            # Check for prompt completion
            if method == "session/prompt" and "result" in msg:
                break

        # Phase: compacting
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="compacting",
            summary="Finalizing ACP response",
        )

        # Final chunk marker
        await send(
            {
                "type": "run_output_chunk",
                "dispatch_id": turn.dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": session_id,
                "turn_id": turn.turn_id,
                "agent": agent_name,
                "model": active_model_id,
                "chunk_index": chunk_index,
                "content": "",
                "final": True,
                "tokens_used": tokens_used,
                "cost_usd": total_cost,
                "context_limit": 0,
                "context_pct": 0.0,
                **route_pay,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )

        # Persist assistant response
        if response_parts:
            assistant_text = " ".join(response_parts)
            transcript.messages.append({"role": "assistant", "content": assistant_text})
            runtime.session_mgr.add_message(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                agent=agent_name,
                model=active_model_id,
            )

        # run_complete
        base = base_payload_fn(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            session_id=session_id,
        )
        await send(
            {
                "type": "run_complete",
                **base,
                "result": "success",
                "summary": assistant_summary or "Completed",
                "cost_usd": total_cost,
                "tokens_used": tokens_used,
                "context_limit": 0,
                "context_pct": 0.0,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        await send(
            {
                "type": "task_complete",
                "task_id": task_id,
                "agent": agent_name,
                "result": "success",
                "summary": assistant_summary or "Completed",
                "cost_usd": total_cost,
                "session_id": session_id,
                "turn_id": turn.turn_id,
                **route_pay,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )

        _acp_session_tracker.update_status(run_id, "done")
        runtime.session_mgr.update_agent_run(
            run_id,
            status="done",
            summary=assistant_summary or "Completed",
            cost_usd=total_cost,
            tokens_used=tokens_used,
            context_limit=0,
            context_pct=0.0,
            completed_at=datetime.now(UTC),
        )

        return {
            "result": "success",
            "cost_usd": total_cost,
            "tokens_used": tokens_used,
            "context_pct": 0.0,
            "context_limit": 0,
        }

    except asyncio.CancelledError:
        _acp_session_tracker.update_status(run_id, "cancelled")
        return await emit_run_interrupted(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            summary="Interrupted by user",
            cost_usd=total_cost,
            tokens_used=tokens_used,
            context_limit=0,
            context_pct=0.0,
        )
    except Exception as exc:
        logger.exception("Error in ACP run agent=%s", agent_name)
        safe_msg = type(exc).__name__
        await send({"type": "error", "message": f"ACP error: {safe_msg}", "agent": agent_name, **route_pay})
        return await emit_run_failure(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            error_type=safe_msg,
            summary="Internal error during ACP execution",
            context_limit=0,
        )
    finally:
        if client is not None:
            try:
                await client.terminate()
            except Exception:
                logger.warning("Failed to terminate ACP agent process for run=%s", run_id)
        _acp_session_tracker.remove(run_id)
