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


@dataclass
class Module:
    id: str
    name: str
    pkg: str
    api_modules: list[str] = field(default_factory=lambda: ["api"])
    always_on: bool = True


# Load order matters — auth must come first so other modules can depend on it.
_REGISTRY: list[Module] = [
    Module("auth",         "Auth",           "app.auth",         always_on=True),
    Module("spaces",       "Spaces",         "app.spaces",       always_on=True),
    Module("workspaces",   "Workspaces",     "app.workspaces",   always_on=True),
    Module("memory",       "Memory",         "app.memory",       api_modules=["api", "context_api"], always_on=True),
    Module("sessions",     "Sessions",       "app.sessions",     always_on=True),
    Module("tasks",        "Tasks",          "app.tasks",        always_on=True),
    Module("agents",        "Agents",          "app.agents",        always_on=True),
    Module("runs",          "Runs",            "app.runs",          always_on=True),
    Module("proposals",     "Proposals",       "app.proposals",     always_on=True),
    Module("artifacts",     "Artifacts",       "app.artifacts",     always_on=True),
    Module("jobs",           "Job Queue",         "app.jobs",          always_on=True),
    Module("cli_adapters",  "CLI Adapters",      "app.cli_adapters",  always_on=True),
    Module("credentials",   "CLI Credentials",   "app.credentials",   always_on=True),
    Module("capabilities",  "Capabilities",      "app.capabilities",  always_on=True),
    Module("deployment",    "Deployment",     "app.deployment",    always_on=True),
    Module("activity",  "Activity Inbox",  "app.activity",   always_on=True),
    Module("workspace_console", "Workspace Console", "app.workspace_console", always_on=True),
    Module("providers",         "Providers",        "app.providers",        always_on=True),
    Module("home",              "Home",             "app.home",             always_on=True),
    Module("me",                "PersonalView",     "app.me",               always_on=True),
    Module("source_pointers",   "Source Pointers",  "app.source_pointers",  always_on=True),
    Module("backups",           "Backups",          "app.backups",          always_on=True),
    Module("personal_memory_grants", "Personal Memory Grants", "app.personal_memory_grants", always_on=True),
    Module("execution_planes",      "Execution Planes",      "app.execution_planes",      always_on=True),
    Module("workspace_profiles",    "Workspace Profiles",    "app.workspace_profiles",    always_on=True),
    Module("runtime_tool_bindings", "Runtime Tool Bindings", "app.runtime_tool_bindings", always_on=True),
    Module("projects",              "Projects",              "app.projects",              always_on=True),
    # Optional modules — not yet implemented; uncomment when ready.
    # Module("wiki",     "Wiki",            "app.knowledge",  always_on=False),
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
