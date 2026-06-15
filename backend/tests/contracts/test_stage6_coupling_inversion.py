"""Contract: Stage 6 S2 inbound-coupling inversion is in place.

These tests lock the Stage 6 coupling boundary (see
``.agent/architecture/TS_MIGRATION_ROADMAP.md`` and
``TS_CONTROL_PLANE_OWNERSHIP.md``): cross-context callers depend on published
memory/session **facade resolvers + ports**, never on a concrete
memory/session implementation class or an internal submodule path. Keeping the
resolvers as the single binding point is what lets Stage 6 route these surfaces
to the TS ``memory`` / ``sessions`` modules later without touching callers.

No DB is required — the ports are pure structural contracts and the resolvers
return the current Python authority.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.memory import (
    ChatContextBuilderPort,
    ContextBuilderPort,
    get_chat_context_builder,
    get_context_builder,
)
from app.memory.chat_context import ChatContextBuilder
from app.memory.context_builder import ContextBuilder
from app.sessions import SessionWritePort, get_session_write_port
from app.sessions.service import SessionService
from app.intake import ContextEvidencePort, get_context_evidence_port
from app.intake.context_evidence import IntakeContextEvidenceProvider

_APP = Path(__file__).resolve().parents[2] / "app"


def test_concrete_builders_satisfy_ports():
    assert issubclass(ContextBuilder, ContextBuilderPort)
    assert issubclass(ChatContextBuilder, ChatContextBuilderPort)


def test_session_service_satisfies_write_port():
    assert issubclass(SessionService, SessionWritePort)


def test_intake_provider_satisfies_context_evidence_port():
    """memory.ContextBuilder reaches evidence selection through the intake port."""
    assert issubclass(IntakeContextEvidenceProvider, ContextEvidencePort)

    from app.intake import get_context_evidence_port as facade
    from app.intake.ports import get_context_evidence_port as module

    assert facade is module


def test_resolvers_are_reexported_from_facade():
    """Callers reach the resolvers through the package facade, not internals."""
    from app.memory import get_context_builder as mem_facade
    from app.memory.ports import get_context_builder as mem_module
    from app.sessions import get_session_write_port as sess_facade
    from app.sessions.ports import get_session_write_port as sess_module

    assert mem_facade is mem_module
    assert sess_facade is sess_module


def _module_names_imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _is_deep_memory_or_session_import(module_name: str) -> bool:
    normalized = module_name.removeprefix("app.")
    return normalized.startswith("memory.") or normalized.startswith("sessions.")


def test_no_deep_imports_into_session_internals_from_other_contexts():
    """No cross-context caller may import ``sessions.service`` (a session internal).

    The chat turn goes through ``sessions.get_session_write_port`` instead. The
    sessions package and its own tests are exempt.
    """
    offenders: list[str] = []
    for path in _APP.rglob("*.py"):
        rel = path.relative_to(_APP)
        if rel.parts and rel.parts[0] == "sessions":
            continue
        for mod in _module_names_imported(path):
            if mod.endswith("sessions.service"):
                offenders.append(str(rel))
    assert not offenders, f"deep sessions.service imports found: {sorted(set(offenders))}"


def test_watched_contexts_import_memory_and_sessions_only_through_facades():
    """Stage 6 prep allows facade imports but blocks deep memory/session imports.

    Later slice flips can replace facade resolvers with TS ports without editing
    these callers. Module-owned implementation/tests are exempt; this guard
    covers the inbound callers named in the S2 prep gate.
    """
    watched_contexts = {
        "activity",
        "agents",
        "evolution",
        "intake",
        "knowledge",
        "proposals",
        "runs",
    }
    offenders: list[str] = []
    for context in watched_contexts:
        for path in (_APP / context).rglob("*.py"):
            rel = path.relative_to(_APP)
            for module_name in _module_names_imported(path):
                if _is_deep_memory_or_session_import(module_name):
                    offenders.append(f"{rel}: {module_name}")
    assert not offenders, (
        "cross-context callers must use app.memory/app.sessions facades, "
        f"not internals: {sorted(offenders)}"
    )


def test_memory_does_not_deep_import_intake_internals():
    """memory uses the published intake port, not intake.evidence_selector/service."""
    deep = {"intake.evidence_selector", "intake.service"}
    offenders: list[str] = []
    memory_dir = _APP / "memory"
    for path in memory_dir.rglob("*.py"):
        for mod in _module_names_imported(path):
            if any(mod.endswith(target) for target in deep):
                offenders.append(str(path.relative_to(_APP)))
    assert not offenders, f"deep intake imports in memory: {sorted(set(offenders))}"
