# agent-space API — FastAPI backend
#
# Build context: repo root (so catalog/agent_templates is bundled into the image
# alongside the backend app)
# Run via docker-compose in ops/compose/
#
# Sandbox routing:
#   default (worktree)    — CLI runs as a subprocess inside THIS container (no new container);
#                           a git worktree provides workspace isolation.
#   high-risk (one_shot_docker) — an opt-in path where a one-shot agent-space-sandbox container
#                           is launched by the host-side deployer service. This backend container
#                           does NOT mount the Docker socket; only the deployer holds it.

FROM python:3.12-slim

# git      — required for SandboxManager.create_worktree() (git worktree add)
# curl     — healthcheck
# postgresql-client-${PG_MAJOR} — provides pg_dump / psql required by BackupService.
#   IMPORTANT: this MUST match the postgres server major version in
#   ops/compose/docker-compose.*.yml (postgres:${POSTGRES_MAJOR:-18}).
#   pg_dump refuses to dump a server newer than the client, so the generic Debian
#   `postgresql-client` (an older major) would break online BackupService. We
#   install the exact matching client from the official PostgreSQL APT repository
#   (PGDG). When the server major is bumped, bump POSTGRES_MAJOR in
#   ops/env/.env.*.example in lockstep (see test_backup_pg_dump_version.py).
ARG PG_MAJOR=18
ENV PG_MAJOR=${PG_MAJOR}
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
         -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-client-${PG_MAJOR}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations/ ./migrations/
# System AgentTemplate seed catalog (factories). Bundled next to the app package
# so seed_system_templates finds it at /app/agent_templates inside the container.
COPY catalog/agent_templates/ ./agent_templates/
COPY catalog/capabilities/ ./capabilities/

# Non-root user
RUN useradd -m -u 1000 agentspace && chown -R agentspace /app
# Pre-create aspace subdirectories so bind-mounts don't create them as root
RUN mkdir -p /aspace/run && chown agentspace:agentspace /aspace
USER agentspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-exclude", "instance", \
     "--reload-exclude", "workspaces", \
     "--reload-exclude", "sandboxes", \
     "--reload-exclude", "capabilities"]
