"""Behavioral tests for Docker build and compose contracts.

Validates Dockerfile and compose.yaml structure without actually
building Docker images — ensures the files match deployment expectations.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = ROOT / "corvus" / "Dockerfile"
COMPOSE = ROOT / "infra" / "stacks" / "laptop-server" / "claw" / "compose.yaml"


class TestDockerfile:
    """Tests for Dockerfile."""

    def test_dockerfile_exists(self):
        assert DOCKERFILE.exists()

    @pytest.fixture
    def content(self) -> str:
        return DOCKERFILE.read_text()

    def test_base_image_is_python_slim(self, content):
        assert "python:3.13-slim-bookworm" in content

    def test_installs_openssh_client(self, content):
        assert "openssh-client" in content

    def test_installs_claude_code_cli(self, content):
        assert "claude.ai/install.sh" in content

    def test_copies_requirements_before_code(self, content):
        """Requirements copied first for Docker layer caching."""
        req_pos = content.index("COPY requirements.txt")
        claw_pos = content.index("COPY corvus/")
        assert req_pos < claw_pos

    def test_copies_claw_code(self, content):
        assert "COPY corvus/" in content

    def test_copies_scripts(self, content):
        assert "COPY scripts/" in content

    def test_copies_claude_config(self, content):
        assert "COPY .claude/" in content

    def test_exposes_port_18789(self, content):
        assert "EXPOSE 18789" in content

    def test_healthcheck_defined(self, content):
        assert "HEALTHCHECK" in content
        assert "18789/health" in content

    def test_cmd_runs_claw_server(self, content):
        assert "corvus.server" in content


class TestComposeYaml:
    """Tests for infra/stacks/laptop-server/claw/compose.yaml."""

    def test_compose_exists(self):
        assert COMPOSE.exists()

    @pytest.fixture
    def config(self) -> dict:
        return yaml.safe_load(COMPOSE.read_text())

    @pytest.fixture
    def service(self, config) -> dict:
        return config["services"]["claw-gateway"]

    def test_container_name(self, service):
        assert service["container_name"] == "claw-gateway"

    def test_restart_always(self, service):
        assert service["restart"] == "always"

    def test_init_true(self, service):
        assert service["init"] is True

    def test_build_context_points_to_repo_root(self, service):
        assert service["build"]["context"] == "../../../../"

    def test_build_dockerfile_path(self, service):
        assert service["build"]["dockerfile"] == "corvus/Dockerfile"

    def test_anthropic_api_key_from_env(self, service):
        env = service["environment"]
        assert env["ANTHROPIC_API_KEY"] == "${ANTHROPIC_API_KEY}"

    def test_memory_dir_points_to_vaults(self, service):
        """MEMORY_DIR must point to Obsidian vault mount, not /data."""
        env = service["environment"]
        assert env["MEMORY_DIR"] == "/mnt/vaults"

    def test_cognee_data_dir(self, service):
        env = service["environment"]
        assert env["COGNEE_DATA_DIR"] == "/data/cognee"

    def test_workspace_dir_env(self, service):
        env = service["environment"]
        assert env["WORKSPACE_DIR"] == "/data/workspace"

    def test_events_log_env(self, service):
        env = service["environment"]
        assert env["EVENTS_LOG"] == "/var/log/claw/events.jsonl"

    def test_allowed_users(self, service):
        env = service["environment"]
        assert env["ALLOWED_USERS"] == "testuser"

    def test_data_volume_mounted(self, service):
        volumes = service["volumes"]
        data_vol = [v for v in volumes if ":/data" in v]
        assert len(data_vol) == 1

    def test_obsidian_vault_is_readwrite(self, service):
        """CRITICAL: Obsidian vault must be RW for memory writes."""
        volumes = service["volumes"]
        vault_vols = [v for v in volumes if "/mnt/vaults" in v]
        assert len(vault_vols) == 1
        # Must NOT have :ro suffix
        assert not vault_vols[0].endswith(":ro"), f"Obsidian vault must be RW, got: {vault_vols[0]}"

    def test_docker_socket_mounted(self, service):
        volumes = service["volumes"]
        sock_vols = [v for v in volumes if "docker.sock" in v]
        assert len(sock_vols) == 1

    def test_docker_binary_readonly(self, service):
        volumes = service["volumes"]
        bin_vols = [v for v in volumes if "/usr/bin/docker" in v]
        assert len(bin_vols) == 1
        assert bin_vols[0].endswith(":ro")

    def test_log_volume_mounted(self, service):
        volumes = service["volumes"]
        log_vols = [v for v in volumes if "/var/log/claw" in v]
        assert len(log_vols) == 1

    def test_docker_group_add(self, service):
        assert "988" in service["group_add"]

    def test_port_bound_to_lan_ip(self, service):
        ports = service["ports"]
        assert any("127.0.0.1:18789:18789" in p for p in ports)

    def test_memory_limit(self, service):
        limits = service["deploy"]["resources"]["limits"]
        assert limits["memory"] == "4G"

    def test_memory_reservation(self, service):
        reservations = service["deploy"]["resources"]["reservations"]
        assert reservations["memory"] == "1G"

    def test_healthcheck_uses_health_endpoint(self, service):
        hc = service["healthcheck"]
        test_cmd = " ".join(hc["test"])
        assert "18789/health" in test_cmd

    def test_healthcheck_intervals(self, service):
        hc = service["healthcheck"]
        assert hc["interval"] == "30s"
        assert hc["timeout"] == "10s"
        assert hc["retries"] == 3
        assert hc["start_period"] == "30s"

    def test_komodo_skip_label(self, service):
        labels = service.get("labels", {})
        assert labels.get("komodo.skip") == "true"
