FROM python:3.13-slim-bookworm

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client curl git bash && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (required by claude-agent-sdk)
RUN curl -fsSL https://claude.ai/install.sh | bash

WORKDIR /app

# Python dependencies — install first for Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY corvus/ ./corvus/
COPY scripts/ ./scripts/
COPY mcp_servers/ ./mcp_servers/
COPY .claude/ ./.claude/

EXPOSE 18789

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18789/health')"

CMD ["python", "-m", "corvus.server"]
