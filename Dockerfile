FROM python:3.13-slim-bookworm AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client curl git bash && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Claude Code CLI (required by claude-agent-sdk)
RUN curl -fsSL https://claude.ai/install.sh | bash

WORKDIR /app

# Python dependencies — install prod-only deps from lockfile for caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

FROM python:3.13-slim-bookworm

RUN useradd -r -m corvus
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client git bash && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.claude /home/corvus/.claude
RUN chown -R corvus:corvus /home/corvus/.claude
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY corvus/ ./corvus/
COPY config/ ./config/

RUN mkdir -p /app/.data && chown corvus:corvus /app/.data

EXPOSE 18789
USER corvus

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18789/health')"

CMD ["python", "-m", "corvus.server"]
