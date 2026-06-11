"""Public facade for the ``memory`` module.

This re-exports the small set of symbols other modules import today so callers
can depend on ``app.memory`` instead of reaching into internal submodules. Once
callers use the facade, the internal file layout can move without breaking them
— the first concrete step of the TS-first migration seam work (see
``.agent/architecture/TS_MIGRATION_STRATEGY.md``).

**Why lazy (PEP 562 ``__getattr__``) instead of eager re-export:** ``memory`` is
the documented import-cycle hub of the backend — it both is a kernel dependency
and depends on five product modules (``agents``, ``knowledge``, ``intake``,
``evolution``, ``sessions``); see ``MODULE_BOUNDARIES_2026_06_09.md``. Eagerly
importing every submodule from this ``__init__`` would change *when* those
modules load and could turn an existing latent cycle into an ``ImportError``.
Lazy attribute resolution imports the *same* submodule a direct
``from app.memory.<sub> import X`` would, only on first access — so the public
surface exists with **zero** new import-time edges and no runtime behavior
change.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public name -> submodule (relative to this package) that defines it.
# Derived from the symbols other modules import from ``memory`` today.
_EXPORTS: dict[str, str] = {
    "ChatContextBuilder": "chat_context",
    "CodePatchApplyError": "code_patch_apply",
    "CodePatchPartialApplyError": "code_patch_apply",
    "ActivityConsolidationService": "consolidation.service",
    "run_memory_consolidation_job_payload": "consolidation.service",
    "ContextBuilder": "context_builder",
    "ContextCompiler": "context_compiler",
    "TargetFormat": "context_compiler",
    "ContextDigestService": "digest_service",
    "MemoryInternalWriter": "internal_writer",
    "PolicyInternalWriter": "internal_writer",
    "ProvenanceEntry": "proposal_payload",
    "SOURCE_TRUST_VALUES": "proposal_payload",
    "activity_provenance_entry": "proposal_payload",
    "dominant_source_trust": "proposal_payload",
    "first_activity_id": "proposal_payload",
    "merge_distinct_provenance_entries": "proposal_payload",
    "proposal_provenance_entry": "proposal_payload",
    "provenance_entries_from_payload": "proposal_payload",
    "strip_flat_provenance_keys": "proposal_payload",
    "TARGET_KNOWLEDGE": "provenance_apply",
    "TARGET_MEMORY": "provenance_apply",
    "TARGET_POLICY": "provenance_apply",
    "copy_provenance_to_memory": "provenance_apply",
    "record_memory_supersedes_relation": "provenance_apply",
    "source_refs_to_provenance_entries": "provenance_apply",
    "write_provenance_links": "provenance_apply",
    "ReflectorModelProviderMissingError": "provider_client",
    "resolve_reflector_provider_id": "provider_client",
    "SENSITIVITY_LEVELS": "read_auth",
    "VISIBILITY_VALUES": "read_auth",
    "can_read_memory": "read_auth",
    "MemoryReflector": "reflector",
    "seed_system_memories_for_space": "seeder",
    "memory_entry_to_out": "serialization",
    "SourceMonitoringService": "source_monitoring",
    "monitoring_snapshot": "source_monitoring",
    # Interface-only seam over the concrete ``ContextBuilder`` (see ports.py).
    "ContextBuilderPort": "ports",
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
    from .chat_context import ChatContextBuilder as ChatContextBuilder
    from .code_patch_apply import (
        CodePatchApplyError as CodePatchApplyError,
        CodePatchPartialApplyError as CodePatchPartialApplyError,
    )
    from .consolidation.service import (
        ActivityConsolidationService as ActivityConsolidationService,
        run_memory_consolidation_job_payload as run_memory_consolidation_job_payload,
    )
    from .context_builder import ContextBuilder as ContextBuilder
    from .context_compiler import (
        ContextCompiler as ContextCompiler,
        TargetFormat as TargetFormat,
    )
    from .digest_service import ContextDigestService as ContextDigestService
    from .internal_writer import (
        MemoryInternalWriter as MemoryInternalWriter,
        PolicyInternalWriter as PolicyInternalWriter,
    )
    from .ports import ContextBuilderPort as ContextBuilderPort
    from .proposal_payload import (
        ProvenanceEntry as ProvenanceEntry,
        SOURCE_TRUST_VALUES as SOURCE_TRUST_VALUES,
        activity_provenance_entry as activity_provenance_entry,
        dominant_source_trust as dominant_source_trust,
        first_activity_id as first_activity_id,
        merge_distinct_provenance_entries as merge_distinct_provenance_entries,
        proposal_provenance_entry as proposal_provenance_entry,
        provenance_entries_from_payload as provenance_entries_from_payload,
        strip_flat_provenance_keys as strip_flat_provenance_keys,
    )
    from .provenance_apply import (
        TARGET_KNOWLEDGE as TARGET_KNOWLEDGE,
        TARGET_MEMORY as TARGET_MEMORY,
        TARGET_POLICY as TARGET_POLICY,
        copy_provenance_to_memory as copy_provenance_to_memory,
        record_memory_supersedes_relation as record_memory_supersedes_relation,
        source_refs_to_provenance_entries as source_refs_to_provenance_entries,
        write_provenance_links as write_provenance_links,
    )
    from .provider_client import (
        ReflectorModelProviderMissingError as ReflectorModelProviderMissingError,
        resolve_reflector_provider_id as resolve_reflector_provider_id,
    )
    from .read_auth import (
        SENSITIVITY_LEVELS as SENSITIVITY_LEVELS,
        VISIBILITY_VALUES as VISIBILITY_VALUES,
        can_read_memory as can_read_memory,
    )
    from .reflector import MemoryReflector as MemoryReflector
    from .seeder import seed_system_memories_for_space as seed_system_memories_for_space
    from .serialization import memory_entry_to_out as memory_entry_to_out
    from .source_monitoring import (
        SourceMonitoringService as SourceMonitoringService,
        monitoring_snapshot as monitoring_snapshot,
    )
