"""Public facade for the ``runs`` module.

Re-exports the symbols other modules (``agents``, ``tasks``, ``jobs``,
``automation``) import from ``runs`` today, so callers can depend on
``app.runs`` instead of five different internal submodules. See
``.agent/architecture/TS_MIGRATION_STRATEGY.md``.

``runtimes`` no longer imports ``runs`` at all: runtime adapters emit run
evidence and register subprocess handles through ``app.runtimes.ports``
protocols, implemented by ``app.runs.runtime_bridge`` and injected by
``app.runs.execution``. Dependency direction is ``runs -> runtimes`` only.

``tasks`` no longer has a cycle with ``runs`` either: the RunEvaluation →
TaskEvaluation bridge moved behind the runs-owned
``app.runs.lifecycle_hooks.RunFinalizedHookRegistry``; ``tasks`` registers its
hook via the module registry, so the dependency direction is ``tasks -> runs``
only.

**Why lazy (PEP 562 ``__getattr__``):** ``runs`` is the execution spine with a
large service graph. Eager re-export from this ``__init__`` would pull that
whole graph the moment any ``app.runs.<sub>`` is imported. Lazy resolution
imports the exact submodule a direct import would, only on first access — same
modules load, same order, no runtime behavior change — and keeps the facade
light (``tests/invariants/test_public_facades.py`` asserts this).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public name -> submodule (relative to this package) that defines it.
# Derived from the symbols other modules import from ``runs`` today.
_EXPORTS: dict[str, str] = {
    "ResolvedRuntimeAdapter": "adapter_resolution",
    "RunExecutionService": "execution",
    "DuplicateRunFinalizedHookError": "lifecycle_hooks",
    "RunFinalizedContext": "lifecycle_hooks",
    "RunFinalizedHookRegistry": "lifecycle_hooks",
    "CredentialPolicyMetadataError": "policy_inputs",
    "build_runtime_execute_policy_request": "policy_inputs",
    "build_runtime_use_credential_policy_request": "policy_inputs",
    "resolve_runtime_credential_policy_metadata": "policy_inputs",
    "PreflightRequest": "preflight",
    "PreflightService": "preflight",
    "run_to_out": "read_model",
    "is_obsolete_runtime_override_token": "removed_runtime_token",
    "RunService": "run_service",
    "RuntimePolicyDecision": "runtime_policy",
    "_norm_risk": "runtime_policy",
    "required_sandbox_level_for_risk": "runtime_policy",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    submodule = _EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{submodule}", __name__)
    value = getattr(module, name)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if TYPE_CHECKING:  # give type checkers / IDEs the concrete symbols
    from .adapter_resolution import ResolvedRuntimeAdapter as ResolvedRuntimeAdapter
    from .execution import RunExecutionService as RunExecutionService
    from .lifecycle_hooks import (
        DuplicateRunFinalizedHookError as DuplicateRunFinalizedHookError,
        RunFinalizedContext as RunFinalizedContext,
        RunFinalizedHookRegistry as RunFinalizedHookRegistry,
    )
    from .policy_inputs import (
        CredentialPolicyMetadataError as CredentialPolicyMetadataError,
        build_runtime_execute_policy_request as build_runtime_execute_policy_request,
        build_runtime_use_credential_policy_request as build_runtime_use_credential_policy_request,
        resolve_runtime_credential_policy_metadata as resolve_runtime_credential_policy_metadata,
    )
    from .preflight import (
        PreflightRequest as PreflightRequest,
        PreflightService as PreflightService,
    )
    from .read_model import run_to_out as run_to_out
    from .removed_runtime_token import (
        is_obsolete_runtime_override_token as is_obsolete_runtime_override_token,
    )
    from .run_service import RunService as RunService
    from .runtime_policy import (
        RuntimePolicyDecision as RuntimePolicyDecision,
        _norm_risk as _norm_risk,
        required_sandbox_level_for_risk as required_sandbox_level_for_risk,
    )
