#!/usr/bin/env bash
# backup.sh — FALLBACK / OPERATOR EMERGENCY TOOL.
#
# The primary backup mechanism is BackupService (core/backend/app/backups/service.py),
# started automatically by the backend when BACKUP_ENABLED=true. Use that for
# two-person dogfooding — it runs on schedule, runs once on startup, writes
# backup_manifest.json, and prunes old archives automatically.
#
# Use this script only when:
#   - The backend is not running and you need an emergency offline backup.
#   - You are performing a manual operator action outside normal operations.
#   - You want to verify the data root contents independently.
#
# Archives are written to AGENT_SPACE_HOME/<mode>/backups/ by default — the same
# directory used by BackupService. Use --output to override.
#
# Creates a timestamped tar archive of all runtime data under AGENT_SPACE_HOME/<mode>/.
# Does NOT dump secrets to stdout. Does NOT include repo source code.
# Does NOT overwrite an existing backup unless --force is given.
# Does NOT write backup_manifest.json (use the backend service for manifested backups).
#
# Usage:
#   ./scripts/backup.sh [--mode dev|test|prod] [--output DIR] [--dry-run] [--force] [--include-logs]
#
# Backup contents:
#   db/         — SQLite database (memory, proposals, runs, artifacts, activity, policies)
#   storage/    — artifact storage files
#   artifacts/  — artifact storage root (may overlap storage/ depending on config)
#   config/     — runtime configuration (no secret values)
#   secrets/    — secrets directory (encrypted key files only, not printed to stdout)
#   workspaces/ — workspace metadata directories
#   backups/    — excluded (recursion prevention)
#   sandboxes/  — excluded (ephemeral)
#   logs/       — optional; excluded by default unless --include-logs
#
# Consistency note:
#   SQLite WAL mode: a running backend may hold a WAL file. For maximum consistency,
#   stop writes before backup: docker compose stop backend.
#   A hot backup of SQLite is safe for read-only inspection but may miss the last
#   in-flight transaction if the WAL has not been checkpointed.
#
# See docs/BACKUP_AND_RESTORE.md for restore instructions.

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
MODE="dev"
OUTPUT_DIR=""          # resolved below after DATA_ROOT is known
DRY_RUN=false
FORCE=false
INCLUDE_LOGS=false

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)      MODE="$2"; shift 2 ;;
        --output)    OUTPUT_DIR="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --force)     FORCE=true; shift ;;
        --include-logs) INCLUDE_LOGS=true; shift ;;
        -h|--help)
            sed -n '/^# /p' "$0" | sed 's/^# \{0,2\}//'
            exit 0 ;;
        *) echo "[backup] Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Resolve paths ────────────────────────────────────────────────────────────
ASPACE_PARENT="${AGENT_SPACE_HOME:-${HOME}/aspace}"
DATA_ROOT="${ASPACE_PARENT}/${MODE}"

if [[ ! -d "$DATA_ROOT" ]]; then
    echo "[backup] ERROR: data root not found: $DATA_ROOT" >&2
    echo "[backup] Set AGENT_SPACE_HOME or use --mode to select a valid mode." >&2
    exit 1
fi

# Default output is the same backups/ directory used by BackupService.
# Override with --output or BACKUP_OUTPUT_DIR.
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="${BACKUP_OUTPUT_DIR:-${DATA_ROOT}/backups}"
fi

TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
ARCHIVE_NAME="fallback-${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"

echo "[backup] mode:      $MODE"
echo "[backup] data_root: $DATA_ROOT"
echo "[backup] output:    $ARCHIVE_PATH"
echo "[backup] dry_run:   $DRY_RUN"
echo "[backup] include_logs: $INCLUDE_LOGS"

# ── Safety: do not overwrite existing backup ─────────────────────────────────
if [[ -e "$ARCHIVE_PATH" ]] && [[ "$FORCE" != "true" ]]; then
    echo "[backup] ERROR: backup file already exists: $ARCHIVE_PATH" >&2
    echo "[backup] Use --force to overwrite." >&2
    exit 1
fi

# ── Build include/exclude list ────────────────────────────────────────────────
INCLUDE_DIRS=()
for d in db storage artifacts config secrets workspaces; do
    if [[ -d "${DATA_ROOT}/${d}" ]]; then
        INCLUDE_DIRS+=("${d}")
    fi
done

if [[ "$INCLUDE_LOGS" == "true" ]]; then
    if [[ -d "${DATA_ROOT}/logs" ]]; then
        INCLUDE_DIRS+=("logs")
        echo "[backup] including logs/ (--include-logs)"
    fi
else
    echo "[backup] skipping logs/ (use --include-logs to include)"
fi

echo "[backup] directories to archive: ${INCLUDE_DIRS[*]}"

# ── Dry-run mode ─────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[backup] DRY RUN — no archive created."
    echo "[backup] Would archive from: $DATA_ROOT"
    echo "[backup] Would write to:     $ARCHIVE_PATH"
    for d in "${INCLUDE_DIRS[@]}"; do
        echo "[backup]   + ${d}/"
    done
    exit 0
fi

# ── Create output directory ───────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR"

# ── Create archive ────────────────────────────────────────────────────────────
echo "[backup] creating archive..."
tar -czf "$ARCHIVE_PATH" -C "$DATA_ROOT" "${INCLUDE_DIRS[@]}" 2>&1 | grep -v "^$" || true
chmod 600 "$ARCHIVE_PATH"

ARCHIVE_SIZE=$(du -sh "$ARCHIVE_PATH" | cut -f1)
echo "[backup] done: $ARCHIVE_PATH ($ARCHIVE_SIZE)"
echo "[backup] to restore, see: docs/BACKUP_AND_RESTORE.md"
