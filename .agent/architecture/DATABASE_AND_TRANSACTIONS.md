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

- `BackupService` uses an independent SQLite connection/snapshot mechanism, not a request/job ORM Session.
- Backup uses `sqlite3.Connection.backup()` (WAL-safe, live-database snapshot).
- Raw file-copy fallback is not used — it may miss WAL tail and produce a misleading successful archive.
- Long-running app transactions must be avoided so backups stay fresh and SQLite lock contention stays low.
- Backup metadata and manifests must not contain raw secrets.
- `backups/` is always excluded from backup archives (recursion prevention).

## SQLite Current Assumptions

- SQLite allows only one writer at a time; long write transactions block other writes and can make backups stale.
- WAL mode plus sqlite backup API is acceptable for current local single-process use.
- Savepoints are available and isolate best-effort writes.
- Loose typing must not be relied on in new infrastructure.
- `RunStep` has DB-level `UniqueConstraint(run_id, step_index)`.
- `BackupService` uses a local advisory lock file (`backups/.backup.lock`, fcntl-based) and fails closed when the sqlite backup API fails.

## Postgres Compatibility Rules

Do not introduce patterns that block a future Postgres migration:
- No SQLite-only SQL in new infrastructure.
- No reliance on SQLite loose typing or implicit constraint behavior.
- Use explicit FK, index, and unique constraints where needed.
- Timestamps must be UTC.
- Store large files in storage; store metadata and relative paths in DB.
- Avoid long transactions and transaction-spanning external calls.
- Do not rely on application-only `MAX()+1` ordering for distributed writers without a future lock/constraint note. Current `RunStep.step_index` uses `MAX()+1` for local SQLite — a documented distributed-runner risk.

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

- **Postgres migration** — requires removing SQLite-only patterns, ensuring UTC timestamps everywhere, FK constraint review, and migration of existing data.
- **Distributed multi-host locking** — current single-process advisory lock does not extend to multi-host. Requires a real distributed lock service.
- **Stronger RunStep ordering under distributed writers** — current `MAX()+1` approach is not safe under concurrent writers. Requires DB sequence or distributed counter.
