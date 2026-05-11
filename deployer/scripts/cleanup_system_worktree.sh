#!/usr/bin/env bash
# cleanup_system_worktree — remove an agent-space self-evolution worktree
# Args: WORKSPACE_DIR=<path>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
REPO_PATH="${REPO_PATH:-/repo}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "[cleanup] worktree does not exist at $WORKSPACE_DIR, nothing to do"
    exit 0
fi

echo "[cleanup] removing worktree at $WORKSPACE_DIR"

CANONICAL_REPO="$REPO_PATH"

cd "$CANONICAL_REPO"
git config --global --add safe.directory "*"
git config --global --add safe.directory "$WORKSPACE_DIR"
git worktree remove --force "$WORKSPACE_DIR" 2>&1 || {
    # Fallback: just remove the directory
    rm -rf "$WORKSPACE_DIR"
}

echo "[cleanup] success"