# agent-space-sandbox — isolated execution environment for agent runs
#
# This image runs inside a Docker container spawned per agent run.
# It has no access to host files beyond the volumes explicitly mounted:
#   /workspace          (rw) — the agent's working directory for this run
#   /workspace/repo     (ro) — the source workspace repo (if provided)
#   /home/sandbox/.claude (ro, optional) — granted CLI profile state, when the
#       future one-shot Docker path is implemented
#
# Network: controlled per run.
# Resources: 1 GB RAM, 1 CPU (enforced by DockerExecutor at spawn time).
#
# Build:
#   docker build -t agent-space-sandbox sandbox/
#
# Vendor CLIs are not baked into this image. They are installed as instance
# runtime tools and mounted/resolved by the run launcher when Docker execution
# becomes available.

FROM node:20-slim

# Install system tools agents commonly need
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rename the built-in node user (UID 1000) to sandbox
# node:20-slim ships with UID 1000 already claimed, so we reuse it
RUN usermod -l sandbox -d /home/sandbox -m node \
    && groupmod -n sandbox node

# Default working directory — overridden by DockerExecutor volume mount
WORKDIR /workspace
RUN chown sandbox /workspace

USER sandbox

# No ENTRYPOINT — DockerExecutor passes the full command directly
# e.g. docker run agent-space-sandbox claude --print "..."
