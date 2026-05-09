#!/usr/bin/env bash
# Health check — returns 0 if backend is up, 1 otherwise
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

if curl -sf "$BACKEND_URL/health" > /dev/null 2>&1; then
    echo "backend: ok ($BACKEND_URL/health)"
    exit 0
else
    echo "backend: DOWN ($BACKEND_URL/health)" >&2
    exit 1
fi
