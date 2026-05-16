#!/usr/bin/env bash
# restore.sh — Restore a local agent-space backup.
#
# Extracts a backup archive into a clean AGENT_SPACE_HOME/<mode>/ directory.
# Will NOT overwrite an existing live data root unless --force is given.
# Does NOT print secret values. Does NOT start the application.
#
# Usage:
#   ./scripts/restore.sh <backup-archive.tar.gz> [--mode dev|test|prod] [--force]
#
# After restore, verify with the checklist in docs/BACKUP_AND_RESTORE.md:
#   1. App starts and /health returns 200.
#   2. Spaces and users are visible via API.
#   3. Memory entries are readable.
#   4. Artifacts are readable and exportable.
#   5. Proposals and runs are inspectable.
#   6. Activity inbox entries are present.
#   7. RunStep rows are present for backed-up runs.
#
# IMPORTANT: Stop any running backend before restoring to avoid DB conflicts.
#   docker compose -f deployments/local/docker-compose.yml stop backend frontend

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
MODE="dev"
FORCE=false
ARCHIVE=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)  MODE="$2"; shift 2 ;;
        --force) FORCE=true; shift ;;
        -h|--help)
            sed -n '/^# /p' "$0" | sed 's/^# \{0,2\}//'
            exit 0 ;;
        -*)
            echo "[restore] Unknown option: $1" >&2; exit 1 ;;
        *)
            if [[ -z "$ARCHIVE" ]]; then
                ARCHIVE="$1"
            else
                echo "[restore] Unexpected argument: $1" >&2; exit 1
            fi
            shift ;;
    esac
done

if [[ -z "$ARCHIVE" ]]; then
    echo "[restore] ERROR: no backup archive specified." >&2
    echo "[restore] Usage: $0 <backup-archive.tar.gz> [--mode dev|test|prod] [--force]" >&2
    exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
    echo "[restore] ERROR: archive not found: $ARCHIVE" >&2
    exit 1
fi

# Resolve to absolute path now — before any directory removal changes the CWD context
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

# ── Resolve target ────────────────────────────────────────────────────────────
ASPACE_PARENT="${AGENT_SPACE_HOME:-${HOME}/aspace}"
TARGET="${ASPACE_PARENT}/${MODE}"

echo "[restore] archive:  $ARCHIVE"
echo "[restore] mode:     $MODE"
echo "[restore] target:   $TARGET"
echo "[restore] force:    $FORCE"

# ── Safety: do not overwrite existing live data root ─────────────────────────
if [[ -d "$TARGET" ]] && [[ "$FORCE" != "true" ]]; then
    echo "[restore] ERROR: target data root already exists: $TARGET" >&2
    echo "[restore] Stop the running instance and use --force to overwrite." >&2
    echo "[restore] WARNING: --force will overwrite all current data in this mode." >&2
    exit 1
fi

# ── Verify archive integrity before extracting ───────────────────────────────
echo "[restore] verifying archive integrity..."
if ! tar -tzf "$ARCHIVE" > /dev/null 2>&1; then
    echo "[restore] ERROR: archive failed integrity check: $ARCHIVE" >&2
    exit 1
fi
echo "[restore] archive OK"

# ── Create and populate target ────────────────────────────────────────────────
if [[ "$FORCE" == "true" ]] && [[ -d "$TARGET" ]]; then
    # Remove only the data directories the backup captures.
    # backups/ is intentionally kept: it may contain the archive being restored,
    # and losing it would make rollback impossible.
    echo "[restore] --force: clearing data directories in $TARGET (backups/ preserved)"
    for d in db storage artifacts config secrets workspaces sandboxes cache logs; do
        if [[ -d "${TARGET}/${d}" ]]; then
            echo "[restore]   removing ${TARGET}/${d}"
            rm -rf "${TARGET:?}/${d}"
        fi
    done
fi

mkdir -p "$TARGET"
chmod 700 "$TARGET"

echo "[restore] extracting archive to $TARGET ..."
tar -xzf "$ARCHIVE" -C "$TARGET"

echo "[restore] setting permissions on sensitive directories..."
for d in db secrets config; do
    if [[ -d "${TARGET}/${d}" ]]; then
        chmod 700 "${TARGET}/${d}"
    fi
done

echo "[restore] restore complete: $TARGET"
echo ""
echo "[restore] NEXT STEPS — verify restore per docs/BACKUP_AND_RESTORE.md:"
echo "  1. Start the app: ./scripts/start.sh --${MODE}"
echo "  2. Check health:  curl http://localhost:8000/health"
echo "  3. List spaces:   curl http://localhost:8000/api/v1/spaces"
echo "  4. List memory:   curl http://localhost:8000/api/v1/memory"
echo "  5. List artifacts: curl http://localhost:8000/api/v1/artifacts"
echo "  6. List runs:     curl http://localhost:8000/api/v1/runs"
echo "  7. List activity: curl http://localhost:8000/api/v1/activity"
