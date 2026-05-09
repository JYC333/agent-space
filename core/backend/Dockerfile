# agent-space API — FastAPI backend
#
# Build context: core/backend/
# Run via docker-compose in deployments/local/
#
# Sandbox routing:
#   medium risk (default) — CLI runs as a subprocess inside THIS container (no new container).
#                           git worktree provides workspace isolation.
#   high/critical risk    — DockerExecutor spawns a one-shot agent-space-sandbox container.
#                           Docker socket is mounted via docker-compose.yml.

FROM python:3.12-slim

# Node.js — required for claude and codex CLI tools (npm packages)
# git    — required for SandboxManager.create_worktree() (git worktree add)
# curl   — healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI + Codex CLI
RUN npm install -g @anthropic-ai/claude-code \
    && npm install -g @openai/codex

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Non-root user
RUN useradd -m -u 1000 agentspace && chown -R agentspace /app
# Pre-create .claude owned by agentspace so the named volume inherits the right
# permissions when Docker seeds it on first mount (new empty volumes copy the
# image directory including ownership).
RUN mkdir -p /home/agentspace/.claude && chown agentspace:agentspace /home/agentspace/.claude
USER agentspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-exclude", "instance", \
     "--reload-exclude", "workspaces", \
     "--reload-exclude", "sandboxes", \
     "--reload-exclude", "capabilities"]
