#!/usr/bin/env bash
# merge_approved_system_patch — merge approved patch into canonical repo
# Args: WORKSPACE_DIR=<path> PROPOSAL_ID=<proposal_id> BRANCH_NAME=<branch>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
PROPOSAL_ID="${PROPOSAL_ID:-unknown}"
BRANCH_NAME="${BRANCH_NAME:-}"
REPO_PATH="${REPO_PATH:-/repo}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ -z "$BRANCH_NAME" ]]; then
    echo "ERROR: BRANCH_NAME is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "ERROR: worktree directory does not exist: $WORKSPACE_DIR" >&2
    exit 1
fi

CANONICAL_REPO="$REPO_PATH"
cd "$CANONICAL_REPO"

echo "[merge] merging $BRANCH_NAME into master for proposal $PROPOSAL_ID"

# Allow git access to the repo dir (host-mounted, owned by host uid)
git config --global --add safe.directory "*"
git config --global --add safe.directory "$WORKSPACE_DIR"

# Fetch the worktree branch
git fetch "$WORKSPACE_DIR" "$BRANCH_NAME" 2>&1 || true

# Checkout master
git checkout master 2>&1

# Merge --squash the worktree branch
git merge --squash "$BRANCH_NAME" 2>&1 || {
    echo "WARNING: merge conflict detected" >&2
    exit 1
}

# Create commit with proposal reference
git commit -m "Apply approved system evolution proposal $PROPOSAL_ID" 2>&1

echo "[merge] success: committed to master"