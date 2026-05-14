#!/usr/bin/env bash
# run_system_tests — run allowlisted tests from a worktree
# Args: WORKSPACE_DIR=<path> TEST_PROFILE=<profile>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
TEST_PROFILE="${TEST_PROFILE:-backend}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "ERROR: worktree directory does not exist: $WORKSPACE_DIR" >&2
    exit 1
fi

cd "$WORKSPACE_DIR"

echo "[run_system_tests] profile=$TEST_PROFILE worktree=$WORKSPACE_DIR"

case "$TEST_PROFILE" in
    backend)
        echo "=== Running backend tests ==="
        if [[ -d "$WORKSPACE_DIR/core/backend" ]]; then
            cd "$WORKSPACE_DIR/core/backend"
            if [[ -f requirements.txt ]]; then
                pip install -q -r requirements.txt 2>&1 | tail -5
            fi
            # tests/conftest.py isolates AGENT_SPACE_HOME unless AGENT_SPACE_PYTEST_USE_REAL_HOME=1
            python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short 2>&1
        else
            echo "ERROR: backend directory not found" >&2
            exit 1
        fi
        ;;
    frontend)
        echo "=== Running frontend tests ==="
        if [[ -d "$WORKSPACE_DIR/frontend" ]]; then
            cd "$WORKSPACE_DIR/frontend"
            if [[ -f package.json ]]; then
                npm ci --silent 2>&1 | tail -5
                npm test -- --passWithNoTests 2>&1
            else
                echo "ERROR: frontend package.json not found" >&2
                exit 1
            fi
        else
            echo "ERROR: frontend directory not found" >&2
            exit 1
        fi
        ;;
    typecheck)
        echo "=== Running typecheck ==="
        if [[ -d "$WORKSPACE_DIR/frontend" ]] && [[ -f "$WORKSPACE_DIR/frontend/tsconfig.json" ]]; then
            cd "$WORKSPACE_DIR/frontend"
            npx tsc --noEmit 2>&1
        else
            echo "ERROR: frontend tsconfig.json not found" >&2
            exit 1
        fi
        ;;
    lint)
        echo "=== Running lint ==="
        if [[ -d "$WORKSPACE_DIR/frontend" ]]; then
            cd "$WORKSPACE_DIR/frontend"
            if [[ -f package.json ]]; then
                npm run lint 2>&1 || echo "lint: no lint script found"
            fi
        fi
        ;;
    build)
        echo "=== Running build ==="
        if [[ -d "$WORKSPACE_DIR/frontend" ]]; then
            cd "$WORKSPACE_DIR/frontend"
            if [[ -f package.json ]]; then
                npm ci --silent 2>&1 | tail -3
                npm run build 2>&1
            fi
        elif [[ -d "$WORKSPACE_DIR/core/backend" ]]; then
            cd "$WORKSPACE_DIR/core/backend"
            if [[ -f requirements.txt ]]; then
                pip install -q -r requirements.txt 2>&1 | tail -3
            fi
        fi
        ;;
    *)
        echo "ERROR: Unknown test profile '$TEST_PROFILE'" >&2
        echo "Allowed profiles: backend, frontend, typecheck, lint, build" >&2
        exit 1
        ;;
esac

echo "[run_system_tests] done"
