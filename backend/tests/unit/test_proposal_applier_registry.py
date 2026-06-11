"""ProposalApplierRegistry — dispatch mechanics, coverage, and legacy-dispatch removal.

Covers:
- registration mechanics (duplicate/invalid fail fast, sorted key listing)
- dispatch mechanics (registered applier invoked once, async appliers awaited,
  applier exceptions propagate unchanged)
- unknown-type failure semantics (UnknownProposalApplierError is a
  ProposalApplyError carrying the legacy ``unsupported proposal type`` message)
- default registry coverage: every previously supported proposal type is
  registered exactly once by its owning module and matches the policy risk
  table (SUPPORTED_PROPOSAL_TYPES)
- the policy apply gate derives supported-ness from the registry
- no legacy hardcoded per-type apply dispatch remains in
  ``ProposalApplyService.apply``
- the proposals public facade exports the registry API
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.proposals import (
    DuplicateProposalApplierError,
    InvalidProposalApplierError,
    ProposalApplierRegistry,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
    UnknownProposalApplierError,
    get_proposal_applier_registry,
)
from app.proposals.applier_registry import init_registry, reset_registry


BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class _FakeProposal:
    proposal_type: str
    id: str = "prop-1"
    space_id: str = "space-1"


def _context(proposal_type: str) -> ProposalApplyContext:
    return ProposalApplyContext(db=None, proposal=_FakeProposal(proposal_type), user_id="user-1")


# ---------------------------------------------------------------------------
# Registration mechanics
# ---------------------------------------------------------------------------


def test_register_and_get_and_listing_sorted():
    registry = ProposalApplierRegistry()
    b = lambda ctx: ProposalApplyResult(proposal=ctx.proposal)  # noqa: E731
    a = lambda ctx: ProposalApplyResult(proposal=ctx.proposal)  # noqa: E731
    registry.register("type_b", b)
    registry.register("type_a", a)

    assert registry.get("type_a") is a
    assert registry.get("type_b") is b
    assert registry.get("missing") is None
    assert registry.registered_appliers() == ["type_a", "type_b"]


def test_duplicate_registration_fails_fast():
    registry = ProposalApplierRegistry()
    registry.register("memory_create", lambda ctx: ProposalApplyResult())
    with pytest.raises(DuplicateProposalApplierError) as excinfo:
        registry.register("memory_create", lambda ctx: ProposalApplyResult())
    assert excinfo.value.proposal_type == "memory_create"


def test_invalid_registration_fails_fast():
    registry = ProposalApplierRegistry()
    with pytest.raises(InvalidProposalApplierError):
        registry.register("", lambda ctx: ProposalApplyResult())
    with pytest.raises(InvalidProposalApplierError):
        registry.register(None, lambda ctx: ProposalApplyResult())  # type: ignore[arg-type]
    with pytest.raises(InvalidProposalApplierError):
        registry.register("memory_create", "not-callable")  # type: ignore[arg-type]


def test_clear_drops_registrations():
    registry = ProposalApplierRegistry()
    registry.register("memory_create", lambda ctx: ProposalApplyResult())
    registry.clear()
    assert registry.registered_appliers() == []


# ---------------------------------------------------------------------------
# Dispatch mechanics
# ---------------------------------------------------------------------------


def test_registered_applier_invoked_exactly_once_with_context():
    registry = ProposalApplierRegistry()
    calls: list[ProposalApplyContext] = []

    def applier(ctx: ProposalApplyContext) -> ProposalApplyResult:
        calls.append(ctx)
        return ProposalApplyResult(proposal=ctx.proposal, egress_review=True)

    registry.register("egress_review", applier)
    context = _context("egress_review")
    result = registry.apply(context)

    assert len(calls) == 1
    assert calls[0] is context
    assert result.proposal is context.proposal
    assert result.egress_review is True


def test_async_applier_is_awaited():
    registry = ProposalApplierRegistry()

    async def applier(ctx: ProposalApplyContext) -> ProposalApplyResult:
        return ProposalApplyResult(proposal=ctx.proposal, task="task-sentinel")

    registry.register("follow_up_task", applier)
    result = registry.apply(_context("follow_up_task"))
    assert result.task == "task-sentinel"


def test_unknown_type_raises_typed_error_with_legacy_message():
    registry = ProposalApplierRegistry()
    with pytest.raises(UnknownProposalApplierError, match="unsupported proposal type"):
        registry.apply(_context("workspace_profile_update"))

    err = UnknownProposalApplierError("workspace_profile_update")
    # Failure semantics preserved: callers catching ProposalApplyError (the
    # accept boundary's rollback → HTTP 422 path) keep working, and the
    # message matches the pre-registry central dispatch exactly.
    assert isinstance(err, ProposalApplyError)
    assert str(err) == "unsupported proposal type: 'workspace_profile_update'"
    assert err.proposal_type == "workspace_profile_update"


def test_applier_exception_propagates_unchanged():
    registry = ProposalApplierRegistry()

    class CustomApplyFailure(ProposalApplyError):
        pass

    def applier(ctx: ProposalApplyContext) -> ProposalApplyResult:
        raise CustomApplyFailure("target memory missing")

    registry.register("memory_update", applier)
    with pytest.raises(CustomApplyFailure, match="target memory missing"):
        registry.apply(_context("memory_update"))


def test_non_apply_error_exceptions_also_propagate_unchanged():
    registry = ProposalApplierRegistry()

    class FileWriteFailure(Exception):
        """Stands in for CodePatchApplyError: not a ProposalApplyError."""

    registry.register("code_patch", lambda ctx: (_ for _ in ()).throw(FileWriteFailure("boom")))
    with pytest.raises(FileWriteFailure, match="boom"):
        registry.apply(_context("code_patch"))


# ---------------------------------------------------------------------------
# Default registry coverage — every supported type registered exactly once
# ---------------------------------------------------------------------------


EXPECTED_APPLIER_OWNERS = {
    "memory": {
        "memory_create",
        "memory_update",
        "memory_archive",
        "policy_change",
        "code_patch",
        "follow_up_task",
        "egress_review",
    },
    "knowledge": {
        "knowledge_create",
        "knowledge_update",
        "knowledge_archive",
        "knowledge_relation_create",
        "knowledge_relation_delete",
    },
    "agents": {"agent_config_update"},
    "evolution": {"prompt_update"},
}


def test_default_registry_covers_all_supported_types_exactly_once():
    from app.modules.registry import register_proposal_appliers
    from app.policy import SUPPORTED_PROPOSAL_TYPES

    registry = ProposalApplierRegistry()
    loaded = register_proposal_appliers(registry)

    # Duplicate registration raises, so a successful build implies unique keys.
    assert sorted(loaded) == sorted(EXPECTED_APPLIER_OWNERS)
    assert frozenset(registry.registered_appliers()) == SUPPORTED_PROPOSAL_TYPES

    expected_keys = set().union(*EXPECTED_APPLIER_OWNERS.values())
    assert set(registry.registered_appliers()) == expected_keys


def test_each_owning_module_registers_its_own_types():
    for module_id, expected_types in EXPECTED_APPLIER_OWNERS.items():
        import importlib

        mod = importlib.import_module(f"app.{module_id}.proposal_appliers")
        registry = ProposalApplierRegistry()
        mod.register_proposal_appliers(registry)
        assert set(registry.registered_appliers()) == expected_types, module_id


def test_apply_service_supported_types_reflects_registry():
    from app.proposals import ProposalApplyService
    from app.policy import SUPPORTED_PROPOSAL_TYPES

    assert ProposalApplyService.supported_types() == SUPPORTED_PROPOSAL_TYPES


def test_process_wide_registry_lazy_build_and_init_override():
    previous = get_proposal_applier_registry()
    try:
        isolated = ProposalApplierRegistry()
        isolated.register("memory_create", lambda ctx: ProposalApplyResult())
        init_registry(isolated)
        assert get_proposal_applier_registry() is isolated

        reset_registry()
        rebuilt = get_proposal_applier_registry()
        assert "memory_create" in rebuilt.registered_appliers()
        assert "prompt_update" in rebuilt.registered_appliers()
    finally:
        init_registry(previous)


# ---------------------------------------------------------------------------
# Policy gate derives supported-ness from the registry
# ---------------------------------------------------------------------------


def test_policy_gate_supported_check_follows_registry():
    from app.policy.proposal_apply import _supported_proposal_types

    previous = get_proposal_applier_registry()
    try:
        partial = ProposalApplierRegistry()
        partial.register("memory_create", lambda ctx: ProposalApplyResult())
        init_registry(partial)
        assert _supported_proposal_types() == frozenset({"memory_create"})
    finally:
        init_registry(previous)
    from app.policy import SUPPORTED_PROPOSAL_TYPES

    assert _supported_proposal_types() == SUPPORTED_PROPOSAL_TYPES


# ---------------------------------------------------------------------------
# Legacy dispatch removal — no hardcoded per-type apply branch remains
# ---------------------------------------------------------------------------


def _method_ast(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


def test_no_legacy_hardcoded_apply_dispatch_remains():
    """``ProposalApplyService.apply`` must contain no proposal-type string
    comparisons or per-type branches — all type dispatch goes through the
    registry. (Cross-cutting helpers like source monitoring / digest marking
    keep their own per-type behavior; only the apply dispatch is guarded.)"""
    from app.policy import SUPPORTED_PROPOSAL_TYPES

    apply_service = BACKEND_ROOT / "app" / "proposals" / "apply_service.py"
    apply_method = _method_ast(apply_service, "ProposalApplyService", "apply")

    proposal_type_constants = [
        node.value
        for node in ast.walk(apply_method)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in SUPPORTED_PROPOSAL_TYPES
    ]
    assert proposal_type_constants == [], (
        "ProposalApplyService.apply still references proposal-type literals; "
        f"found {proposal_type_constants!r} — dispatch must go through "
        "ProposalApplierRegistry"
    )

    source = apply_service.read_text(encoding="utf-8")
    assert "SUPPORTED_PROPOSAL_TYPES" not in source, (
        "apply_service must not duplicate the supported-type set; "
        "supported-ness is registry membership"
    )

    # The old central dispatch imported the knowledge module directly; the
    # knowledge appliers now register through app.knowledge.proposal_appliers.
    tree = ast.parse(source, filename=str(apply_service))
    knowledge_imports = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.ImportFrom) and "knowledge" in (node.module or ""))
        or (isinstance(node, ast.Import) and any("knowledge" in a.name for a in node.names))
    ]
    assert knowledge_imports == [], (
        f"apply_service must not import the knowledge module (lines {knowledge_imports})"
    )


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


def test_proposals_facade_exports_registry_api():
    import app.proposals as proposals

    for name in (
        "ProposalApplierRegistry",
        "ProposalApplier",
        "ProposalApplierKey",
        "ProposalApplyContext",
        "ProposalApplyResult",
        "ProposalApplyError",
        "DuplicateProposalApplierError",
        "UnknownProposalApplierError",
        "get_proposal_applier_registry",
    ):
        assert name in proposals.__all__, name
        assert getattr(proposals, name) is not None, name


def test_proposals_facade_reexports_apply_error_and_result():
    """The proposals facade exposes the apply boundary result and error."""
    from app.proposals import ApplyResult, ProposalApplyError as ReExported

    assert ReExported is ProposalApplyError
    assert ApplyResult is ProposalApplyResult
