import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings, paths
from .db import init_db
from .modules.registry import register as register_modules, list_modules

@asynccontextmanager
async def lifespan(app: FastAPI):
    paths.init_dirs()
    paths.validate()
    # Alembic upgrade is synchronous and can take noticeable time on cold DBs.
    await asyncio.to_thread(init_db)
    from .db import migrate_db
    migrate_db()

    from .db import SessionLocal
    from .capabilities.registry import CapabilityRegistry
    from .auth.api_key import ApiKeyService
    from .feature_gates import API_KEYS_DB_PERSISTED
    from .models import Space, SpaceMembership
    from .agents import hooks as _hooks  # noqa: F401 — registers post-run hooks
    from .jobs import handlers as _job_handlers  # noqa: F401 — registers job handlers
    from .jobs.queue import DatabaseQueueService, init_queue
    from .jobs.worker import start_worker

    db = SessionLocal()
    try:
        CapabilityRegistry(db).reload()

        # Register system-core workspace if configured
        from .workspaces.system_core import register_system_core_workspace
        register_system_core_workspace(db)

        if settings.debug:
            dev_space = db.query(Space).filter(Space.id == settings.default_space_id).first()
            owner_ms = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.space_id == settings.default_space_id,
                    SpaceMembership.role == "owner",
                    SpaceMembership.status == "active",
                )
                .first()
            )
            if dev_space and owner_ms and API_KEYS_DB_PERSISTED:
                existing = ApiKeyService(db).list(space_id=settings.default_space_id)
                if not existing:
                    _, raw = ApiKeyService(db).create(
                        space_id=settings.default_space_id,
                        owner_user_id=owner_ms.user_id,
                        name="dev-key",
                    )
                    print(f"\n[agent-space] Dev API key: {raw}\n")
    finally:
        db.close()

    # Initialise the durable job queue and start the background worker
    queue = DatabaseQueueService(SessionLocal)
    init_queue(queue)
    worker_task = await start_worker(queue)

    # ── Backup scheduler ──────────────────────────────────────────────────────
    _backup_scheduler = None
    if settings.backup_enabled:
        from .backups.service import BackupService
        from .backups.scheduler import BackupScheduler, set_scheduler
        _backup_svc = BackupService(
            data_root=Path(settings.agent_space_home),
            backup_root=Path(settings.backup_root),
            interval_hours=settings.backup_interval_hours,
            retention_count=settings.backup_retention_count,
            include_logs=settings.backup_include_logs,
        )
        _backup_scheduler = BackupScheduler(
            service=_backup_svc,
            interval_hours=settings.backup_interval_hours,
            run_on_start=settings.backup_on_startup,
        )
        set_scheduler(_backup_scheduler)
        await _backup_scheduler.start()

    yield

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    if _backup_scheduler is not None:
        from .backups.scheduler import set_scheduler
        await _backup_scheduler.stop()
        set_scheduler(None)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Space-based, multi-user, agent-first memory system.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all enabled feature modules (each module owns its routes in api.py)
register_modules(app)


# ---------------------------------------------------------------------------
# Standardized error responses
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": _status_code_to_slug(exc.status_code), "message": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": "Request validation failed", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import logging
    logging.getLogger("agent-space").exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred."},
    )


def _status_code_to_slug(code: int) -> str:
    return {400: "bad_request", 401: "unauthorized", 403: "forbidden",
            404: "not_found", 409: "conflict", 422: "validation_error"}.get(code, "error")


@app.get("/health")
def health():
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/v1/auth/google-configured")
def google_auth_configured():
    """Check if Google OAuth is configured."""
    from .auth.google import is_configured
    return {"google_auth_available": is_configured()}


@app.get("/api/v1/features")
def list_features():
    """List all registered modules and their enabled status."""
    return list_modules()
