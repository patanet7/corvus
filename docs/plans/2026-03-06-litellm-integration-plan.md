# LiteLLM Proxy Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hand-rolled model routing (`client_pool.py`, `ollama_probe.py` usage in routing, `env_swap` logic) with LiteLLM proxy, keeping `claude-agent-sdk` orchestration and `kimi_proxy.py` intact.

**Architecture:** LiteLLM proxy runs as an embedded subprocess managed by `LiteLLMManager`. All SDK traffic routes through `http://127.0.0.1:4000`. Config is generated from `config/models.yaml` at startup. `ollama_probe.py` stays for cognee backend usage but is removed from routing paths.

**Tech Stack:** Python 3.11+, FastAPI, claude_agent_sdk, litellm, pytest, asyncio, httpx

---

## Phase 1: LiteLLMManager + Config Translation

### Task 1: Install litellm dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add litellm to requirements**

Add `litellm` to `requirements.txt` (find the alphabetical position among existing deps).

**Step 2: Install**

Run: `uv pip install litellm`
Expected: Successful installation

**Step 3: Verify import**

Run: `uv run python -c "import litellm; print(litellm.__version__)"`
Expected: Version string printed

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add litellm for model routing proxy"
```

---

### Task 2: Write config translation tests

**Files:**
- Create: `tests/contracts/test_litellm_config.py`

**Step 1: Write the failing tests**

```python
"""Behavioral tests for LiteLLM config generation from models.yaml."""

import yaml
import pytest
from pathlib import Path


class TestConfigTranslation:
    """Verify models.yaml → litellm_config.yaml translation."""

    @staticmethod
    def _models_yaml(tmp_path: Path) -> Path:
        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "agents": {
                "finance": {"model": "opus", "params": {"temperature": 0.2}},
                "music": {"model": "haiku", "backend": "ollama"},
                "general": {"model": "sonnet", "backend": "kimi"},
            },
            "backends": {
                "claude": {"type": "sdk_native"},
                "ollama": {
                    "type": "env_swap",
                    "urls": ["http://localhost:11434"],
                    "env": {"ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": ""},
                },
                "kimi": {
                    "type": "proxy",
                    "base_url": "http://localhost:8100",
                    "env": {"ANTHROPIC_API_KEY": "not-needed"},
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        return p

    def test_generates_model_list(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        assert "model_list" in result
        model_names = {m["model_name"] for m in result["model_list"]}
        assert "sonnet" in model_names
        assert "opus" in model_names
        assert "haiku" in model_names

    def test_claude_backend_uses_anthropic_prefix(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        claude_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("model", "").startswith("anthropic/")
        ]
        assert len(claude_models) >= 1

    def test_ollama_backend_uses_ollama_prefix(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        ollama_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("model", "").startswith("ollama/")
            or m["litellm_params"].get("model", "").startswith("ollama_chat/")
        ]
        assert len(ollama_models) >= 1

    def test_kimi_backend_routes_to_kimi_proxy(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        kimi_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("api_base") == "http://localhost:8100"
        ]
        assert len(kimi_models) >= 1

    def test_router_settings_present(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        assert "router_settings" in result
        rs = result["router_settings"]
        assert rs["num_retries"] >= 1
        assert "fallbacks" in rs or "routing_strategy" in rs

    def test_generates_valid_yaml_file(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        out_path = tmp_path / "litellm_config.yaml"
        out_path.write_text(yaml.dump(result, default_flow_style=False))
        reloaded = yaml.safe_load(out_path.read_text())
        assert reloaded["model_list"] == result["model_list"]

    def test_no_api_keys_in_generated_config(self, tmp_path: Path) -> None:
        """API keys must reference env vars, never contain actual values."""
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        config_str = yaml.dump(result)
        # Should not contain real key patterns
        assert "sk-ant-" not in config_str
        assert "sk-" not in config_str.replace("os.environ/", "")

    def test_sdk_native_models_all_present(self, tmp_path: Path) -> None:
        """All three SDK-native models should be in the model list."""
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        model_names = {m["model_name"] for m in result["model_list"]}
        for expected in ("haiku", "sonnet", "opus"):
            assert expected in model_names, f"Missing SDK-native model: {expected}"
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/contracts/test_litellm_config.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_litellm_config_results.log`
Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.litellm_manager'`

**Step 3: Commit**

```bash
git add tests/contracts/test_litellm_config.py
git commit -m "test: add failing config translation tests for litellm integration"
```

---

### Task 3: Implement config translation

**Files:**
- Create: `corvus/litellm_manager.py`

**Step 1: Write the implementation**

```python
"""LiteLLM proxy manager — config generation and subprocess lifecycle.

Generates litellm_config.yaml from config/models.yaml at startup.
Manages LiteLLM proxy as a subprocess on 127.0.0.1:4000.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger("corvus-gateway.litellm")

# SDK-native model names → LiteLLM model identifiers
_SDK_MODEL_MAP: dict[str, str] = {
    "haiku": "anthropic/claude-haiku-4-5-20251001",
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "opus": "anthropic/claude-opus-4-20250514",
}

_DEFAULT_PORT = 4000
_DEFAULT_HOST = "127.0.0.1"
_HEALTH_TIMEOUT = 30.0
_HEALTH_POLL_INTERVAL = 0.5


def generate_litellm_config(models_yaml_path: Path) -> dict[str, Any]:
    """Translate config/models.yaml into a LiteLLM config dict.

    API keys are referenced via ``os.environ/VAR_NAME`` — never inlined.
    """
    with open(models_yaml_path) as f:
        config = yaml.safe_load(f) or {}

    backends = config.get("backends", {})
    model_list: list[dict[str, Any]] = []
    seen_models: set[str] = set()

    # 1. SDK-native Claude models
    for short_name, litellm_model in _SDK_MODEL_MAP.items():
        if short_name not in seen_models:
            model_list.append({
                "model_name": short_name,
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": "os.environ/ANTHROPIC_API_KEY",
                },
            })
            seen_models.add(short_name)

    # 2. Ollama models from config
    ollama_cfg = backends.get("ollama", {})
    if ollama_cfg.get("type") == "env_swap":
        urls = ollama_cfg.get("urls", [])
        api_base = urls[0] if urls else "http://localhost:11434"
        # Resolve env var references like ${OLLAMA_API_BASE:-default}
        if api_base.startswith("${") and ":-" in api_base:
            env_var = api_base.split(":-")[0].lstrip("${")
            default = api_base.split(":-")[1].rstrip("}")
            api_base = os.environ.get(env_var, default)

        # Add a generic ollama entry; LiteLLM discovers models dynamically
        model_list.append({
            "model_name": "ollama/*",
            "litellm_params": {
                "model": "ollama/*",
                "api_base": api_base,
            },
        })

    # 3. Kimi via KimiProxy
    kimi_cfg = backends.get("kimi", {})
    if kimi_cfg.get("type") == "proxy":
        base_url = kimi_cfg.get("base_url", "http://localhost:8100")
        model_list.append({
            "model_name": "kimi",
            "litellm_params": {
                "model": "openai/kimi-k2",
                "api_base": base_url,
                "api_key": "not-needed",
            },
        })

    # 4. OpenAI
    openai_cfg = backends.get("openai", {})
    if openai_cfg:
        model_list.append({
            "model_name": "openai/gpt-4o",
            "litellm_params": {
                "model": "openai/gpt-4o",
                "api_key": "os.environ/OPENAI_API_KEY",
            },
        })

    # 5. OpenAI-compatible
    compat_cfg = backends.get("openai_compat", {})
    if compat_cfg:
        model_list.append({
            "model_name": "openai-compat",
            "litellm_params": {
                "model": "openai/custom",
                "api_base": "os.environ/OPENAI_COMPAT_BASE_URL",
                "api_key": "os.environ/OPENAI_COMPAT_API_KEY",
            },
        })

    # Router settings
    router_settings: dict[str, Any] = {
        "routing_strategy": "simple-shuffle",
        "num_retries": 3,
        "allowed_fails": 3,
        "cooldown_time": 30,
        "retry_after": 5,
    }

    # Build fallback chains from config
    fallbacks: list[dict[str, list[str]]] = []
    if "ollama/*" in {m["model_name"] for m in model_list}:
        for sdk_model in _SDK_MODEL_MAP:
            fallbacks.append({sdk_model: ["ollama/*"]})
    if fallbacks:
        router_settings["fallbacks"] = fallbacks

    return {
        "model_list": model_list,
        "router_settings": router_settings,
    }


class LiteLLMManager:
    """Manages LiteLLM proxy subprocess lifecycle."""

    def __init__(
        self,
        port: int = _DEFAULT_PORT,
        host: str = _DEFAULT_HOST,
    ) -> None:
        self._port = port
        self._host = host
        self._process: subprocess.Popen | None = None
        self._config_path: Path | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self, models_yaml: Path, output_dir: Path | None = None) -> None:
        """Generate config, start proxy, wait for health check."""
        config = generate_litellm_config(models_yaml)
        out_dir = output_dir or models_yaml.parent
        self._config_path = out_dir / "litellm_config.yaml"
        self._config_path.write_text(
            yaml.dump(config, default_flow_style=False)
        )
        logger.info("Generated LiteLLM config at %s", self._config_path)

        self._process = subprocess.Popen(
            [
                "litellm",
                "--config", str(self._config_path),
                "--host", self._host,
                "--port", str(self._port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(
            "LiteLLM proxy starting on %s:%d (pid=%d)",
            self._host, self._port, self._process.pid,
        )

        await self._wait_healthy()
        os.environ["ANTHROPIC_BASE_URL"] = self.base_url
        logger.info("ANTHROPIC_BASE_URL set to %s", self.base_url)

    async def _wait_healthy(self) -> None:
        """Poll /health until LiteLLM is ready."""
        import asyncio

        deadline = time.monotonic() + _HEALTH_TIMEOUT
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{self.base_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    logger.info("LiteLLM proxy is healthy")
                    return
            except httpx.ConnectError:
                pass
            # Check if process died
            if self._process and self._process.poll() is not None:
                stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                raise RuntimeError(
                    f"LiteLLM proxy exited with code {self._process.returncode}: {stderr[:500]}"
                )
            await asyncio.sleep(_HEALTH_POLL_INTERVAL)
        raise TimeoutError(
            f"LiteLLM proxy did not become healthy within {_HEALTH_TIMEOUT}s"
        )

    async def stop(self) -> None:
        """Gracefully shut down the proxy subprocess."""
        if self._process is None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=10)
            logger.info("LiteLLM proxy stopped (pid=%d)", self._process.pid)
        except subprocess.TimeoutExpired:
            self._process.kill()
            logger.warning("LiteLLM proxy killed (pid=%d)", self._process.pid)
        finally:
            self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
```

**Step 2: Run tests to verify they pass**

Run: `uv run python -m pytest tests/contracts/test_litellm_config.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_litellm_config_results.log`
Expected: All 8 tests PASS

**Step 3: Commit**

```bash
git add corvus/litellm_manager.py
git commit -m "feat: add LiteLLMManager with config translation from models.yaml"
```

---

## Phase 2: Wire LiteLLMManager Into Runtime

### Task 4: Write LiteLLMManager lifecycle tests

**Files:**
- Modify: `tests/contracts/test_litellm_config.py`

**Step 1: Add lifecycle tests**

Append to the test file:

```python
class TestLiteLLMManagerLifecycle:
    """Verify LiteLLMManager properties and config generation to disk."""

    def test_base_url_default(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()
        assert mgr.base_url == "http://127.0.0.1:4000"

    def test_base_url_custom_port(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager(port=5555)
        assert mgr.base_url == "http://127.0.0.1:5555"

    def test_is_running_false_before_start(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()
        assert mgr.is_running is False

    def test_config_written_to_disk(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        models_yaml = tmp_path / "models.yaml"
        models_yaml.write_text(yaml.dump({
            "defaults": {"model": "sonnet", "backend": "claude"},
            "backends": {"claude": {"type": "sdk_native"}},
        }))

        config = generate_litellm_config(models_yaml)
        out = tmp_path / "litellm_config.yaml"
        out.write_text(yaml.dump(config, default_flow_style=False))
        assert out.exists()
        reloaded = yaml.safe_load(out.read_text())
        assert "model_list" in reloaded
```

**Step 2: Run tests**

Run: `uv run python -m pytest tests/contracts/test_litellm_config.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_litellm_config_lifecycle_results.log`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/contracts/test_litellm_config.py
git commit -m "test: add LiteLLMManager lifecycle property tests"
```

---

### Task 5: Add LiteLLMManager to GatewayRuntime

**Files:**
- Modify: `corvus/gateway/runtime.py`
- Modify: `corvus/server.py`

**Step 1: Add LiteLLMManager to GatewayRuntime dataclass**

In `corvus/gateway/runtime.py`:

1. Add import: `from corvus.litellm_manager import LiteLLMManager`
2. Remove import: `from corvus.client_pool import SDKClientPool`
3. Remove import: `from corvus.ollama_probe import probe_ollama_models, resolve_ollama_url`
4. In `GatewayRuntime` dataclass, replace `client_pool: SDKClientPool` with `litellm_manager: LiteLLMManager`
5. In `build_runtime()`:
   - Remove: `client_pool = SDKClientPool(model_router=model_router)`
   - Add: `litellm_manager = LiteLLMManager()`
   - In the return statement, replace `client_pool=client_pool` with `litellm_manager=litellm_manager`
6. In `_build_router_agent()`:
   - Remove the Ollama fallback block (lines 96-121) — LiteLLM handles all routing now
   - Simplify to just: `return RouterAgent(registry=agent_registry)`

**Step 2: Wire LiteLLMManager into server lifespan**

In `corvus/server.py`:

1. Remove: `client_pool = runtime.client_pool` (line 63)
2. In `lifespan()`, add LiteLLM startup before model discovery:
   ```python
   @asynccontextmanager
   async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
       del _app
       ensure_dirs()

       # Start LiteLLM proxy — must be up before model discovery
       await runtime.litellm_manager.start(Path("config/models.yaml"))

       runtime.model_router.discover_models()
       # ... rest stays the same ...
       yield
       # ... shutdown ...
       await runtime.litellm_manager.stop()
       logger.info("LiteLLM proxy stopped")
   ```

**Step 3: Verify import chain works**

Run: `uv run python -c "from corvus.gateway.runtime import GatewayRuntime; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add corvus/gateway/runtime.py corvus/server.py
git commit -m "feat: wire LiteLLMManager into GatewayRuntime, replace SDKClientPool"
```

---

### Task 6: Simplify options.py — remove env-swap and backend resolution

**Files:**
- Modify: `corvus/gateway/options.py`

**Step 1: Simplify resolve_backend_and_model**

Replace the current `resolve_backend_and_model` function (lines 365-411) and remove `_pick_fallback_model` (lines 414-426). The new version is much simpler — LiteLLM handles all fallback logic:

```python
def resolve_backend_and_model(
    runtime: GatewayRuntime,
    agent_name: str,
    requested_model: str | None,
) -> tuple[str, str]:
    """Resolve backend/model pair for the next SDK query.

    With LiteLLM proxy handling routing, this just returns the configured
    model name. LiteLLM handles fallbacks, retries, and backend selection.
    """
    if requested_model:
        token = requested_model.strip()
        if "/" in token:
            prefix, _, model_name = token.partition("/")
            if model_name:
                return prefix, model_name
        return "litellm", token

    configured = runtime.model_router.get_model(agent_name).strip()
    backend = runtime.model_router.get_backend(agent_name)
    return backend, configured
```

**Step 2: Simplify build_backend_options**

Remove the `backend_env` parameter and the env-swap merging logic. Since `ANTHROPIC_BASE_URL` is already set globally to the LiteLLM proxy, no per-call env overrides are needed:

Update the signature — remove `backend_env: dict[str, str]` parameter. Remove the line `opts.env = {**opts.env, **backend_env}`. The rest of the function stays the same.

**Step 3: Update callers of build_backend_options**

There are exactly two callers that pass `backend_env`:

1. `corvus/gateway/chat_session.py:718` — Remove the `backend_env = self.runtime.client_pool.build_env(backend_name)` line and remove `backend_env=backend_env` from the `build_backend_options()` call.

2. `corvus/gateway/background_dispatch.py:320` — Remove `backend_env = runtime.client_pool.build_env(backend_name)` line and remove `backend_env=backend_env` from the `build_backend_options()` call.

**Step 4: Run existing tests to check for breakage**

Run: `uv run python -m pytest tests/ -x -q 2>&1 | tail -20`
Expected: May see failures from `test_client_pool.py` (expected — that module is being replaced)

**Step 5: Commit**

```bash
git add corvus/gateway/options.py corvus/gateway/chat_session.py corvus/gateway/background_dispatch.py
git commit -m "refactor: simplify options.py — LiteLLM handles routing, remove env-swap"
```

---

### Task 7: Simplify model discovery to query LiteLLM

**Files:**
- Modify: `corvus/model_router.py`

**Step 1: Replace discover_models with LiteLLM query**

Remove the import `from corvus.ollama_probe import probe_ollama_models, resolve_ollama_url`.

Replace the `discover_models` method (lines 272-343) with:

```python
def discover_models(self, litellm_base_url: str = "http://127.0.0.1:4000") -> None:
    """Query LiteLLM proxy for available models.

    Falls back to config-based discovery if LiteLLM is unreachable
    (e.g. during tests without a running proxy).
    """
    models: list[ModelInfo] = []

    try:
        resp = httpx.get(f"{litellm_base_url}/models", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            for model_data in data.get("data", []):
                model_id = model_data.get("id", "")
                # Map back to our short names for SDK-native models
                short_name = model_id
                backend = "litellm"
                for name, full_id in self._litellm_model_map().items():
                    if model_id == full_id:
                        short_name = name
                        backend = "claude"
                        break
                if "ollama" in model_id:
                    backend = "ollama"
                supports_tools, supports_streaming = self._capabilities_for_backend(backend)
                models.append(
                    ModelInfo(
                        id=short_name,
                        label=short_name.title() if "/" not in short_name else short_name,
                        backend=backend,
                        available=True,
                        description=f"via LiteLLM — {model_id}",
                        is_default=short_name == self.default_model,
                        supports_tools=supports_tools,
                        supports_streaming=supports_streaming,
                    )
                )
            self._discovered_models = models
            logger.info("Discovered %d models from LiteLLM proxy", len(models))
            return
    except Exception:
        logger.warning("LiteLLM proxy unreachable, falling back to config-based discovery")

    # Fallback: populate from config (for tests and offline scenarios)
    for model_name in sorted(self._sdk_native_models - {"inherit"}):
        supports_tools, supports_streaming = self._capabilities_for_backend("claude")
        models.append(
            ModelInfo(
                id=model_name,
                label=model_name.title(),
                backend="claude",
                available=True,
                description=f"Claude {model_name.title()}",
                is_default=model_name == self.default_model,
                supports_tools=supports_tools,
                supports_streaming=supports_streaming,
            )
        )
    self._discovered_models = models
    logger.info("Config-based discovery: %d models", len(models))

@staticmethod
def _litellm_model_map() -> dict[str, str]:
    """Short name → LiteLLM model ID for SDK-native models."""
    return {
        "haiku": "anthropic/claude-haiku-4-5-20251001",
        "sonnet": "anthropic/claude-sonnet-4-20250514",
        "opus": "anthropic/claude-opus-4-20250514",
    }
```

Also add `import httpx` at the top of the file (it's already a project dependency).

**Step 2: Remove _is_chat_ollama_model static method**

This method is no longer needed since LiteLLM handles Ollama model filtering.

**Step 3: Run model router tests**

Run: `uv run python -m pytest tests/contracts/test_model_router.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_model_router_results.log`
Expected: Tests pass (most tests use config-based methods, not discovery)

**Step 4: Commit**

```bash
git add corvus/model_router.py
git commit -m "refactor: model discovery queries LiteLLM proxy, remove ollama_probe dependency"
```

---

## Phase 3: Remove Dead Code + Update Tests

### Task 8: Delete client_pool.py

**Files:**
- Delete: `corvus/client_pool.py`
- Modify: `corvus/gateway/__init__.py` (if it re-exports anything from client_pool)

**Step 1: Delete the file**

```bash
rm corvus/client_pool.py
```

**Step 2: Remove any re-exports**

Check `corvus/gateway/__init__.py` — it does NOT re-export `SDKClientPool`, so no changes needed there.

Check `corvus/server.py` — remove the line `client_pool = runtime.client_pool` (already done in Task 5).

**Step 3: Verify no remaining imports**

Run: `uv run python -m pytest tests/ -x --collect-only 2>&1 | grep "error" | head -10`
Expected: No import errors from `corvus.client_pool`

**Step 4: Commit**

```bash
git add -u corvus/client_pool.py
git commit -m "refactor: delete client_pool.py — routing handled by LiteLLM"
```

---

### Task 9: Rewrite client_pool tests as litellm config tests

**Files:**
- Delete: `tests/contracts/test_client_pool.py`

The behavioral contracts previously tested by `test_client_pool.py` (backend resolution, fallback chains, env building) are now handled by LiteLLM and tested in `test_litellm_config.py` (Task 2). The old tests directly import `SDKClientPool` which no longer exists.

**Step 1: Delete the old test file**

```bash
rm tests/contracts/test_client_pool.py
```

**Step 2: Verify remaining tests pass**

Run: `uv run python -m pytest tests/ -x -q 2>&1 | tail -20`
Expected: No import errors

**Step 3: Commit**

```bash
git add -u tests/contracts/test_client_pool.py
git commit -m "test: remove client_pool tests — contracts covered by litellm config tests"
```

---

### Task 10: Update gateway __init__.py exports

**Files:**
- Modify: `corvus/gateway/__init__.py`

**Step 1: Check if resolve_backend_and_model signature changed**

The function still exists with the same name but simplified logic. The `__init__.py` exports it — no changes needed there.

**Step 2: Verify the export list is clean**

Run: `uv run python -c "from corvus.gateway import resolve_backend_and_model, build_backend_options; print('OK')"`
Expected: `OK`

**Step 3: Commit (if any changes needed)**

```bash
git add corvus/gateway/__init__.py
git commit -m "refactor: update gateway exports after litellm integration"
```

---

### Task 11: Update models.yaml config format

**Files:**
- Modify: `config/models.yaml`

**Step 1: Update the config comments**

Update the comments in `config/models.yaml` to reflect that LiteLLM now handles routing:

- Remove references to "provider adapter layer (Slice 10B)"
- Remove "Uncomment after KimiProxy is deployed" — update to show kimi is available
- Update backend type descriptions to mention LiteLLM
- Enable the commented-out `backend: kimi` for general agent if appropriate

**Step 2: Add litellm section for configurable retry/fallback settings**

Add a new top-level section to `config/models.yaml`:

```yaml
# LiteLLM proxy configuration — routing, retries, fallbacks.
# These settings are translated into litellm_config.yaml at startup.
litellm:
  port: 4000
  host: "127.0.0.1"
  num_retries: 3
  cooldown_time: 30
  retry_after: 5
  routing_strategy: "simple-shuffle"
```

**Step 3: Update LiteLLMManager to read these settings**

In `corvus/litellm_manager.py`, update `generate_litellm_config` to read `config.get("litellm", {})` for port/retry settings instead of hardcoding them.

**Step 4: Commit**

```bash
git add config/models.yaml corvus/litellm_manager.py
git commit -m "config: add litellm section to models.yaml for routing settings"
```

---

### Task 12: Update config.example

**Files:**
- Modify or create: `config.example/models.yaml`

**Step 1: Check if config.example exists**

Run: `ls config.example/`

**Step 2: Update example config**

Copy updated `config/models.yaml` structure to `config.example/models.yaml`, removing any deployment-specific values but keeping the structure and comments.

**Step 3: Commit**

```bash
git add config.example/models.yaml
git commit -m "docs: update example models.yaml with litellm config section"
```

---

## Phase 4: Full Validation

### Task 13: Run full test suite

**Files:**
- No new files

**Step 1: Run all tests**

Run: `uv run python -m pytest tests/ -v --tb=short 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_full_suite_litellm_results.log`
Expected: All tests pass (except any that require a running LiteLLM proxy, which should gracefully degrade)

**Step 2: Fix any failures**

Address each failure individually:
- Import errors → update imports to remove `client_pool` / `ollama_probe` references from routing code
- Test assertions → update expected values for simplified routing
- Runtime attribute errors → ensure `GatewayRuntime.litellm_manager` is used consistently

**Step 3: Commit fixes**

```bash
git add -A
git commit -m "fix: resolve test failures after litellm integration"
```

---

### Task 14: Verify models.yaml → litellm config end-to-end

**Files:**
- Modify: `tests/contracts/test_litellm_config.py`

**Step 1: Add end-to-end config test using real models.yaml**

```python
class TestRealModelsYaml:
    """Test config translation against the actual config/models.yaml."""

    def test_real_config_translates(self) -> None:
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        assert len(result["model_list"]) >= 3  # at least haiku/sonnet/opus
        assert "router_settings" in result

    def test_real_config_has_no_secrets(self) -> None:
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        config_str = yaml.dump(result)
        assert "sk-ant-" not in config_str
```

**Step 2: Run**

Run: `uv run python -m pytest tests/contracts/test_litellm_config.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_litellm_config_e2e_results.log`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/contracts/test_litellm_config.py
git commit -m "test: add end-to-end litellm config translation tests"
```

---

### Task 15: Final cleanup — remove stale references and update docs

**Files:**
- Modify: `CLAUDE.md` (update architecture summary)
- Modify: `corvus/gateway/options.py` (remove unused `_pick_fallback_model` if not already removed)

**Step 1: Update CLAUDE.md architecture summary**

In the "Multi-Backend Model Routing" section, update to mention LiteLLM:

```markdown
## Multi-Backend Model Routing

**Corvus uses LiteLLM proxy for model routing.** At startup, `LiteLLMManager` generates a `litellm_config.yaml` from `config/models.yaml` and starts a local proxy on `127.0.0.1:4000`. The `claude-agent-sdk` talks to this proxy via `ANTHROPIC_BASE_URL`.

- **Claude**: Direct Anthropic API via LiteLLM
- **Ollama**: Routed by LiteLLM to local Ollama instance
- **Kimi**: Routed through KimiProxy (`localhost:8100`) registered as LiteLLM backend
- **OpenAI / Groq / etc.**: Add to `config/models.yaml` backends section

LiteLLM handles fallbacks, retries, cooldowns, and cost tracking. `config/models.yaml` is the single source of truth.
```

**Step 2: Verify no stale `client_pool` or routing `ollama_probe` references remain**

Run: `grep -r "client_pool\|from corvus.client_pool\|SDKClientPool" corvus/ --include="*.py" | grep -v __pycache__`
Expected: No results (cognee's `ollama_probe` usage is fine — it's not routing)

Run: `grep -r "from corvus.ollama_probe" corvus/ --include="*.py" | grep -v __pycache__ | grep -v cognee | grep -v memory`
Expected: No results (only cognee/memory should reference it)

**Step 3: Commit**

```bash
git add CLAUDE.md corvus/gateway/options.py
git commit -m "docs: update architecture for litellm integration, remove stale references"
```
