# Two-Person Dogfooding Release Candidate Runbook

**RC declared:** 2026-05-16
**Scope:** Local two-person dogfooding only.

---

## A. RC Purpose

This runbook describes the release-candidate boundary for two-person local dogfooding of
Agent-Space. The system's foundation — space isolation, actor identity, run replay, runtime
and credential boundaries, policy enforcement, activity provenance, backup/restore, and
deployment control — is hardened and tested.

**What this is:**

- Local two-person dogfooding on a single host instance.
- A gate that is honest about allowed and disabled surfaces.

**What this is not:**

- Public launch.
- SaaS or remote multi-tenant deployment.
- A test of all future ambitions (Automation, Connectors, Information Horizon,
  self-evolution, marketplace, mobile client).

**Rule:** Only allowed surfaces may be used for daily dogfood workflows. Disabled surfaces
must not be relied on. If a disabled surface is required for normal use, dogfooding must
stop and the surface must be gated before resuming.

---

## B. Allowed Surfaces

The following surfaces are allowed after all release gates pass:

**Spaces and users**
- Personal spaces (`personal` space type).
- Household shared space (`household` space type).
- Explicit two-user membership and space switching.
- Auth via session cookies or API keys. No dev identity fallback.

**Activity**
- Activity Inbox for non-chat capture: thoughts, notes, snippets, links.
- All non-chat capture enters Activity first via `POST /api/v1/activity`.
- Explicit chat sessions only for real conversations with agents (`POST /api/v1/sessions`).

**Memory**
- Memory proposal creation, review, acceptance, rejection, and archive.
- Memory read and search with ACL, provenance, and proposal-first boundaries.
- Archived memory excluded from active reads.
- Memory consolidation producing proposals from Activity.

**Runs and execution**
- Runs through canonical `app.runtimes` path only.
- RunStep replay and failure diagnosis via `GET /api/v1/runs/{id}/steps`.
- Artifacts produced by runs; safe export within owned space.

**Proposals**
- Proposals linked to runs, tasks, artifacts, and memory where supported.
- `code_patch` proposals via approved-proposal-only apply path.

**Tasks and boards**
- Task boards and task-linked runs/artifacts/proposals.

**Home and status**
- Home summary as read-only command center.
- Provider/runtime status where secrets are redacted.

**Backup and restore**
- Automatic local backups through `BackupService` (primary — `BACKUP_ENABLED=true` required).
- Manual backup via `POST /api/v1/system/backups/manual` or `scripts/backup.sh` (fallback only).
- Manual restore through `scripts/restore.sh` or documented restore procedure.
- Restore is always manual and explicit.

**Deployment**
- Manual deployment or allowlisted deployer-only flow.
- No arbitrary shell commands through the deployer.

---

## C. Disabled Surfaces

The following surfaces are disabled, 501-gated, feature-gated, or not trusted for RC.
Do not rely on any of these for daily dogfood workflows.

| Surface | Status |
|---|---|
| Broad Information Horizon ingestion | Not implemented |
| External chat/media/file import pipelines | Not implemented |
| Web crawler | Not implemented |
| Vector index over external corpus | Not implemented |
| Automation/Trigger engine | Not implemented |
| Connectors/Integrations platform | Not implemented |
| Full Source/Evidence schema and ingestion | Deferred (field mapping only) |
| Full capability marketplace or install/discovery UX | Not implemented |
| Self-evolution behavior changes | Disabled (`ENABLE_SYSTEM_EVOLUTION=false`) |
| Self-evolution execution | Disabled by default |
| App-container self-deployment | Blocked by deployer allowlist |
| Deployment job persistence | 501-gated (`POST /deployments/jobs` → 501) |
| Arbitrary deployer commands | Blocked; only allowlisted `CoreJobType` + `SelfEvolutionJobType` |
| Automatic restore | Not implemented; restore is always manual |
| Cloud/offsite backup sync | Not implemented |
| Multi-device conflict resolution | Not implemented |
| Public sharing | Not implemented |
| Public launch / SaaS | Not in scope |
| Remote multi-tenant deployment | Not in scope |
| API key persistence UI | Feature-gated if not yet implemented |
| Workspace console persisted sessions | Feature-gated if not yet implemented |
| Any runtime adapter bypassing the credential resolver | Blocked by `RunExecutionService` design |
| Any runtime adapter bypassing sandbox/path policy | Blocked by `execution_workspace` contract |
| File mutation not protected by approved proposal + PathPolicy | Blocked by code patch apply boundary |

**UI status of planned-but-not-built surfaces:**

- `LLM Wiki` — registry entry with `planned: true`; displays "soon" badge; non-interactive.
- `Cards` — registry entry with `planned: true`; displays "soon" badge; non-interactive.
- `Time` — registry entry with `planned: true`; displays "soon" badge; non-interactive.

No automation, connector, horizon, or self-evolution controls appear in the frontend.

---

## D. RC Config Requirements

The following config must be set in `~/aspace/<mode>/.env` before dogfooding begins.

### Required backup config

```env
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=7
BACKUP_INCLUDE_LOGS=false
BACKUP_ON_STARTUP=true
```

`BACKUP_ENABLED=true` is the minimum required setting. Without it, no automatic backups
are created and dogfood data is unprotected.

`BACKUP_ON_STARTUP=true` is the default. It causes `BackupScheduler` to run one backup
immediately on startup, so you can verify the service is working before any writes occur.
Leave it at the default for dogfooding.

`BACKUP_ROOT` defaults to `AGENT_SPACE_HOME/backups/`. Override only if you need a
non-standard location.

### Required safety config

```env
ENABLE_SYSTEM_EVOLUTION=false   # default; do not change for dogfooding
```

`SYSTEM_CORE_OWNER_EMAIL` must be left unset or empty unless you intend to register a
system_core workspace.

### Auth config

```env
DEBUG=false   # prevents dev API key auto-seed
```

All authenticated calls require a real session cookie or API key. No dev-identity fallback exists.

### Runtime

```env
DEFAULT_SPACE_ID=personal
DEFAULT_USER_ID=default_user
```

These bootstrap defaults are used only for single-user personal mode initialization.
Multi-user dogfooding requires each user to authenticate with their own credentials.

### Where config lives

- Host: `~/aspace/<mode>/.env` (never stored in the repo).
- In Docker: mounted at `/aspace/.env` through the Compose volume.
- See `deployments/local/docker-compose.dev.yml` for volume mapping.

### Where runtime data lives

```
AGENT_SPACE_HOME/          (default: ~/aspace/dev/)
  db/                      SQLite database (all spaces, memory, proposals, runs, etc.)
  storage/                 Artifact storage files
  secrets/                 Encrypted provider key files
  config/                  Runtime configuration
  workspaces/              Workspace metadata
  backups/                 Backup archives (auto-pruned to BACKUP_RETENTION_COUNT)
  logs/                    Application logs (optional; BACKUP_INCLUDE_LOGS=false by default)
```

Backups are stored at `AGENT_SPACE_HOME/backups/` by default. Archives contain `db/`,
`storage/`, `secrets/`, `config/`, and `workspaces/`. Logs optional. `backups/` and
`sandboxes/` are always excluded from backup archives.

### Allowed runtime adapters for RC

- `echo` — zero-dependency test adapter; no credentials required.
- `anthropic_messages` — Messages API adapter; credentials resolved through `ModelProvider`
  encrypted key via `runtimes/credentials.py`.

No adapter may read `ANTHROPIC_API_KEY` from the environment directly. All credentials
must be resolved through `runtimes/credentials.py`.

### Deployment posture

- `POST /deployments/jobs` returns 501. Deployment job persistence is absent.
- Deployer `ALLOWED_JOB_TYPES` covers `CoreJobType` (`rebuild_agent_space`,
  `restart_agent_space`, `health_check`) and `SelfEvolutionJobType`. No arbitrary shell.
- `ENABLE_SYSTEM_EVOLUTION=false` disables self-evolution by default.

---

## E. Test Commands

Run all of these before declaring RC ready.

### Full backend suite

```bash
cd core/backend
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -q --tb=short
```

Expected: 640 passed, 0 failed.

### Frontend typecheck

```bash
cd frontend
npx tsc --noEmit
```

Expected: no output (no errors).

### Frontend build

```bash
cd frontend
npm run build
```

Expected: clean build with no TypeScript or bundler errors.

### Script syntax check

```bash
bash -n scripts/backup.sh scripts/restore.sh
```

Expected: no output (no syntax errors).

### Optional: shellcheck

```bash
shellcheck scripts/backup.sh scripts/restore.sh
```

### Focused test groups by boundary

```bash
cd core/backend

# Space contracts, auth, two-user isolation
python3 -m pytest \
  tests/contracts/test_space_contract.py \
  tests/invariants/test_space_isolation.py \
  tests/contracts/test_memory_api.py \
  tests/contracts/test_workspace_api.py \
  tests/contracts/test_activity_api.py \
  -v

# Actor identity
python3 -m pytest \
  tests/unit/test_actor_ref.py \
  tests/unit/test_actor_service.py \
  tests/invariants/test_actor_identity.py \
  -v

# RunStep replay and failure diagnosis
python3 -m pytest \
  tests/unit/test_run_step_taxonomy.py \
  tests/workflows/test_run_step_workflow.py \
  tests/workflows/test_runtime_failure_workflow.py \
  tests/contracts/test_run_steps_api.py \
  tests/invariants/test_run_step_invariants.py \
  tests/invariants/test_run_auditability.py \
  -v

# Runtime credential, sandbox, redaction
python3 -m pytest \
  tests/unit/test_runtime_credentials.py \
  tests/unit/test_redaction.py \
  tests/unit/test_runtime_policy.py \
  tests/unit/test_path_policy.py \
  tests/invariants/test_runtime_credential_sandbox_boundary.py \
  tests/invariants/test_runtime_provider_separation.py \
  -v

# Persisted policy enforcement
python3 -m pytest \
  tests/unit/test_policy_engine.py \
  tests/invariants/test_memory_write_invariants.py \
  tests/contracts/test_memory_write_governance.py \
  -v

# Activity-first capture and provenance
python3 -m pytest \
  tests/contracts/test_activity_capture_contract.py \
  tests/invariants/test_activity_source_boundary.py \
  tests/workflows/test_activity_to_memory_workflow.py \
  tests/workflows/test_activity_to_memory_provenance.py \
  -v

# Lifecycle and deployment boundary
python3 -m pytest \
  tests/invariants/test_lifecycle_deployment_boundary.py \
  tests/unit/test_deployer_protocol.py \
  -v

# Backup service
python3 -m pytest tests/unit/test_backup_service.py -v

# DB transaction boundary
python3 -m pytest \
  tests/unit/test_job_transaction_boundary.py \
  tests/invariants/test_run_step_invariants.py \
  tests/invariants/test_memory_proposal_boundary.py \
  -v
```

---

## F. Two-User Smoke Test

This is a manual test. Run it before first dogfood writes.

**Prerequisites:** Backend and frontend running with dogfood config. `BACKUP_ENABLED=true`.

### Step 1 — Startup and backup verification

```bash
./scripts/start.sh
# Wait for backend to start, then:
curl -s http://localhost:8000/health
# Expected: {"status": "ok", ...}
```

Verify BackupService is active in startup logs:
```
INFO  backup scheduler started, interval=24h
```

Or trigger a manual backup and confirm:
```bash
curl -s -X POST http://localhost:8000/api/v1/system/backups/manual \
  -H "X-API-Key: <dogfood-api-key>"
# Expected: {"status": "ok", "backup": "manual-YYYYMMDD-HHMMSS.tar.gz"}

curl -s http://localhost:8000/api/v1/system/backups \
  -H "X-API-Key: <dogfood-api-key>"
# Expected: list with at least one archive containing backup_manifest.json
```

Inspect the manifest:
```bash
tar -xOf ~/aspace/dev/backups/manual-*.tar.gz backup_manifest.json | python3 -m json.tool
# Expected: backup_format="agent-space-backup.v1", included_paths lists db/ etc.
```

### Step 2 — User setup

Create or confirm two users with distinct credentials:
- **User A** — personal space `personal`, user ID `user_a` (or registered email).
- **User B** — personal space `personal`, user ID `user_b` (or registered email).
- Confirm a `household` space exists with both as members.

```bash
# As User A: list spaces
curl -s "http://localhost:8000/api/v1/spaces" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: personal space for User A

# As User B: list spaces
curl -s "http://localhost:8000/api/v1/spaces" \
  -H "X-API-Key: <user-b-api-key>"
# Expected: personal space for User B

# As either user: confirm household space membership
curl -s "http://localhost:8000/api/v1/spaces?space_type=household" \
  -H "X-API-Key: <user-a-api-key>"
```

### Step 3 — Private space isolation

```bash
# User B attempts to access User A's personal space — must be 403
curl -s "http://localhost:8000/api/v1/memory?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-b-api-key>"
# Expected: HTTP 403

# User A attempts to access User B's personal space — must be 403
curl -s "http://localhost:8000/api/v1/memory?space_id=<user-b-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: HTTP 403
```

### Step 4 — Shared space access

```bash
# Both users can read household space memory
curl -s "http://localhost:8000/api/v1/memory?space_id=<household-space-id>&status=active" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: 200 (may be empty list)

curl -s "http://localhost:8000/api/v1/memory?space_id=<household-space-id>&status=active" \
  -H "X-API-Key: <user-b-api-key>"
# Expected: 200 (same list)
```

### Step 5 — Non-chat capture and Activity Inbox

```bash
# User A captures a thought — must create ActivityRecord, not Session
curl -s -X POST "http://localhost:8000/api/v1/activity" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"space_id": "<user-a-personal-space-id>", "content": "Test thought for RC smoke test", "source_type": "user_capture", "activity_type": "capture"}'
# Expected: 201 with ActivityRecord id

# Confirm it appears in Activity Inbox
curl -s "http://localhost:8000/api/v1/activity?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: list including the new ActivityRecord
```

### Step 6 — Memory proposal from Activity

Trigger consolidation or create a proposal manually:
```bash
# Consolidate activity into proposal
curl -s -X POST "http://localhost:8000/api/v1/activity/consolidate" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"space_id": "<user-a-personal-space-id>"}'

# Check proposals
curl -s "http://localhost:8000/api/v1/proposals?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: at least one proposal with provenance_entries referencing the ActivityRecord
```

### Step 7 — Proposal accept and provenance

```bash
# Accept the proposal
curl -s -X POST "http://localhost:8000/api/v1/proposals/<proposal-id>/accept" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"space_id": "<user-a-personal-space-id>"}'
# Expected: 200 with resulting_memory_id

# Confirm MemoryEntry has source_activity_id set
curl -s "http://localhost:8000/api/v1/memory/<memory-id>?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: source_activity_id not null; source_trust present
```

### Step 8 — Memory archive

```bash
# Archive the memory (must return proposal, not direct delete)
curl -s -X DELETE "http://localhost:8000/api/v1/memory/<memory-id>?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: 202 with memory_archive proposal

# Accept archive proposal
curl -s -X POST "http://localhost:8000/api/v1/proposals/<archive-proposal-id>/accept" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"space_id": "<user-a-personal-space-id>"}'

# Confirm archived memory is excluded from active reads
curl -s "http://localhost:8000/api/v1/memory?space_id=<user-a-personal-space-id>&status=active" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: archived entry not in list
```

### Step 9 — Run and RunStep replay

```bash
# Create a run (echo adapter — no credentials required)
curl -s -X POST "http://localhost:8000/api/v1/runs" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"space_id": "<user-a-personal-space-id>", "adapter_type": "echo", "input": "smoke test"}'
# Note run_id

# Check RunSteps (may need to wait for run to complete)
curl -s "http://localhost:8000/api/v1/runs/<run-id>/steps?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: ordered list of RunStep records
```

### Step 10 — Artifact export

```bash
# List artifacts for the run
curl -s "http://localhost:8000/api/v1/artifacts?space_id=<user-a-personal-space-id>&run_id=<run-id>" \
  -H "X-API-Key: <user-a-api-key>"

# Export artifact inline
curl -s "http://localhost:8000/api/v1/artifacts/<artifact-id>/export?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: artifact content

# Cross-space export must fail
curl -s "http://localhost:8000/api/v1/artifacts/<artifact-id>/export?space_id=<user-b-personal-space-id>" \
  -H "X-API-Key: <user-b-api-key>"
# Expected: 404
```

### Step 11 — Home summary

```bash
curl -s "http://localhost:8000/api/v1/home/summary?space_id=<user-a-personal-space-id>" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: 200 with read-only summary object
```

### Step 12 — Disabled surfaces check

```bash
# Deployment jobs must be 501
curl -s -X POST "http://localhost:8000/api/v1/deployments/jobs" \
  -H "X-API-Key: <user-a-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "arbitrary", "target": "local"}'
# Expected: 501

# Deployment jobs list must be empty
curl -s "http://localhost:8000/api/v1/deployments/jobs" \
  -H "X-API-Key: <user-a-api-key>"
# Expected: []
```

In the frontend:
- Navigate to all gallery cards; confirm no automation, connector, horizon, or
  self-evolution controls are visible.
- Wiki, Cards, and Time cards show "soon" badge and are non-interactive.

---

## G. Backup and Restore Rehearsal

Run this before first write session and periodically during dogfooding.

### Verify automatic backup is configured

```bash
grep BACKUP_ENABLED ~/aspace/dev/.env
# Expected: BACKUP_ENABLED=true

# Check backend startup logs for scheduler confirmation
grep "backup scheduler" ~/aspace/dev/logs/backend.log
# Expected: "backup scheduler started"
```

### Trigger a manual backup (primary: API; fallback: shell script)

**API (backend running):**
```bash
curl -s -X POST http://localhost:8000/api/v1/system/backups/manual \
  -H "X-API-Key: <dogfood-api-key>"
# Expected: {"status": "ok", "backup": "manual-YYYYMMDD-HHMMSS.tar.gz"}
```

**Shell script fallback (backend not running):**
```bash
./scripts/backup.sh --mode dev
# Archives to ~/aspace/dev/backups/fallback-<timestamp>.tar.gz (same dir as BackupService)
# Note: shell script does NOT write backup_manifest.json
```

### List backup archives

```bash
curl -s http://localhost:8000/api/v1/system/backups \
  -H "X-API-Key: <dogfood-api-key>"
# Expected: JSON list of archives with name, size, created_at

# Or list on filesystem
ls -lh ~/aspace/dev/backups/
```

### Inspect backup_manifest.json

```bash
ARCHIVE=$(ls ~/aspace/dev/backups/auto-*.tar.gz | tail -1)
tar -xOf "$ARCHIVE" backup_manifest.json | python3 -m json.tool
```

Expected fields in manifest:
- `backup_format: "agent-space-backup.v1"`
- `kind: "auto"` or `"manual"`
- `created_at` — ISO timestamp
- `source_root` — absolute path of data root at backup time
- `included_paths` — list: `db/`, `storage/`, `secrets/`, `config/`, `workspaces/`
- `excluded_paths` — `backups/`, `sandboxes/`, `cache/` with reason
- `db_snapshot_method: "sqlite-backup-api"`
- `warnings` — empty list for clean backup

### Restore into a clean target root

**Stop the instance first:**
```bash
docker compose -f deployments/local/docker-compose.dev.yml stop
```

**Restore:**
```bash
ARCHIVE=~/aspace/dev/backups/auto-<timestamp>.tar.gz

# Restore to clean location (preferred for rehearsal)
./scripts/restore.sh "$ARCHIVE" --mode dev-restored

# If overwriting existing root (requires --force):
./scripts/restore.sh "$ARCHIVE" --mode dev --force
```

`--force` removes the existing data root before extracting. All current data is replaced.

### Verify restored app starts

```bash
AGENT_SPACE_HOME=~/aspace/dev-restored ./scripts/start.sh
curl -s http://localhost:8000/health
# Expected: {"status": "ok", ...}
```

### Verify key data survives restore

```bash
BASE="http://localhost:8000/api/v1"
KEY="X-API-Key: <dogfood-api-key>"
SPACE="<space-id>"

# Spaces
curl -s "$BASE/spaces" -H "$KEY"

# Memory
curl -s "$BASE/memory?space_id=$SPACE&status=active" -H "$KEY"

# Artifacts
curl -s "$BASE/artifacts?space_id=$SPACE" -H "$KEY"

# Proposals
curl -s "$BASE/proposals?space_id=$SPACE" -H "$KEY"

# Runs
curl -s "$BASE/runs?space_id=$SPACE" -H "$KEY"

# RunSteps (use a known run_id from above)
curl -s "$BASE/runs/<run-id>/steps?space_id=$SPACE" -H "$KEY"

# Activity
curl -s "$BASE/activity?space_id=$SPACE" -H "$KEY"
```

All expected: 200 with data matching pre-restore state.

**Restore is always manual and explicit. There is no automatic restore.**

---

## H. Rollback Plan

Use this procedure when a stop condition triggers or a serious incident occurs.

### Step 1 — Stop writes immediately

Prevent new writes from entering the database:
```bash
docker compose -f deployments/local/docker-compose.dev.yml stop backend worker
```

Do not stop the frontend yet — it will naturally lose backend connectivity.

### Step 2 — Stop all services

```bash
docker compose -f deployments/local/docker-compose.dev.yml stop
```

### Step 3 — Snapshot current state

Before overwriting anything, copy the current data root:
```bash
cp -a ~/aspace/dev ~/aspace/dev-pre-rollback-$(date +%Y%m%d-%H%M%S)
```

This preserves the failing state for incident analysis.

### Step 4 — Identify previous known-good revision

```bash
git log --oneline -10
# Identify the commit hash before the problem was introduced
```

### Step 5 — Revert app revision

```bash
git checkout <known-good-commit>
# Or if rolling back a branch:
git reset --hard <known-good-commit>
```

### Step 6 — Restore from last known-good backup (if data integrity suspect)

```bash
ARCHIVE=$(ls ~/aspace/dev/backups/auto-*.tar.gz | sort | tail -2 | head -1)
./scripts/restore.sh "$ARCHIVE" --mode dev --force
```

Use the backup immediately before the problem started, not the latest one (which may
already be corrupted).

### Step 7 — Disable implicated surface

Edit `~/aspace/dev/.env` to disable the problematic surface:
```bash
# Examples:
ENABLE_SYSTEM_EVOLUTION=false    # if self-evolution implicated
BACKUP_ENABLED=false             # temporarily if backup itself is problematic
```

Or comment out the module in `core/backend/app/modules/registry.py` if a specific
module is implicated.

### Step 8 — Record incident note

File an incident note immediately (see §J template) before resuming or discussing.

### Step 9 — Re-run the failed gate

```bash
cd core/backend
python3 -m pytest tests/<implicated-tests> -v
```

Do not resume dogfooding until the failing gate passes.

### Step 10 — Resume

```bash
./scripts/start.sh
```

Resume dogfooding only after the failed gate passes and the incident note is filed.

---

## I. Stop Conditions

**Dogfooding must stop immediately if any of the following occur:**

1. **Cross-user private-space data leak** — User B reads User A's personal space data
   without explicit household membership.

2. **Household membership access bypass** — A non-member user accesses household space
   data.

3. **Memory write bypasses proposal or active policy boundary** — A direct internal memory
   write succeeds without going through `create_from_approved_proposal` when an active
   `memory.write_direct` deny policy is in effect.

4. **Accepted policy does not affect enforcement** — An accepted, active `Policy` row
   with the selected class does not change the enforcement decision it was meant to govern.

5. **RunStep replay missing** — `GET /runs/{id}/steps` returns an empty list for a run
   that completed through the canonical `app.runtimes` path.

6. **Runtime secret in output** — A raw API key, secret, or credential appears in run
   output, RunStep metadata, artifact content, logs, or any UI surface.

7. **Backup fails repeatedly** — `BackupService` cannot complete a backup or produce
   `backup_manifest.json` after two consecutive automatic intervals.

8. **Restore rehearsal fails** — `scripts/restore.sh` fails, or the restored app fails
   to start, or key data is missing after restore.

9. **Workspace scan deletes metadata** — `POST /workspaces/scan` hard-deletes a
   workspace row instead of marking it `stale`.

10. **Deployer accepts arbitrary command** — The deployer accepts and executes a job type
    not in `ALLOWED_JOB_TYPES`.

11. **Self-evolution executes behavior changes** — Any self-evolution code path modifies
    production code or configuration without explicit approved proposal and deployer gate.

12. **Disabled surface required for daily use** — A disabled surface from §C becomes
    necessary for normal dogfood workflows (any disabled surface that must be enabled to
    continue productive use).

13. **Code patch partial apply** — `code_patch` proposal apply reports a partial-apply
    error (some files written, others failed, rollback failed) and the incident is not
    handled before continuing.

14. **Database transaction produces partial state** — An operation leaves partial active
    `MemoryEntry` or `Proposal` rows in an inconsistent state that cannot be traced to a
    clean rollback.

---

## J. Incident Note Template

File one note per incident. Save to `.agent/incidents/YYYYMMDD-<slug>.md`.

```markdown
## Incident: <short title>

Date/time: YYYY-MM-DD HH:MM UTC
User: <user identifier — not email>
Space: <space id and type>
Surface used: <module, API endpoint, or UI page>

### Expected behavior
<what should have happened>

### Actual behavior
<what actually happened — be specific>

### Data affected
<tables, IDs, or records involved; none if no data was mutated>

### Privacy impact
<none | potential | confirmed — describe if confirmed>

### Backup status
Last successful backup: <timestamp or "unknown">
Backup manifest inspected: <yes / no>

### Rollback performed
<yes / no — if yes, describe which backup was used>

### Boundary gate implicated
<space-isolation / actor-identity / run-step-replay / runtime-credential / policy-enforcement / activity-provenance / lifecycle-deployment / backup-service / db-transaction / unknown>

### Follow-up task
<link to task or describe concrete next action>

### Severity
<critical (stop condition triggered) / major (gate regressed) / minor (UX issue only)>
```

---

## Security Notes

- `secrets/provider_keys.key` is included in backup archives. Treat archives as
  sensitive. Archive permissions: `600` (owner only).
- No raw secret values are written to stdout, logs, or `backup_manifest.json`.
- For offsite storage: `gpg --symmetric <archive.tar.gz>` before transferring.

---

## Residual Risks

| Risk | Status |
|---|---|
| `Credential.secret_ref` full decryption deferred | Only `ModelProvider` encrypted keys decryptable; full secret_ref deferred |
| `app.agents` CLI adapter runtime path | CLI adapters only; new adapters must use `app.runtimes` |
| Most PolicyEngine enforcement points not yet wired to persisted policy | One class (`memory.write_direct`) is wired; rest documented in `PRODUCT_AND_BOUNDARIES.md` |
| Artifact archive/delete API not yet implemented | Artifacts accumulate; deferred |
| Activity archive/delete not yet implemented | Deferred |
| Workspace stale status has no recovery UI | Operator must use `PATCH /workspaces/{id}` |
| Deployment job persistence absent | 501-gated; manual deployment only |
| Local advisory lock only (single-host) | Distributed locking is future scope |
| Cloud/offsite backup absent | Manual GPG + offsite upload if required |
| `context_sources` table removed from schema | A future first-class Source model would be a new table |
| QuickCapture `ask` mode still routes to `/sessions` | Correct for real conversations; UX deferred |
| QuickCapture `process` mode creates new Activity | Acceptable; product refinement deferred |
| First-class Source/Evidence tables deferred | Pre-external-ingestion gate; not needed for dogfooding |
| `source_confidence` / `source_reliability` may be absent from canonical migration | Verify before depending on these fields |
