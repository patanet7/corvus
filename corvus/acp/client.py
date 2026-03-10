"""ACP Client — spawns and orchestrates ACP agent processes with 7-layer security.

CorvusACPClient manages the full lifecycle of an ACP-compatible agent process:
spawn, initialize, session management, prompt dispatch, security-gated callbacks,
and graceful termination. All communication uses JSON-RPC 2.0 over stdio (NDJSON).

Security layers enforced:
1. Environment stripping (sandbox.build_acp_spawn_env / build_acp_child_env)
2. Process isolation (sandbox.build_sandbox_command)
3. File gate (file_gate.check_file_access)
4. Terminal gate (terminal_gate.check_terminal_command)
5. Permission mapping (permission_map.map_acp_permission)
6. Output sanitization (sanitize.sanitize)
7. Capability advertisement (build_capabilities)
"""

import asyncio
import json
import signal
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corvus.acp.file_gate import check_file_access
from corvus.acp.permission_map import map_acp_permission
from corvus.acp.registry import AcpAgentEntry
from corvus.acp.sandbox import build_acp_spawn_env, build_sandbox_command
from corvus.acp.terminal_gate import check_terminal_command
import structlog
from corvus.sanitize import sanitize

logger = structlog.get_logger(__name__)

ACP_PROTOCOL_VERSION = 1
CLIENT_NAME = "corvus-gateway"
CLIENT_VERSION = "1.0.0"


@dataclass
class ACPClientConfig:
    """Configuration for spawning a CorvusACPClient.

    Attributes:
        agent_entry: The ACP agent registry entry describing the agent binary.
        workspace: Filesystem path to the agent's sandboxed workspace.
        corvus_session_id: Corvus session identifier for tracing.
        corvus_run_id: Corvus run identifier for tracing.
        parent_agent: Name of the Corvus domain agent that owns this ACP agent.
        parent_allows_read: Whether the parent agent policy permits file reads.
        parent_allows_write: Whether the parent agent policy permits file writes.
        parent_allows_bash: Whether the parent agent policy permits bash execution.
    """

    agent_entry: AcpAgentEntry
    workspace: Path
    corvus_session_id: str
    corvus_run_id: str
    parent_agent: str
    parent_allows_read: bool = True
    parent_allows_write: bool = True
    parent_allows_bash: bool = True


class CorvusACPClient:
    """Client for spawning and communicating with an ACP-compatible agent process.

    Manages JSON-RPC 2.0 communication over stdio, enforces all 7 security
    layers through capability advertisement and request callbacks.

    Args:
        config: Client configuration specifying the agent and security policy.
    """

    def __init__(self, config: ACPClientConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id: int = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    @property
    def agent_name(self) -> str:
        """Name of the ACP agent."""
        return self._config.agent_entry.name

    @property
    def workspace(self) -> Path:
        """Workspace directory for the ACP agent."""
        return self._config.workspace

    def build_capabilities(self) -> dict[str, Any]:
        """Build ACP clientCapabilities dict based on parent agent policy.

        Only advertises capabilities that the parent agent permits.
        If neither read nor write is allowed, the ``fs`` key is omitted entirely.
        If bash is not allowed, the ``terminal`` key is omitted.

        Returns:
            Dict of ACP capability sections to advertise to the agent.
        """
        caps: dict[str, Any] = {}

        # File system capabilities
        fs: dict[str, bool] = {}
        if self._config.parent_allows_read:
            fs["readTextFile"] = True
        if self._config.parent_allows_write:
            fs["writeTextFile"] = True
        if fs:
            caps["fs"] = fs

        # Terminal capabilities (ACP spec: boolean)
        if self._config.parent_allows_bash:
            caps["terminal"] = True

        return caps

    async def spawn(self) -> int:
        """Spawn the ACP agent process in a sandboxed environment.

        Builds a sanitized environment, wraps the command in a platform sandbox,
        and starts the subprocess with stdin/stdout/stderr pipes.

        Returns:
            The PID of the spawned process.

        Raises:
            RuntimeError: If the process fails to start.
        """
        env = build_acp_spawn_env(workspace=self._config.workspace)
        cmd_parts = self._config.agent_entry.command_parts()
        sandboxed_cmd = build_sandbox_command(cmd_parts, workspace=self._config.workspace)

        logger.info(
            "acp_agent_spawning",
            agent_name=self.agent_name,
            command=sandboxed_cmd,
            workspace=str(self._config.workspace),
        )

        self._process = await asyncio.create_subprocess_exec(
            *sandboxed_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._config.workspace),
            env=env,
        )

        pid = self._process.pid
        logger.info("acp_agent_spawned", agent_name=self.agent_name, pid=pid)
        return pid

    async def initialize(self) -> dict[str, Any]:
        """Send the JSON-RPC initialize request to the ACP agent.

        Returns:
            The result dict from the agent's initialize response.
        """
        return await self._send_request(
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientInfo": {
                    "name": CLIENT_NAME,
                    "version": CLIENT_VERSION,
                },
                "clientCapabilities": self.build_capabilities(),
            },
        )

    async def new_session(self) -> str:
        """Create a new ACP session.

        Returns:
            The session ID assigned by the ACP agent.
        """
        result = await self._send_request(
            "session/new",
            {
                "cwd": str(self._config.workspace),
                "mcpServers": [],
            },
        )
        return result.get("sessionId", "")

    async def prompt(self, message: str, session_id: str) -> None:
        """Send a prompt to the ACP agent session.

        Args:
            message: The user message to send.
            session_id: The ACP session ID to prompt.
        """
        await self._send_request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": message}],
            },
        )

    async def cancel(self, session_id: str) -> None:
        """Send a cancellation notification for an ACP session.

        Args:
            session_id: The ACP session ID to cancel.
        """
        await self._send_notification(
            "session/cancel",
            {"sessionId": session_id},
        )

    async def receive_updates(self) -> AsyncIterator[dict[str, Any]]:
        """Read NDJSON lines from the agent's stdout and yield parsed dicts.

        Yields:
            Parsed JSON-RPC messages from the agent process.
        """
        if self._process is None or self._process.stdout is None:
            return

        while True:
            line = await self._process.stdout.readline()
            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.warning(
                    "acp_agent_non_json_line",
                    agent_name=self.agent_name,
                    line=text[:200],
                )
                continue

            yield msg

    def resolve_response(self, msg: dict[str, Any]) -> bool:
        """Resolve a pending request future if the message has a matching ID.

        Args:
            msg: A parsed JSON-RPC message that may contain an ``id`` field.

        Returns:
            True if the message matched and resolved a pending future.
        """
        msg_id = msg.get("id")
        if msg_id is None:
            return False

        future = self._pending.pop(msg_id, None)
        if future is None:
            return False

        if "error" in msg:
            future.set_exception(
                RuntimeError(
                    f"ACP agent {self.agent_name!r} returned error: {msg['error']}"
                )
            )
        else:
            future.set_result(msg.get("result", {}))

        return True

    async def handle_fs_read(
        self, path: str, *, allow_secret_access: bool = False,
    ) -> dict[str, Any]:
        """Handle an ACP fs/readTextFile callback with file gate enforcement.

        Args:
            path: The file path the agent wants to read.
            allow_secret_access: If True (break-glass), bypass secret pattern checks.

        Returns:
            Dict with ``content`` key on success, or ``error`` key on denial.
        """
        result = check_file_access(
            path=path,
            workspace_root=self._config.workspace,
            operation="read",
            parent_allows_read=self._config.parent_allows_read,
            parent_allows_write=self._config.parent_allows_write,
            allow_secret_access=allow_secret_access,
        )

        if not result.allowed:
            logger.warning(
                "acp_fs_read_denied",
                agent_name=self.agent_name,
                path=path,
                reason=result.reason,
            )
            return {"error": result.reason}

        try:
            content = result.resolved_path.read_text(encoding="utf-8")
            return {"content": sanitize(content)}
        except OSError as exc:
            return {"error": f"Read failed: {exc}"}

    async def handle_fs_write(
        self, path: str, content: str, *, allow_secret_access: bool = False,
    ) -> dict[str, Any]:
        """Handle an ACP fs/writeTextFile callback with file gate enforcement.

        Args:
            path: The file path the agent wants to write.
            content: The content to write.
            allow_secret_access: If True (break-glass), bypass secret pattern checks.

        Returns:
            Dict with ``success`` key on success, or ``error`` key on denial.
        """
        result = check_file_access(
            path=path,
            workspace_root=self._config.workspace,
            operation="write",
            parent_allows_read=self._config.parent_allows_read,
            parent_allows_write=self._config.parent_allows_write,
            allow_secret_access=allow_secret_access,
        )

        if not result.allowed:
            logger.warning(
                "acp_fs_write_denied",
                agent_name=self.agent_name,
                path=path,
                reason=result.reason,
            )
            return {"error": result.reason}

        try:
            result.resolved_path.parent.mkdir(parents=True, exist_ok=True)
            result.resolved_path.write_text(content, encoding="utf-8")
            return {"success": True}
        except OSError as exc:
            return {"error": f"Write failed: {exc}"}

    async def handle_terminal_create(
        self, command: str
    ) -> dict[str, Any]:
        """Handle an ACP terminal/create callback with terminal gate enforcement.

        Args:
            command: The shell command the agent wants to execute.

        Returns:
            Dict with ``allowed``, ``requires_confirm``, and ``command`` keys
            on success, or ``error`` key on denial.
        """
        result = check_terminal_command(
            command=command,
            parent_allows_bash=self._config.parent_allows_bash,
        )

        if not result.allowed:
            logger.warning(
                "acp_terminal_command_denied",
                agent_name=self.agent_name,
                command=command,
                reason=result.reason,
            )
            return {"error": result.reason}

        return {
            "allowed": True,
            "requires_confirm": result.requires_confirm,
            "command": command,
        }

    async def handle_permission_request(self, kind: str) -> bool:
        """Handle an ACP session/request_permission callback.

        Maps the ACP permission kind to a Corvus capability and checks
        against parent policy.

        Args:
            kind: The ACP permission kind (e.g. "read", "execute").

        Returns:
            True if the permission is granted, False otherwise.
        """
        mapped = map_acp_permission(kind)

        # None means always allowed (e.g. "think")
        if mapped is None:
            return True

        # __DENIED__ means unknown kind — deny by default
        if mapped == "__DENIED__":
            logger.warning(
                "acp_permission_denied_unknown_kind",
                agent_name=self.agent_name,
                kind=kind,
            )
            return False

        # Check against parent policy
        policy_map: dict[str, bool] = {
            "Read": self._config.parent_allows_read,
            "Grep": self._config.parent_allows_read,
            "Write": self._config.parent_allows_write,
            "Bash": self._config.parent_allows_bash,
            "WebFetch": False,  # Network access denied by default
        }

        allowed = policy_map.get(mapped, False)
        if not allowed:
            logger.warning(
                "acp_permission_denied",
                agent_name=self.agent_name,
                kind=kind,
                mapped=mapped,
            )
        return allowed

    async def terminate(self, timeout: float = 5.0) -> None:
        """Gracefully terminate the ACP agent process.

        Closes stdin, waits for graceful exit, sends SIGTERM, waits again,
        then sends SIGKILL as last resort.

        Args:
            timeout: Seconds to wait at each stage before escalating.
        """
        if self._process is None:
            return

        pid = self._process.pid
        logger.info("acp_agent_terminating", agent_name=self.agent_name, pid=pid)

        # Close stdin to signal EOF
        if self._process.stdin is not None:
            self._process.stdin.close()
            try:
                await self._process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        # Wait for graceful exit
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
            logger.info("acp_agent_exited_gracefully", agent_name=self.agent_name)
            return
        except TimeoutError:
            pass

        # SIGTERM
        logger.warning("acp_agent_sigterm", agent_name=self.agent_name)
        try:
            self._process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
            logger.info("acp_agent_exited_after_sigterm", agent_name=self.agent_name)
            return
        except TimeoutError:
            pass

        # SIGKILL
        logger.warning("acp_agent_sigkill", agent_name=self.agent_name)
        try:
            self._process.kill()
        except ProcessLookupError:
            return

        await self._process.wait()
        logger.info("acp_agent_killed", agent_name=self.agent_name)

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result.

        Args:
            method: The JSON-RPC method name.
            params: The request parameters.

        Returns:
            The result dict from the response.

        Raises:
            RuntimeError: If the agent returns an error response.
        """
        self._request_id += 1
        req_id = self._request_id

        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future

        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        await self._write(msg)
        return await future

    async def _send_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The JSON-RPC method name.
            params: The notification parameters.
        """
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write(msg)

    async def _write(self, msg: dict[str, Any]) -> None:
        """Write a JSON-RPC message to the agent's stdin as NDJSON.

        Args:
            msg: The JSON-RPC message to send.

        Raises:
            RuntimeError: If the process is not running or stdin is unavailable.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError(
                f"ACP agent {self.agent_name!r} process is not running"
            )

        line = json.dumps(msg, separators=(",", ":")) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()
