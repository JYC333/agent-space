import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings, paths
from .db import init_db
from .modules.registry import register as register_modules, list_modules
from .policy import PolicyAuditPersistError, PolicyGateBlocked

@asynccontextmanager
async def lifespan(app: FastAPI):
    paths.init_dirs()
    paths.validate()

    # Alembic upgrade is synchronous and can take noticeable time on cold DBs.
    await asyncio.to_thread(init_db)

    from .db import SessionLocal
    from .capabilities import CapabilityRegistry
    from .auth import ApiKeyService
    from .feature_gates import API_KEYS_DB_PERSISTED
    from .models import Space, SpaceMembership

    # Build and publish the space-created hook registry before any code path can
    # create a Space (bootstrap_instance / register_system_core_workspace below).
    # Mirrors the job registry: populating it here makes a broken/missing module
    # hook fail fast at startup rather than on the first space creation.
    from .spaces import SpaceCreatedHookRegistry
    from .spaces.hooks import init_registry as init_space_created_registry
    from .modules.registry import register_space_created_hooks

    space_created_registry = SpaceCreatedHookRegistry()
    register_space_created_hooks(space_created_registry)
    init_space_created_registry(space_created_registry)

    # Build and publish the run-finalized hook registry the same way, so a
    # broken/missing module hook fails fast at startup rather than on the
    # first run finalization.
    from .runs import RunFinalizedHookRegistry
    from .runs.lifecycle_hooks import init_registry as init_run_finalized_registry
    from .modules.registry import register_run_finalized_hooks

    run_finalized_registry = RunFinalizedHookRegistry()
    register_run_finalized_hooks(run_finalized_registry)
    init_run_finalized_registry(run_finalized_registry)

    # Build and publish the proposal applier registry the same way, so a
    # broken/missing/duplicate module applier fails fast at startup rather
    # than on the first proposal accept.
    from .proposals import ProposalApplierRegistry
    from .proposals.applier_registry import init_registry as init_proposal_applier_registry
    from .modules.registry import register_proposal_appliers

    proposal_applier_registry = ProposalApplierRegistry()
    register_proposal_appliers(proposal_applier_registry)
    init_proposal_applier_registry(proposal_applier_registry)

    db = SessionLocal()
    try:
        CapabilityRegistry(db).reload()

        # Bring a fresh (empty) PostgreSQL database to a usable initial state:
        # default owner user + their personal space + membership, and default
        # execution planes. Idempotent — safe on every startup.
        from .bootstrap import bootstrap_instance
        bootstrap_instance(db, user_id=settings.default_user_id)

        # Register system-core workspace if configured
        from .workspaces.system_core import register_system_core_workspace
        register_system_core_workspace(db)

        if settings.debug:
            from .spaces.defaults import resolve_default_space_id
            space_id = resolve_default_space_id(db)
            dev_space = db.query(Space).filter(Space.id == space_id).first()
            owner_ms = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.space_id == space_id,
                    SpaceMembership.role == "owner",
                    SpaceMembership.status == "active",
                )
                .first()
            )
            if dev_space and owner_ms and API_KEYS_DB_PERSISTED:
                existing = ApiKeyService(db).list(space_id=space_id)
                if not existing:
                    _, raw = ApiKeyService(db).create(
                        space_id=space_id,
                        owner_user_id=owner_ms.user_id,
                        name="dev-key",
                    )
                    print(f"\n[agent-space] Dev API key: {raw}\n")
    finally:
        db.close()

    yield


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


@app.exception_handler(PolicyGateBlocked)
async def policy_gate_blocked_handler(request: Request, exc: PolicyGateBlocked):
    """Roll back business work and independently persist one blocking decision."""
    db = getattr(getattr(request, "state", None), "db", None)
    if db is not None:
        try:
            db.rollback()
        except Exception:
            import logging
            logging.getLogger("agent-space").warning(
                "Failed to rollback request DB session after PolicyGateBlocked action=%s",
                exc.action,
            )

    from .policy import write_blocked_gate_audit
    try:
        record_id = write_blocked_gate_audit(exc)
    except Exception:
        import logging
        logging.getLogger("agent-space").error(
            "DurablePolicyAuditWriter failed after PolicyGateBlocked action=%s actor=%s",
            exc.action, exc.actor_id, exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "policy_audit_persist_failed",
                "message": "Policy decision audit could not be persisted; sensitive action was blocked.",
                "audit_code": "policy_decision_record_persist_failed",
            },
        )

    decision = exc.decision
    return JSONResponse(
        status_code=exc.http_status_code,
        content={
            "error": exc.error_code,
            "message": decision.message,
            "reason_code": decision.reason_code,
            "audit_code": decision.audit_code,
            "action": exc.action,
            "risk_level": decision.risk_level.value,
            "policy_decision_record_id": record_id,
        },
    )


@app.exception_handler(PolicyAuditPersistError)
async def policy_audit_persist_error_handler(request: Request, exc: PolicyAuditPersistError):
    db = getattr(getattr(request, "state", None), "db", None)
    if db is not None:
        try:
            db.rollback()
        except Exception:
            import logging
            logging.getLogger("agent-space").warning(
                "Failed to rollback request DB session after PolicyAuditPersistError action=%s",
                exc.action,
            )

    return JSONResponse(
        status_code=500,
        content={
            "error": "policy_audit_persist_failed",
            "message": "Policy decision audit could not be persisted; sensitive action was blocked.",
            "audit_code": exc.audit_code,
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    import logging
    logging.getLogger("agent-space").exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred."},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": "Request validation failed", "detail": exc.errors()},
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
    from .auth import is_configured
    return {"google_auth_available": is_configured()}


@app.get("/api/v1/features")
def list_features():
    """List all registered modules and their enabled status."""
    return list_modules()
