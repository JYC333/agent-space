#!/usr/bin/env bash
# collect_system_diff — collect git status/diff from a worktree
# Args: WORKSPACE_DIR=<path>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "ERROR: worktree directory does not exist: $WORKSPACE_DIR" >&2
    exit 1
fi

cd "$WORKSPACE_DIR"

echo "=== GIT STATUS ==="
git status --short

echo ""
echo "=== GIT DIFF ==="
git diff

echo ""
echo "=== CHANGED FILES ==="
git diff --name-only
