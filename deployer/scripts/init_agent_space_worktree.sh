#!/usr/bin/env bash
# init_agent_space_worktree — clone canonical repo into the system-core worktree
# Safe to call multiple times — checks if already initialized.
# Path: /aspace/workspaces/<space_id>/agent-space
set -euo pipefail

AGENT_SPACE_HOME="${AGENT_SPACE_HOME:-/aspace}"
REPO_PATH="${REPO_PATH:-/repo}"

# Target dir: must be passed as WORKSPACE_DIR (e.g. /aspace/workspaces/<space_id>/agent-space)
WORKSPACE_DIR="${WORKSPACE_DIR:-}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "[init] ERROR: WORKSPACE_DIR is not set" >&2
    exit 1
fi

# Check if already initialized (has .git = valid git repo)
if [[ -d "$WORKSPACE_DIR/.git" ]]; then
    echo "[init] agent-space worktree already initialized at $WORKSPACE_DIR"
    exit 0
fi

if [[ ! -d "$(dirname "$WORKSPACE_DIR")" ]]; then
    mkdir -p "$(dirname "$WORKSPACE_DIR")"
fi

echo "[init] cloning canonical repo from $REPO_PATH to $WORKSPACE_DIR"

cd "$REPO_PATH"

# Allow git access to the repo dir (host-mounted, owned by host uid)
git config --global --add safe.directory "*"

# Clone as regular repo (not bare) — this IS the worktree
git clone . "$WORKSPACE_DIR" 2>&1

echo "[init] success"
echo "WORKSPACE_DIR=$WORKSPACE_DIR"