"""
Module registry — controls which feature modules are loaded and registered.

Every module that exposes HTTP routes has an entry here. Modules marked
always_on=True are always registered. Optional modules (always_on=False)
can be enabled per deployment via the ENABLED_MODULES environment variable
(comma-separated module IDs) — reserved for future use.

To add a new module:
  1. Create app/<module_id>/api.py with a `router = APIRouter(...)`.
  2. Add a Module entry below.
  3. Restart the server.

Cross-module imports are allowed from modules into core (app.db, app.config,
app.models, app.schemas, app.auth). Modules must not import from each other
directly — use the service layer or dependency injection.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)


if TYPE_CHECKING:
    from app.proposals import ProposalApplierRegistry
    from app.runs import RunFinalizedHookRegistry
    from app.spaces import SpaceCreatedHookRegistry


@dataclass
class Module:
    id: str
    name: str
    pkg: str
    api_modules: list[str] = field(default_factory=lambda: ["api"])
    always_on: bool = True
    # Submodule (relative to ``pkg``) exposing
    # ``register_space_created_hooks(registry)`` for modules that initialize
    # per-space state when a new Space is created. None means no space-created
    # hooks.
    space_created_hooks: str | None = None
    # Submodule (relative to ``pkg``) exposing
    # ``register_run_finalized_hooks(registry)`` for modules that own post-run
    # side effects dispatched when a terminal Run is finalized. None means no
    # run-finalized hooks.
    run_finalized_hooks: str | None = None
    # Submodule (relative to ``pkg``) exposing
    # ``register_proposal_appliers(registry)`` for modules that own the apply
    # business logic of one or more proposal types. None means the module owns
    # no proposal appliers.
    proposal_appliers: str | None = None


# Load order matters — auth must come first so other modules can depend on it.
_REGISTRY: list[Module] = [
    Module("auth",         "Auth",           "app.auth",         always_on=True),
    Module("spaces",       "Spaces",         "app.spaces",       always_on=True),
    Module("workspaces",   "Workspaces",     "app.workspaces",   always_on=True),
    Module("memory",       "Memory",         "app.memory",       api_modules=["api", "context_api"], always_on=True, space_created_hooks="space_hooks", proposal_appliers="proposal_appliers"),
    Module("sessions",     "Sessions",       "app.sessions",     api_modules=["api", "internal_api"], always_on=True),
    Module("tasks",        "Tasks",          "app.tasks",        always_on=True, run_finalized_hooks="run_lifecycle"),
    Module("agents",        "Agents",          "app.agents",        api_modules=["api", "internal_api"], always_on=True, proposal_appliers="proposal_appliers"),
    Module("agent_templates", "Agent Templates", "app.agent_templates", always_on=True),
    Module("runs",          "Runs",            "app.runs",          api_modules=["api", "internal_api"], always_on=True),
    Module("proposals",     "Proposals",       "app.proposals",     api_modules=["api", "internal_api"], always_on=True),
    Module("artifacts",     "Artifacts",       "app.artifacts",     always_on=True),
    Module("credentials",   "CLI Credentials",   "app.credentials",   always_on=True),
    Module("capabilities",  "Capabilities",      "app.capabilities",  always_on=True),
    Module("deployment",    "Deployment",     "app.deployment",    always_on=True),
    Module("activity",  "Activity Inbox",  "app.activity",   always_on=True),
    Module("workspace_console", "Workspace Console", "app.workspace_console", always_on=True),
    Module("providers",         "Providers",        "app.providers",        always_on=True),
    Module("home",              "Home",             "app.home",             always_on=True),
    Module("me",                "PersonalView",     "app.me",               always_on=True),
    Module("source_pointers",   "Source Pointers",  "app.source_pointers",  always_on=True),
    Module("personal_memory_grants", "Personal Memory Grants", "app.personal_memory_grants", always_on=True),
    Module("execution_planes",      "Execution Planes",      "app.execution_planes",      always_on=True, space_created_hooks="space_hooks"),
    Module("workspace_profiles",    "Workspace Profiles",    "app.workspace_profiles",    always_on=True),
    Module("runtime_tool_bindings", "Runtime Tool Bindings", "app.runtime_tool_bindings", always_on=True),
    Module("projects",              "Projects",              "app.projects",              always_on=True),
    Module("automation",            "Automation",            "app.automation",            always_on=True),
    Module("knowledge",             "Knowledge",             "app.knowledge",             always_on=True, space_created_hooks="space_hooks", proposal_appliers="proposal_appliers"),
    Module("intake",                "Intake",                "app.intake",                api_modules=["api"], always_on=True),
    Module("evolution",             "Evolution",             "app.evolution",             always_on=True, proposal_appliers="proposal_appliers"),
    Module("daily_reports",        "Daily Capture Report",  "app.daily_reports",         always_on=True),
    # Optional modules — not yet implemented; uncomment when ready.
    # Module("cards",    "Cards",           "app.cards",      always_on=False),
]


def register(app: "FastAPI", enabled: set[str] | None = None) -> list[str]:
    """
    Import and register HTTP routers for all enabled modules.

    If `enabled` is None, only always_on modules are loaded.
    If `enabled` is a set of IDs, always_on modules + those IDs are loaded.
    """
    loaded: list[str] = []
    for module in _REGISTRY:
        if not module.always_on and (enabled is None or module.id not in enabled):
            log.info("module %s: disabled", module.id)
            continue

        for api_name in module.api_modules:
            try:
                mod = importlib.import_module(f".{api_name}", package=module.pkg)
            except ImportError as exc:
                log.warning("module %s: cannot import %s: %s", module.id, api_name, exc)
                continue

            if hasattr(mod, "router"):
                app.include_router(mod.router, prefix="/api/v1")
                log.debug("module %s: registered router from %s", module.id, api_name)

            for extra in getattr(mod, "extra_routers", []):
                app.include_router(extra, prefix="/api/v1")
                log.debug("module %s: registered extra router from %s", module.id, api_name)

        loaded.append(module.id)

    return loaded


def register_space_created_hooks(
    registry: "SpaceCreatedHookRegistry",
    enabled: set[str] | None = None,
    *,
    modules: "list[Module] | None" = None,
) -> list[str]:
    """Populate ``registry`` from each selected module's space-created hook.

    Modules that initialize per-space state declare a ``space_created_hooks``
    submodule exposing ``register_space_created_hooks(registry)``. This wires
    them through the same module registry that loads routers and job handlers,
    so adding a new per-space initializer means adding a module hook — never
    editing the core Space creation service.

    Fails fast: a *selected* module (``always_on``, or named in ``enabled``)
    that declares ``space_created_hooks`` must import cleanly and expose the
    hook. A broken import (``ImportError``) propagates and a missing hook raises
    ``RuntimeError`` — both surface at startup rather than silently dropping a
    space's default records. Intentionally disabled modules are skipped without
    importing.

    ``modules`` overrides the module list (for tests); it defaults to the
    backend module registry. Returns the module ids whose hooks registered.
    """
    loaded: list[str] = []
    for module in (_REGISTRY if modules is None else modules):
        if not module.space_created_hooks:
            continue
        if not module.always_on and (enabled is None or module.id not in enabled):
            continue  # intentionally disabled — skip its hooks without importing

        # A selected module that declares space_created_hooks MUST register
        # cleanly: let ImportError propagate (fail fast) and raise on a missing
        # hook.
        mod = importlib.import_module(f".{module.space_created_hooks}", package=module.pkg)
        hook = getattr(mod, "register_space_created_hooks", None)
        if not callable(hook):
            raise RuntimeError(
                f"module {module.id}: {module.pkg}.{module.space_created_hooks} declares "
                f"space_created_hooks but exposes no register_space_created_hooks(registry)"
            )

        hook(registry)
        loaded.append(module.id)
        log.debug(
            "module %s: registered space-created hooks from %s",
            module.id, module.space_created_hooks,
        )

    return loaded


def register_run_finalized_hooks(
    registry: "RunFinalizedHookRegistry",
    enabled: set[str] | None = None,
    *,
    modules: "list[Module] | None" = None,
) -> list[str]:
    """Populate ``registry`` from each selected module's run-finalized hook.

    Modules that own post-run side effects declare a ``run_finalized_hooks``
    submodule exposing ``register_run_finalized_hooks(registry)``. This wires
    them through the same module registry that loads routers, job handlers, and
    space-created hooks, so adding a new post-run side effect means adding a
    module hook — never editing ``runs`` finalization internals.

    Fails fast: a *selected* module (``always_on``, or named in ``enabled``)
    that declares ``run_finalized_hooks`` must import cleanly and expose the
    hook. A broken import (``ImportError``) propagates and a missing hook raises
    ``RuntimeError`` — both surface at first finalization rather than silently
    dropping a module's post-run side effects. Intentionally disabled modules
    are skipped without importing.

    ``modules`` overrides the module list (for tests); it defaults to the
    backend module registry. Returns the module ids whose hooks registered.
    """
    loaded: list[str] = []
    for module in (_REGISTRY if modules is None else modules):
        if not module.run_finalized_hooks:
            continue
        if not module.always_on and (enabled is None or module.id not in enabled):
            continue  # intentionally disabled — skip its hooks without importing

        # A selected module that declares run_finalized_hooks MUST register
        # cleanly: let ImportError propagate (fail fast) and raise on a missing
        # hook.
        mod = importlib.import_module(f".{module.run_finalized_hooks}", package=module.pkg)
        hook = getattr(mod, "register_run_finalized_hooks", None)
        if not callable(hook):
            raise RuntimeError(
                f"module {module.id}: {module.pkg}.{module.run_finalized_hooks} declares "
                f"run_finalized_hooks but exposes no register_run_finalized_hooks(registry)"
            )

        hook(registry)
        loaded.append(module.id)
        log.debug(
            "module %s: registered run-finalized hooks from %s",
            module.id, module.run_finalized_hooks,
        )

    return loaded


def register_proposal_appliers(
    registry: "ProposalApplierRegistry",
    enabled: set[str] | None = None,
    *,
    modules: "list[Module] | None" = None,
) -> list[str]:
    """Populate ``registry`` from each selected module's proposal-applier hook.

    Modules that own proposal apply business logic declare a
    ``proposal_appliers`` submodule exposing
    ``register_proposal_appliers(registry)``. This wires them through the same
    module registry that loads routers, job handlers, and lifecycle hooks, so
    adding a new proposal type means adding a module hook — never editing the
    proposal API, the policy apply gate, or ``ProposalApplyService`` dispatch
    internals.

    Fails fast: a *selected* module (``always_on``, or named in ``enabled``)
    that declares ``proposal_appliers`` must import cleanly and expose the
    hook. A broken import (``ImportError``) propagates and a missing hook
    raises ``RuntimeError`` — both surface at startup (or first apply) rather
    than silently degrading into "unsupported proposal type" failures.
    Intentionally disabled modules are skipped without importing.

    ``modules`` overrides the module list (for tests); it defaults to the
    backend module registry. Returns the module ids whose appliers registered.
    """
    loaded: list[str] = []
    for module in (_REGISTRY if modules is None else modules):
        if not module.proposal_appliers:
            continue
        if not module.always_on and (enabled is None or module.id not in enabled):
            continue  # intentionally disabled — skip its appliers without importing

        # A selected module that declares proposal_appliers MUST register
        # cleanly: let ImportError propagate (fail fast) and raise on a missing
        # hook.
        mod = importlib.import_module(f".{module.proposal_appliers}", package=module.pkg)
        hook = getattr(mod, "register_proposal_appliers", None)
        if not callable(hook):
            raise RuntimeError(
                f"module {module.id}: {module.pkg}.{module.proposal_appliers} declares "
                f"proposal_appliers but exposes no register_proposal_appliers(registry)"
            )

        hook(registry)
        loaded.append(module.id)
        log.debug(
            "module %s: registered proposal appliers from %s",
            module.id, module.proposal_appliers,
        )

    return loaded


def list_modules(enabled: set[str] | None = None) -> list[dict]:
    """Return module metadata for the /api/v1/features endpoint."""
    result = []
    for module in _REGISTRY:
        is_enabled = module.always_on or (enabled is not None and module.id in enabled)
        result.append({
            "id": module.id,
            "name": module.name,
            "enabled": is_enabled,
            "always_on": module.always_on,
        })
    return result
