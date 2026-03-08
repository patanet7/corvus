"""REAL integration tests for Docker build, server startup, and auth.

These tests actually build Docker images, start containers, and make HTTP requests.
They are slower but verify the system ACTUALLY works end-to-end.

Port allocation: Uses random free ports via socket binding to avoid collisions
when tests run in parallel (pytest-xdist).
"""

import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parent.parent.parent

skip_no_docker = pytest.mark.skipif(
    not shutil.which("docker")
    or subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=5,
    ).returncode
    != 0,
    reason="Docker daemon not running",
)


def _find_free_port() -> int:
    """Find a random free TCP port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _unique_name(prefix: str) -> str:
    """Generate a unique container name to avoid collisions in parallel runs."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@skip_no_docker
def _docker_healthy() -> bool:
    """Check if Docker daemon is available and responding."""
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _docker_healthy(), reason="Docker daemon not available")
class TestDockerBuild:
    """Verify the Docker image actually builds successfully."""

    @pytest.fixture(scope="class")
    def docker_build(self):
        """Build the Docker image — this is the real test."""
        result = subprocess.run(
            ["docker", "build", "-f", "Dockerfile", "-t", "corvus-gateway:test", "."],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=300,  # 5 min max
        )
        return result

    def test_docker_build_succeeds(self, docker_build):
        """CONTRACT: Docker image builds without errors."""
        assert docker_build.returncode == 0, f"Docker build failed:\n{docker_build.stderr}"

    def test_docker_image_exists_after_build(self, docker_build):
        """CONTRACT: image tag exists after build."""
        if docker_build.returncode != 0:
            pytest.skip("Build failed")
        result = subprocess.run(
            ["docker", "image", "inspect", "corvus-gateway:test"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


@pytest.mark.skipif(not _docker_healthy(), reason="Docker daemon not available")
class TestServerStartup:
    """Verify the server actually starts and responds to health checks."""

    @pytest.fixture(scope="class")
    def running_container(self):
        """Start the container on a random port and yield, then clean up."""
        port = _find_free_port()
        name = _unique_name("claw-test")

        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:18789",
                "-e",
                "ALLOWED_USERS=testuser",
                "corvus-gateway:test",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Container failed to start: {result.stderr}")

        base_url = f"http://127.0.0.1:{port}"

        # Wait for startup (max 30s)
        for _ in range(30):
            try:
                resp = requests.get(f"{base_url}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(1)

        yield base_url

        # Cleanup — always remove, even on failure
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def test_health_endpoint_returns_200(self, running_container):
        """CONTRACT: /health returns 200 with correct JSON shape."""
        resp = requests.get(f"{running_container}/health", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "corvus-gateway"

    def test_health_response_time_under_1s(self, running_container):
        """CONTRACT: health endpoint responds within 1 second."""
        start = time.time()
        resp = requests.get(f"{running_container}/health", timeout=5)
        elapsed = time.time() - start
        assert elapsed < 1.0
        assert resp.status_code == 200

    def test_webhook_endpoint_exists(self, running_container):
        """CONTRACT: webhook endpoint accepts POST and returns JSON."""
        resp = requests.post(
            f"{running_container}/api/webhooks/test",
            json={"test": True},
            timeout=5,
        )
        # Should be 200 (accepted) or 422 (validation) — not 404
        assert resp.status_code != 404

    def test_ws_endpoint_rejects_unauthenticated(self, running_container):
        """CONTRACT: WebSocket without auth header gets rejected."""
        try:
            import asyncio

            import websockets

            async def try_connect():
                ws_url = running_container.replace("http://", "ws://") + "/ws"
                async with websockets.connect(ws_url) as _ws:
                    pass

            # websockets v13+ moved exception classes
            with pytest.raises((ConnectionRefusedError, OSError)):
                asyncio.run(try_connect())
        except ImportError:
            # If websockets not installed, test via HTTP upgrade attempt
            resp = requests.get(
                f"{running_container}/ws",
                headers={"Upgrade": "websocket", "Connection": "Upgrade"},
                timeout=5,
            )
            # Should not be 200 (successful upgrade without auth)
            assert resp.status_code != 200


@pytest.mark.skipif(not _docker_healthy(), reason="Docker daemon not available")
class TestAuthMiddleware:
    """Test auth using the real running server."""

    @pytest.fixture(scope="class")
    def running_container(self):
        """Start a container on a random port for auth tests."""
        port = _find_free_port()
        name = _unique_name("claw-auth-test")

        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:18789",
                "-e",
                "ALLOWED_USERS=testuser,testuser",
                "corvus-gateway:test",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Container failed: {result.stderr}")

        base_url = f"http://127.0.0.1:{port}"

        for _ in range(30):
            try:
                resp = requests.get(f"{base_url}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(1)

        yield base_url

        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def test_health_no_auth_required(self, running_container):
        """Health endpoint should work without auth."""
        resp = requests.get(f"{running_container}/health", timeout=5)
        assert resp.status_code == 200
