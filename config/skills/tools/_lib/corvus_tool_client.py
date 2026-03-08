"""Corvus tool client — shared library for skill scripts.

This file is copied into each agent's workspace alongside skill scripts.
It provides the Unix socket client for calling the corvus tool server.

Dependencies: stdlib only (json, os, socket, sys). No pip packages.
"""

from __future__ import annotations

import json
import os
import socket
import sys


def call_tool(tool_name: str, params: dict) -> dict:
    """Call the corvus tool server over Unix socket.

    Reads CORVUS_TOOL_SOCKET and CORVUS_TOOL_TOKEN from environment.

    Args:
        tool_name: The full tool name (e.g., 'obsidian_search').
        params: Dict of parameters for the tool.

    Returns:
        Response dict with 'ok' (bool) and 'result' or 'error'.
    """
    socket_path = os.environ.get("CORVUS_TOOL_SOCKET", "")
    token = os.environ.get("CORVUS_TOOL_TOKEN", "")

    if not socket_path:
        return {"ok": False, "error": "CORVUS_TOOL_SOCKET not set"}
    if not token:
        return {"ok": False, "error": "CORVUS_TOOL_TOKEN not set"}

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(30)
        sock.connect(socket_path)
        request = json.dumps({
            "tool": tool_name,
            "params": params,
            "token": token,
        })
        sock.sendall(request.encode() + b"\n")

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return json.loads(response.decode())
    except socket.timeout:
        return {"ok": False, "error": "tool server timeout"}
    except ConnectionRefusedError:
        return {"ok": False, "error": "tool server not running"}
    except Exception as exc:
        return {"ok": False, "error": f"connection error: {exc}"}
    finally:
        sock.close()


def parse_cli_args(argv: list[str]) -> tuple[str, dict]:
    """Parse CLI args: action --key value --key value.

    Args:
        argv: List of args (not including script name).

    Returns:
        Tuple of (action, params_dict).
    """
    if not argv:
        return "", {}

    action = argv[0]
    params: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            key = argv[i][2:]
            params[key] = argv[i + 1]
            i += 2
        else:
            i += 1
    return action, params


def main(module_prefix: str) -> None:
    """Generic entry point for tool scripts.

    Args:
        module_prefix: The module prefix (e.g., 'obsidian', 'ha', 'memory').
    """
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"ok": False, "error": f"Usage: {sys.argv[0]} <action> [--key value ...]"}))
        sys.exit(1)

    action, params = parse_cli_args(args)
    tool_name = f"{module_prefix}_{action}" if action else module_prefix
    result = call_tool(tool_name, params)
    print(json.dumps(result, indent=2))

    if not result.get("ok"):
        sys.exit(1)
