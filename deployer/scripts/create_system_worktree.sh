#!/usr/bin/env bash
# create_system_worktree — create a git worktree for agent-space self-evolution
# Args: WORKSPACE_DIR=<absolute-path> BRANCH_NAME=<branch-name>
set -euo pipefail

REPO_PATH="${REPO_PATH:-/repo}"

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
BRANCH_NAME="${BRANCH_NAME:-agent-run/self-evolution}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

# Canonical repo is the bind-mounted repo root
CANONICAL_REPO="$REPO_PATH"

echo "[create_worktree] worktree_dir=$WORKSPACE_DIR branch=$BRANCH_NAME"

mkdir -p "$WORKSPACE_DIR"

# Check if worktree already exists
if [[ -d "$WORKSPACE_DIR/.git" ]]; then
    echo "[create_worktree] worktree already exists at $WORKSPACE_DIR"
    exit 0
fi

cd "$CANONICAL_REPO"

# Allow git access
git config --global --add safe.directory "*"
git config --global --add safe.directory "$WORKSPACE_DIR"
git fetch --all --prune 2>&1 || true

# Create worktree from master branch with new branch
git worktree add \
    "$WORKSPACE_DIR" \
    -b "$BRANCH_NAME" \
    origin/master 2>&1 || {
    git worktree add \
        "$WORKSPACE_DIR" \
        -b "$BRANCH_NAME" \
        master 2>&1
}

echo "[create_worktree] success"
echo "WORKSPACE_DIR=$WORKSPACE_DIR"
echo "BRANCH_NAME=$BRANCH_NAME"