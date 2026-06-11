# Backup and Restore — agent-space Local Instance

**Scope:** Local two-person dogfooding instance. PostgreSQL is the server database.

---

## Model

There is one full-system backup concept and one full-system restore concept.

| Tool | Role |
|---|---|
| `BackupService` (`backend/app/backups/service.py`) | **Canonical full-system backup** — scheduled, on-startup, and via API. Produces a manifested archive. |
| `BackupScheduler` (`backend/app/backups/scheduler.py`) | Runs one backup tick for SchedulerRegistry and exposes manual/list API operations. |
| `ops/scripts/system/backup.sh` | App-services-stopped full-system backup — same archive format as `BackupService`, for when `frontend`, `control-plane`, `backend`, and `deployer` are stopped while postgres remains running. |
| `ops/scripts/system/restore.sh` | Full-system restore — restores **both** the database and file data from one archive. |
| `ops/scripts/db/dump.sh` | DB-only expert tool — `pg_dump` custom-format dump to `db/dumps/`. |
| `ops/scripts/db/restore.sh` | DB-only expert tool — `pg_restore` from a `.dump` file. |

A full-system backup archive contains a logical PostgreSQL snapshot **and** the file data, together with a manifest. Restore is a single command that rebuilds the database and the files.

**Two-person dogfooding must set `BACKUP_ENABLED=true`** (or `backup_enabled: true` in `.env`). The service defaults to `False` for test safety.

The local compose stack uses the bundled `postgres` service by default. Setting
`DATABASE_URL` in the mode `.env` points the backend at another PostgreSQL
connection, but the bundled `postgres` service remains defined in the local
compose files until a separate external-db compose profile is added.
Across dev, test, and prod the backend container listens on internal port `8000`,
but the default client-facing API entrypoint is `control-plane`. Dev publishes
control-plane at `http://localhost:8010`; test publishes it at
`http://localhost:8110`. Test mode maps host `localhost:8100` to backend
container `8000` for direct Python debugging only; the test frontend uses
control-plane.
The bundled PostgreSQL containers have stable names per mode:
`agent-space-dev-postgres`, `agent-space-test-postgres`, and `agent-space-prod-postgres`.

---

## Data locations

> **Path semantics.** `ASPACE_ROOT` is the host-side parent directory that holds the
> `dev/`, `test/`, `prod/` mode roots (default `~/.aspace`); the scripts locate a mode
> root as `$ASPACE_ROOT/<mode>`. Inside containers the running backend sees that mode
> root as `AGENT_SPACE_HOME=/aspace`. `AGENT_SPACE_HOME` is never the parent of the mode dirs.
> The DB/system scripts share `ops/scripts/lib/local-compose.sh` with `ops/scripts/start.sh`,
> so mode validation, `$MODE_ROOT/.env`, `AGENT_SPACE_MODE_ROOT`, compose project/file,
> and `docker compose --env-file "$ENV_FILE"` stay consistent.
> Docker-native `ops/scripts/db/migrate.sh`, DB-only `ops/scripts/db/{dump,restore,reset-postgres}.sh`,
> and offline `ops/scripts/system/{backup,restore,verify-restore}.sh` stop the compose
> `postgres` service after completion only if that script started it; they do not
> stop a database that was already running.

| Path | Meaning | In normal backups? |
|---|---|---|
| `$ASPACE_ROOT/<mode>/db/postgres` | Live PostgreSQL data directory (bind-mounted into the postgres container) | **No** — never archived. The database is captured logically via `pg_dump`. |
| `$ASPACE_ROOT/<mode>/db/dumps` | `pg_dump` custom-format dump files written by `ops/scripts/db/dump.sh` | Operator-managed; not part of the system archive |
| `storage/`, `artifacts/`, `config/`, `secrets/`, `workspaces/` | File data | Yes |
| `logs/` | Application logs | Optional (`BACKUP_INCLUDE_LOGS=true`) |
| `backups/`, `cache/`, `sandboxes/` | Archives / ephemeral | No |

---

## Automatic backup (canonical)

### Enable

In `$ASPACE_ROOT/<mode>/.env`:

```
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=7
BACKUP_INCLUDE_LOGS=false
BACKUP_ON_STARTUP=true
```

The backend reads these on startup, creates `BackupScheduler`, and registers its tick with `SchedulerRegistry`. `BACKUP_ON_STARTUP=true` triggers an immediate backup on first startup so you can verify the service is writing archives before any real writes occur.

### Archive contents

| Path in archive | Contents |
|---|---|
| `db/agent_space.dump` | PostgreSQL snapshot (`pg_dump -Fc --no-owner --no-acl`) — all memory, proposals, runs, activity, artifacts, policies, run steps |
| `storage/` | Artifact storage files |
| `artifacts/` | Artifact storage root |
| `config/` | Runtime configuration (no secret values) |
| `secrets/` | Encrypted key files (AES key for provider keys, CLI credentials) |
| `workspaces/` | Workspace metadata directories |
| `logs/` | Only when `BACKUP_INCLUDE_LOGS=true` |
| `backup_manifest.json` | Archive metadata (see below) |

`backups/`, `cache/`, `sandboxes/`, and the live `db/postgres` directory are never included.

**Secrets:** `secrets/` holds encrypted key files. Raw secret values are never written to stdout, logs, or the manifest. Archive permissions are `600`; the output directory is `700`.

### Archive naming

```
$ASPACE_ROOT/<mode>/backups/auto-YYYYMMDD-HHMMSS.tar.gz     ← scheduled
$ASPACE_ROOT/<mode>/backups/manual-YYYYMMDD-HHMMSS.tar.gz   ← API trigger
$ASPACE_ROOT/<mode>/backups/system-YYYYMMDD-HHMMSS.tar.gz   ← ops/scripts/system/backup.sh
```

### backup_manifest.json

Every full-system backup archive — whether written by `BackupService` or by
`ops/scripts/system/backup.sh` — contains a `backup_manifest.json` at its root with
the same schema:

- `backup_format: "agent-space-backup.v1"` — backup format version
- `kind` — `"auto"` | `"manual"`
- `created_at` — ISO timestamp
- `source_root` — absolute path of the data root at backup time
- `included_paths` / `excluded_paths` — what was copied and what was skipped (with reasons)
- `db_snapshot_method` — `"pg_dump_custom"`
- `backup_interval_hours`, `backup_retention_count`
- `warnings` — non-fatal issues
- **Version metadata** (best-effort; `null` when undeterminable):
  - `app_version` — application version at backup time
  - `git_commit` — source commit if the instance is a git checkout
  - `alembic_revision` — current Alembic schema revision in the dumped DB
  - `postgres_server_version` — PostgreSQL server version that produced the dump
  - `pg_dump_version` — `pg_dump` client version that wrote the dump

No raw secret values appear in the manifest. PostgreSQL is the server database.

### PostgreSQL consistency

`BackupService` runs `pg_dump -Fc --no-owner --no-acl` for a consistent custom-format database snapshot using PostgreSQL MVCC — the backend does not need to be stopped. The dump is restored with `pg_restore`. **If `pg_dump` fails, the backup fails closed**: no partial archive is produced.

Full-system backup also copies file data (`storage/`, `artifacts/`, `config/`, `secrets/`, `workspaces/`). The database dump and file copies are not one cross-resource transaction, so restore verification should check restored `artifacts.storage_path` rows against files under `storage/artifacts/`. Use `ops/scripts/system/verify-restore.sh` after restore.

### pg_dump client version (must match the server)

`pg_dump` refuses to dump a server **newer** than the client. The online `BackupService`
runs `pg_dump` inside the backend container, so the backend image installs the PostgreSQL
client whose major version **matches** the `postgres` server image in
`ops/compose/docker-compose.*.yml`. `POSTGRES_MAJOR` in
the mode-specific templates in `ops/env/.env.*.example` drive the compose
`postgres` image and the backend `PG_MAJOR` build arg. The backend `Dockerfile` installs
`postgresql-client-${PG_MAJOR}` from the official PostgreSQL APT repository (PGDG) —
never the generic, older Debian `postgresql-client`. When the `postgres` server major
is upgraded, bump `POSTGRES_MAJOR` in lockstep. This match is enforced by
`tests/unit/test_backup_pg_dump_version.py`. The backend never reaches into the
postgres container (it does not mount the Docker socket); the matching client keeps
`BackupService` self-contained.

### Backup safety guard (prod)

When `AGENT_SPACE_ENV=prod` and `BACKUP_ENABLED=false`, the backend **fails fast at startup**
rather than silently running without backups. To run prod without automatic backups you must
explicitly acknowledge the risk with `BACKUP_ACCEPT_NO_BACKUP=true`; non-prod environments only
log a strong warning. See `app/backups/guard.py`.

### Overlap protection and retention

- Local advisory lock file `backups/.backup.lock` (fcntl-based) prevents overlapping backups across backend processes on the same host.
- Auto backups: the latest `BACKUP_RETENTION_COUNT` (default 7) are kept; older ones are pruned after each run. Manual backups are never pruned automatically.

### API

```bash
# Trigger a manual full-system backup
curl -X POST http://localhost:8010/api/v1/system/backups/manual -H "X-API-Key: <key>"

# List backups
curl http://localhost:8010/api/v1/system/backups -H "X-API-Key: <key>"
```

---

## Offline full-system backup

When app services are stopped, produce an identical-format archive with:

```bash
# Stop writers first; backup starts postgres automatically if needed.
docker compose --env-file "${ASPACE_ROOT:-$HOME/.aspace}/dev/.env" -p agent-space-dev -f ops/compose/docker-compose.dev.yml stop frontend control-plane backend deployer

ops/scripts/system/backup.sh --mode dev
ops/scripts/system/backup.sh --mode prod --include-logs
ops/scripts/system/backup.sh --mode dev --output /mnt/backups
```

This runs `pg_dump` inside the postgres container, copies the file data, writes a `backup_manifest.json` with the same schema as `BackupService` (including `backup_interval_hours` and `backup_retention_count`, read from `BACKUP_INTERVAL_HOURS` / `BACKUP_RETENTION_COUNT` in the mode `.env`, defaulting to `24` / `7`), and produces `system-<timestamp>.tar.gz`. It starts PostgreSQL automatically if needed and stops it afterward only if backup started it. By default, `ops/scripts/system/backup.sh` refuses to run while `frontend`, `control-plane`, `backend`, or `deployer` are active because file data can change during the backup. Use `BackupService` or `POST /api/v1/system/backups/manual` for online backup while the backend is running.

---

## Restore (full-system, single command)

Restore rebuilds the database and the file data from one archive. Stop `frontend`, `control-plane`, `backend`, and `deployer`; restore starts `postgres` automatically if needed and stops it afterward only if restore started it.

> **Do not use `ops/scripts/start.sh` as a restore preflight** — it starts the app services (`frontend`, `control-plane`, `backend`, `deployer`), which `restore.sh` then refuses. Run `ops/scripts/start.sh --<mode>` only *after* the restore succeeds.

```bash
# 1. Stop the app (leave postgres running)
docker compose --env-file "${ASPACE_ROOT:-$HOME/.aspace}/dev/.env" -p agent-space-dev -f ops/compose/docker-compose.dev.yml stop frontend control-plane backend deployer

# 2. Keep or start postgres only
docker compose --env-file "${ASPACE_ROOT:-$HOME/.aspace}/dev/.env" -p agent-space-dev -f ops/compose/docker-compose.dev.yml up -d postgres

# 3. Restore database + files from one archive
ops/scripts/system/restore.sh ~/.aspace/dev/backups/auto-20260101-120000.tar.gz --mode dev --force

# 4. Start the app after restore succeeds, then verify
ops/scripts/start.sh --dev
ops/scripts/system/verify-restore.sh --mode dev
```

`restore.sh` extracts the archive to a temporary staging directory before any destructive database operation. It validates `backup_manifest.json`, verifies `db/agent_space.dump`, checks file-directory overwrite preconditions, refuses to continue while `backend`, `frontend`, or `deployer` are running, then runs `pg_restore` (terminate connections → drop → create → restore) against the maintenance database and restores the file directories into `$ASPACE_ROOT/<mode>/`. `--force` is required to overwrite existing file directories. The live `db/postgres` directory is never touched — the database is rebuilt logically.

During preflight, `restore.sh` reads the manifest **version metadata** (`backup_format`,
`app_version`, `git_commit`, `alembic_revision`, `postgres_server_version`, `pg_dump_version`),
prints the recorded values, and **fails closed before any destructive operation** on a missing
or unexpected `backup_format`, or a PostgreSQL **major-version** mismatch between the backup
source and the live restore target. For controlled recovery you can override this check with
`--force-incompatible-backup`; `--force` (file overwrite) and `--force-running` (active
services) do **not** imply it. The metadata is never silently ignored.

For `test` or `prod`, use the matching compose project and file, for example `agent-space-test` with `ops/compose/docker-compose.test.yml` or `agent-space-prod` with `ops/compose/docker-compose.prod.yml`.

`--force-running` bypasses the running-service refusal and should only be used for controlled recovery when you have independently stopped all writers. `--force-incompatible-backup` bypasses the backup-compatibility preflight (unexpected `backup_format` or PostgreSQL major-version mismatch) and should only be used when you have verified the archive is restorable on the target server.

### DB-only expert path

To dump or restore only the database (no file data):

```bash
ops/scripts/db/dump.sh --mode dev                       # → db/dumps/dump-<ts>.dump
ops/scripts/db/restore.sh ~/.aspace/dev/db/dumps/dump-<ts>.dump --mode dev
```

DB-only dump/restore/reset start `postgres` automatically and stop it afterward only if that script started it. Restore and reset refuse to run while app services are active; stop `backend`, `frontend`, and `deployer` first. `ops/scripts/db/restore.sh` validates the dump with `pg_restore --list` before any destructive drop, so an unreadable archive is rejected before the database is touched.

---

## Restore verification checklist

Use the restore verification script first. It checks the compose `postgres` service,
the Alembic revision, core table counts, and artifact file consistency:

```bash
ops/scripts/system/verify-restore.sh --mode dev
ops/scripts/system/verify-restore.sh --mode test
ops/scripts/system/verify-restore.sh --mode prod
```

For targeted API checks after the verifier passes:

```bash
curl -s "http://localhost:8010/api/v1/spaces?space_id=personal"
curl -s "http://localhost:8010/api/v1/memory?space_id=personal&status=active"
curl -s "http://localhost:8010/api/v1/artifacts?space_id=personal"
curl -s "http://localhost:8010/api/v1/proposals?space_id=personal"
curl -s "http://localhost:8010/api/v1/runs?space_id=personal"
curl -s "http://localhost:8010/api/v1/activity?space_id=personal"
curl -s "http://localhost:8010/api/v1/runs/<run_id>/steps?space_id=personal"   # RunStep replay survives
```

---

## Rollback strategy

1. Stop writes: `docker compose --env-file "${ASPACE_ROOT:-$HOME/.aspace}/dev/.env" -p agent-space-dev -f ops/compose/docker-compose.dev.yml stop frontend control-plane backend deployer`.
2. Snapshot current state: `cp -a ~/.aspace/dev ~/.aspace/dev-pre-rollback-$(date +%Y%m%d-%H%M%S)`.
3. Restore from the last known-good archive: `ops/scripts/system/restore.sh <archive> --mode dev --force`.
4. Restart: `ops/scripts/start.sh --dev`.
5. Verify with `ops/scripts/system/verify-restore.sh --mode dev`.

---

## Security considerations

- **Full-system archives intentionally include `secrets/`** (e.g. `provider_keys.key`,
  CLI credentials) and `config/`. This is by design — a restore must rebuild a working
  instance — so every backup archive is a **high-sensitivity file** and must be handled
  like the secrets it contains.
- Archive permissions are set to `600` (owner only) and the output directory to `700`.
  **`chmod 600` is necessary but is not encryption** — it only restricts other local
  users; it does nothing once the file leaves the machine.
- **Store backups securely, and encrypt them before moving them off-machine.** There is
  no archive passphrase by default; for any offsite/cloud/transfer copy, encrypt first,
  e.g. `gpg --symmetric <archive.tar.gz>`, and protect the passphrase separately.
- Raw secret values are never printed to stdout or written to the manifest. Scripts never
  print database passwords.

---

## Residual risks

| Risk | Mitigation |
|---|---|
| Automatic backup requires `BACKUP_ENABLED=true` | Prod fails fast at startup when backups are off unless `BACKUP_ACCEPT_NO_BACKUP=true`; dogfood operators set `BACKUP_ENABLED=true` in `.env` before first write |
| `pg_dump` client older than the server would fail | Backend image pins `postgresql-client-${PG_MAJOR}` to the `postgres:<major>` server; match enforced by tests |
| `BackupService` fails closed when `pg_dump` raises — no partial archive | Fix the underlying database/connection error before retrying |
| Database dump and file copy are not one cross-resource transaction | Keep normal writers quiescent for offline backup, and run `ops/scripts/system/verify-restore.sh` after restore |
| `workspaces/` captures directory structure, not external mount contents | Document external dependencies separately |
| No cloud backup or offsite replication | Manual GPG + offsite upload if required |

---

## Implementation notes

- `BackupService`: `backend/app/backups/service.py` — creates archives via `pg_dump`, prunes.
- `BackupScheduler`: `backend/app/backups/scheduler.py` — backup tick and API helper used by `SchedulerRegistry`.
- `BackupManifest`: `backend/app/backups/manifest.py` — `backup_manifest.json` structure.
- Backup API: `GET /api/v1/system/backups`, `POST /api/v1/system/backups/manual`.
- `ops/scripts/system/backup.sh` / `ops/scripts/system/restore.sh` — offline full-system tools.
- `ops/scripts/system/verify-restore.sh` — restored DB/schema/artifact consistency check.
- `ops/scripts/db/dump.sh` / `ops/scripts/db/restore.sh` — DB-only expert tools.
- `ops/scripts/lib/local-compose.sh` — shared mode/env/compose resolution for start, DB, and system scripts.
