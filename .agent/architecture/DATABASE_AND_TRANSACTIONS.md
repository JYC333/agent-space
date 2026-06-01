# Database and Transactions

## UnitOfWork Pattern

`UnitOfWork` (`core/backend/app/db_uow.py`) owns transaction control: commit, rollback, flush, savepoint, and explicit failed-session detection.

- Wraps an existing SQLAlchemy `Session`.
- Exposes `flush()` without hiding SQLAlchemy.
- Exposes `savepoint()` for nested best-effort writes.
- Makes failed Session state explicit.
- Does **not** provide generic query methods.

Repositories and stores still own domain queries and row construction. `UnitOfWork` owns only transaction control.

## Transaction Ownership Rules

- API routes may open or receive a Session, but must not scatter commits across unrelated operations.
- Workflow/service layer owns commit for multi-object workflows.
- Repository/store helpers may add, query, and flush, but must not commit unless explicitly documented as a standalone operation.
- Low-level helpers must not commit invisibly when used by proposal apply, run execution, job terminal state, or workspace lifecycle workflows.
- `commit()` should appear only in approved transaction-owner modules or explicit standalone operations.
- `rollback()` belongs at workflow boundaries and failed-session recovery paths, not inside unrelated low-level helpers.
- `flush()` is allowed when IDs, FK checks, or constraints are needed before continuing, but it is not a durability boundary.

## Savepoint and Best-Effort Rules

**Best-effort evidence** (use `UnitOfWork.savepoint()` or a separate short transaction):
- RunStep metadata and terminal detail
- Auxiliary Activity records
- Traces and read logs
- Non-critical replay/read audit rows

**Critical writes** (must not be abandoned due to evidence write failures):
- Run terminal status
- Proposal status
- MemoryEntry creation, update, archive, and provenance/source fields
- Policy row creation and supersession
- Job terminal state
- Workspace lifecycle state
- Backup manifest/archive state

If SQLAlchemy marks the whole Session failed, the helper must surface that state. Callers must not continue as though the Session were clean.

## External Call Boundary

Do not hold an open transaction while calling:
- Runtime adapters
- LLM/model providers
- Deployers
- Backup tar/snapshot creation
- External file/system commands
- Network APIs

Required pattern:
1. Open short transaction.
2. Write pending/running/context state.
3. Commit.
4. Perform external work **outside** the transaction.
5. Open short transaction.
6. Persist result or failure.

`RunExecutionService` applies this: setup state is committed before adapter execution; result/failure is persisted in a separate transaction afterward.

## Backup and Restore Consistency

- `BackupService` uses `pg_dump -Fc` (custom format) for a consistent PostgreSQL database snapshot, independent from the ORM Session. `db_snapshot_method` is `"pg_dump_custom"` in the manifest.
- If `pg_dump` fails, the backup fails closed — no partial archive is produced.
- Full-system backup also copies file data. The database dump and file copies are not one cross-resource transaction, so restore verification checks artifact rows against restored files.
- Run `scripts/system/verify-restore.sh` after restore to verify Alembic state, core table counts, and `artifacts.storage_path` file consistency.
- Long-running app transactions must be avoided so backups stay fresh.
- Backup metadata and manifests must not contain raw secrets.
- `backups/` is always excluded from backup archives (recursion prevention).
- **`db/postgres` is the live PostgreSQL data directory — it is never copied into a backup
  archive.** The database is captured logically with `pg_dump -Fc`; copying the live data
  directory is not a supported backup. The manifest records `db/postgres/ (live PostgreSQL data)`
  in its excluded paths.
- **Manifest version metadata.** Every manifest (online `BackupService` and offline
  `scripts/system/backup.sh`) records `backup_format`, `app_version`, `git_commit`,
  `alembic_revision`, `postgres_server_version`, and `pg_dump_version`. Each value is
  best-effort and may be `null`; gathering it never aborts a backup.
- **Restore preflight validates version metadata.** `scripts/system/restore.sh` reads the
  manifest, prints the recorded versions, and warns clearly on `backup_format` or PostgreSQL
  major-version mismatch. Manifest metadata is never silently ignored.

## Database: PostgreSQL

- **PostgreSQL is the server database.** `DATABASE_URL` accepts
  `postgresql+psycopg://...` and normalizes `postgresql://...` to the canonical
  psycopg form. The app rejects non-PostgreSQL URLs at startup.
- **Local compose/env resolution** is shared by `scripts/start.sh`, `scripts/db/*.sh`,
  and `scripts/system/*.sh` through `scripts/lib/local-compose.sh`: mode validation,
  `ASPACE_ROOT`, `$ASPACE_ROOT/<mode>`, `$MODE_ROOT/.env`, `AGENT_SPACE_MODE_ROOT`,
  compose project/file, and `docker compose --env-file "$ENV_FILE"` are one path.
- Local PostgreSQL containers have stable mode-specific names:
  `agent-space-dev-postgres`, `agent-space-test-postgres`, and `agent-space-prod-postgres`.
- Schema is owned by Alembic migrations (`core/backend/migrations/`); application startup runs
  `alembic upgrade head` (`app.db.init_db`) and never creates schema via `create_all()`.
- Boolean defaults are PostgreSQL-native (`true`/`false`).
- **Migration command path** (`scripts/db/migrate.sh`): defaults to Docker-native — it runs
  Alembic *inside the backend service* via Compose, so it uses the in-network `postgres` host
  (Postgres is not published to the host) and the matching client/deps from the backend image.
  `--host` runs Alembic on the host only against an explicitly configured, reachable external
  Postgres, with a connectivity preflight. `scripts/db/reset-postgres.sh` reuses this path so a
  freshly dropped/created DB is always migrated (never left empty/unmigrated).
  If Docker-native migration starts the compose `postgres` service, it stops that service on
  exit; DB-only dump/restore/reset and offline system backup/restore/verify use the same
  start/stop ownership rule. They leave a pre-existing running database untouched.
- **Pre-migration backup safety** (`scripts/db/migrate.sh`): `--mode prod` requires a
  pre-migration `pg_dump -Fc` backup before Alembic runs, written to
  `$ASPACE_ROOT/<mode>/db/dumps/pre-migrate-<timestamp>.dump`. If that dump fails, migration
  aborts before Alembic touches the schema. Non-prod modes skip it for convenience; opt in with
  `PRE_MIGRATION_BACKUP=1` or `--pre-migration-backup`.
- **Fresh-instance bootstrap** (`app.bootstrap.bootstrap_instance`, called from lifespan): on an
  empty migrated DB it idempotently ensures the default personal space, the default owner user +
  active membership, and the default execution planes — the usable initial state.
- PostgreSQL data lives under `$ASPACE_ROOT/<mode>/db/postgres` (bind-mounted into the postgres container).
- Database dumps live under `$ASPACE_ROOT/<mode>/db/dumps`.
- Local test mode keeps host API `localhost:8100`, but the backend container listens on
  internal port `8000` and compose-internal clients use `http://backend:8000`.
- Job queue uses `SELECT ... FOR UPDATE SKIP LOCKED` for safe concurrent claim. `jobs.scheduled_at`
  is NOT NULL with a server default, and DB CHECK constraints enforce the allowed `status` set,
  `attempts >= 0`, and `max_attempts > 0`.
- `RunStep` has DB-level `UniqueConstraint(run_id, step_index)`.
- `BackupService` uses a local advisory lock file (`backups/.backup.lock`, fcntl-based) and fails closed when `pg_dump` fails.
- Backup/restore uses `pg_dump -Fc --no-owner --no-acl` (custom format) and `pg_restore`. The
  backend image pins `postgresql-client-${PG_MAJOR}` to the `postgres:<major>` server so the
  online `pg_dump` client is never older than the server. Backups are disabled by default; prod
  fails fast at startup unless `BACKUP_ENABLED=true` or `BACKUP_ACCEPT_NO_BACKUP=true`.

## Deployment Topology Assumption

Current local deployment assumes one backend process owns startup migration/bootstrap/schedulers. Multi-backend deployment is out of current scope and requires separate migration/bootstrap and scheduler leadership.

## Rules

- Use explicit FK, index, and unique constraints.
- Timestamps must be UTC with timezone.
- Store large files in storage; store metadata and relative paths in DB.
- Avoid long transactions and transaction-spanning external calls.
- Do not rely on application-only `MAX()+1` ordering for distributed writers without a future lock/constraint note. Current `RunStep.step_index` uses `MAX()+1` — a documented distributed-runner risk.

## Anti-Patterns

- A massive `DatabaseService` or `DatabaseOperations` class owning everything.
- Moving every query into one file mechanically.
- Low-level helper commits inside accepted proposal apply.
- Catching `IntegrityError`/`DBAPIError` and continuing without rollback or savepoint isolation.
- Runtime/model/deployer/backup calls inside long DB transactions.
- Persisting raw secrets in inspectable DB fields or backup manifests.
- Shell scripts writing business DB state directly.
- Hard-deleting workspace metadata because a path is missing.

## Transaction Audit Summary

| Area | Transaction owner | External call risk |
|---|---|---|
| RunService / run creation | `RunService` | Low |
| RunExecutionService / runtime execution | `RunExecutionService` — setup commit before adapter | High: adapter/sandbox |
| RunStep writes | Caller — savepoint-isolated best-effort | Low per step |
| Artifact persistence | Caller (`RunExecutionService`) | File storage write |
| Proposal creation / acceptance / rejection | `ProposalService` | Code patch file write |
| Memory proposal apply | `ProposalService.accept` — one commit with rollback on failure | Source monitoring only (in-process) |
| Policy proposal apply | `ProposalService.accept` — one commit | None |
| Activity capture | `ActivityService` | None |
| Activity consolidation | One short commit per activity outcome | Low (consolidation model call possible) |
| Job queue / handlers | Short standalone commits; auxiliary events isolated | Handler execution |
| Workspace scan | Stale-pass/create-pass commits; filesystem scan | Filesystem scan |
| BackupService | Independent from ORM — no business commits | Tar/snapshot/file IO |
| Deployment/deployer client | No durable DB job state currently | High: socket/network |

## Known Future Work

- **Distributed multi-host locking** — current single-process advisory lock does not extend to multi-host. Requires a real distributed lock service.
- **Stronger RunStep ordering under distributed writers** — current `MAX()+1` approach is not safe under concurrent writers. Requires DB sequence or distributed counter.
