"""Invariant: business enforcement code must not bypass PolicyGateway.

Direct authorization use of PolicyEngine, default_engine, or HardInvariantGuard
is only permitted in:
  - core/backend/app/policy/**  (the policy package itself)
  - core/backend/app/runs/preflight.py  (dry-run simulation, no side effects)
  - core/backend/app/runs/run_service.py  (non-mutating preflight in create_run,
      no PolicyDecisionRecord — real enforcement in RunExecutionService)
  - core/backend/app/agents/agent_service.py  (non-mutating preflight before
      queuing a run — no PolicyDecisionRecord — real enforcement in RunExecutionService)
  - core/backend/app/automation/policy_preflight.py  (non-mutating automation
      policy preflight simulation — no PolicyDecisionRecord)
  - tests/**

Any other location that imports, instantiates, or accesses these directly is a
policy enforcement boundary violation. This test scans all Python source files
with a precise AST pass and fails with a clear violation report if any are found.

Flagged patterns (outside allowed paths):
  - Import / ImportFrom that binds a forbidden name
  - Call node whose func is a forbidden Name (PolicyEngine(...), HardInvariantGuard(...))
  - Attribute access on default_engine (obj.default_engine[...])

Not flagged:
  - Ordinary Name usage in type annotations or non-call expressions
"""
from __future__ import annotations

import ast
import pathlib
import textwrap
from typing import NamedTuple


_REPO_ROOT = pathlib.Path(__file__).parents[4]
_APP_ROOT = _REPO_ROOT / "core" / "backend" / "app"

# Names whose import or instantiation-via-Call constitutes a violation.
_FORBIDDEN_NAMES = frozenset({"PolicyEngine", "HardInvariantGuard"})
# Attribute names whose access constitutes a violation.
_FORBIDDEN_ATTRS = frozenset({"default_engine"})

# Allowed paths (relative to _APP_ROOT).
# Non-policy exceptions must be non-mutating simulations only (no PolicyDecisionRecord).
# Real sensitive-action enforcement goes through PolicyGateway.enforce() paths.
_ALLOWED_RELATIVE = frozenset({
    "policy",                   # entire policy/ package
    "runs/preflight.py",        # dry-run simulation; no PolicyDecisionRecord persisted
    "runs/run_service.py",      # non-mutating preflight in create_run; no PolicyDecisionRecord
    "agents/agent_service.py",  # non-mutating preflight before queuing; no PolicyDecisionRecord
    "automation/policy_preflight.py",  # non-mutating automation policy preflight simulation
})


class Violation(NamedTuple):
    rel_path: str
    lineno: int
    symbol: str
    context: str


def _is_allowed(path: pathlib.Path) -> bool:
    try:
        rel = path.relative_to(_APP_ROOT)
    except ValueError:
        return True  # outside app root — not business code
    parts = rel.parts
    if parts and parts[0] == "policy":
        return True
    rel_str = str(rel)
    if rel_str in _ALLOWED_RELATIVE:
        return True
    return False


def _scan_file(path: pathlib.Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return []

    violations: list[Violation] = []
    lines = source.splitlines()

    def _add(lineno: int, symbol: str) -> None:
        raw = lines[lineno - 1] if lineno <= len(lines) else ""
        if raw.lstrip().startswith("#"):
            return
        violations.append(Violation(
            rel_path=str(path.relative_to(_REPO_ROOT)),
            lineno=lineno,
            symbol=symbol,
            context=raw.rstrip(),
        ))

    # Track Attribute nodes already reported via a parent Call to suppress duplicates.
    _reported_attr_ids: set[int] = set()

    for node in ast.walk(tree):

        # 1. Import / ImportFrom that binds a forbidden name into scope.
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[-1]
                if bound in _FORBIDDEN_NAMES or bound in _FORBIDDEN_ATTRS:
                    _add(node.lineno, bound)

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                if bound in _FORBIDDEN_NAMES or bound in _FORBIDDEN_ATTRS:
                    _add(node.lineno, bound)

        # 2. Call that instantiates a forbidden class or invokes via default_engine.
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
                _add(node.lineno, func.id)
            elif isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_ATTRS:
                _add(node.lineno, func.attr)
                _reported_attr_ids.add(id(func))

        # 3. Attribute access to default_engine not already reported via a Call.
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRS and id(node) not in _reported_attr_ids:
                _add(node.lineno, node.attr)

    return violations


def test_no_direct_policy_engine_usage_outside_allowed_locations() -> None:
    """Scan app source for PolicyEngine / HardInvariantGuard imports, calls, and attribute access.

    Flags:
      - Import / ImportFrom of forbidden names outside allowed paths.
      - Call nodes that instantiate PolicyEngine or HardInvariantGuard.
      - Attribute accesses of default_engine.

    Does not flag ordinary Name usage in type annotations or non-call expressions.

    Fails with a human-readable report listing every violation so they can all
    be fixed at once rather than one at a time.
    """
    all_violations: list[Violation] = []

    for py_file in sorted(_APP_ROOT.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        if _is_allowed(py_file):
            continue
        violations = _scan_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        return

    report_lines = [
        "",
        "PolicyGateway enforcement boundary violations found.",
        "Business enforcement code must call PolicyGateway.enforce() or enforce_proposal_apply().",
        "Direct PolicyEngine / HardInvariantGuard / default_engine is only allowed in:",
        "  app/policy/*, app/runs/preflight.py, app/runs/run_service.py (non-mutating),",
        "  app/agents/agent_service.py, app/automation/policy_preflight.py",
        "  (non-mutating preflight simulation, no PolicyDecisionRecord).",
        "",
        f"{'File':<60} {'Line':>5}  Symbol",
        "-" * 80,
    ]
    for v in all_violations:
        report_lines.append(f"{v.rel_path:<60} {v.lineno:>5}  {v.symbol}")
        report_lines.append(f"       {v.context}")
    report_lines.append("")

    assert not all_violations, textwrap.dedent("\n".join(report_lines))


def test_sensitive_services_use_current_policy_gateway_methods() -> None:
    """Sensitive enforcement paths must call the current gateway methods."""
    checks = (
        (
            "runs/execution.py",
            "RunExecutionService",
            None,
            "enforce(",
        ),
        (
            "memory/proposals.py",
            "ProposalService",
            "create_proposal",
            "enforce(",
        ),
        (
            "memory/proposals.py",
            "ProposalService",
            "accept",
            "enforce_proposal_apply(",
        ),
        (
            "automation/service.py",
            "AutomationService",
            "create",
            "enforce(",
        ),
        (
            "automation/service.py",
            "AutomationService",
            "update",
            "enforce(",
        ),
        (
            "automation/service.py",
            "AutomationService",
            "fire",
            "enforce(",
        ),
        (
            "runs/context_snapshot_populator.py",
            "ContextSnapshotPopulator",
            "populate",
            "enforce(",
        ),
        (
            "runs/artifact_persistence.py",
            None,
            None,
            "enforce(",
        ),
        (
            "memory/code_patch_apply.py",
            None,
            None,
            "enforce(",
        ),
        (
            "runs/code_patch_collector.py",
            None,
            None,
            "enforce(",
        ),
    )

    for rel_path, class_name, method_name, expected_call in checks:
        source = (_APP_ROOT / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        if class_name:
            klass = next(
                node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            if method_name:
                nodes = [
                    node for node in klass.body
                    if isinstance(node, ast.FunctionDef) and node.name == method_name
                ]
            else:
                nodes = [klass]
        else:
            nodes = []
        scoped_source = (
            "\n".join(ast.get_source_segment(source, node) or "" for node in nodes)
            if nodes
            else source
        )
        assert expected_call in scoped_source, f"{class_name} is missing {expected_call}"
