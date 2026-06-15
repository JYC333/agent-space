"""Static module-boundary guard for backend Python imports.

This guard rejects cross-package deep imports, obvious package import cycles,
and reintroduced retired dispatch paths. Keep the deep-import allowlist empty by
default; add narrow public facades or ports instead of expanding exceptions.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


# Keep this empty by default. Prefer adding a facade to the target package over
# adding a new exception.
DOCUMENTED_DEEP_IMPORT_ALLOWLIST: set[tuple[str, str]] = set()


@dataclass(frozen=True)
class ImportRef:
    source_package: str
    source_path: str
    module: str
    lineno: int


def _backend_packages() -> set[str]:
    return {
        path.name
        for path in APP_ROOT.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }


def _submodules(packages: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for package in packages:
        package_root = APP_ROOT / package
        result[package] = {
            path.stem
            for path in package_root.glob("*.py")
            if path.stem != "__init__"
        } | {
            path.name
            for path in package_root.iterdir()
            if path.is_dir() and path.name != "__pycache__"
        }
    return result


def _resolve_relative_import(path: Path, node: ast.ImportFrom) -> list[str]:
    rel_parts = list(path.relative_to(APP_ROOT).with_suffix("").parts)
    if rel_parts[-1] == "__init__":
        rel_parts = rel_parts[:-1]
    base = rel_parts[: max(0, len(rel_parts) - node.level + 1)]
    suffix = node.module.split(".") if node.module else []
    return ["app", *base, *suffix]


def _iter_import_refs() -> list[ImportRef]:
    packages = _backend_packages()
    package_submodules = _submodules(packages)
    refs: list[ImportRef] = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT)
        if "__pycache__" in rel.parts or len(rel.parts) < 2:
            continue

        source_package = rel.parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            specs: list[tuple[list[str], int]] = []
            if isinstance(node, ast.Import):
                specs.extend((alias.name.split("."), node.lineno) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = (
                    (node.module or "").split(".")
                    if node.level == 0
                    else _resolve_relative_import(path, node)
                )
                if not base or base[0] != "app":
                    continue
                specs.append((base, node.lineno))

                # Catch `from app.package import submodule` as a deep import when
                # the imported name is a real submodule.
                if len(base) == 2 and base[1] in package_submodules:
                    for alias in node.names:
                        if alias.name in package_submodules[base[1]]:
                            specs.append(([*base, alias.name], node.lineno))

            for parts, lineno in specs:
                if len(parts) < 2 or parts[0] != "app" or parts[1] not in packages:
                    continue
                if parts[1] == source_package:
                    continue
                refs.append(
                    ImportRef(
                        source_package=source_package,
                        source_path=path.relative_to(APP_ROOT).as_posix(),
                        module=".".join(parts),
                        lineno=lineno,
                    )
                )

    return refs


def _first_three_parts(module: str) -> str:
    return ".".join(module.split(".")[:3])


def _cross_package_edges(refs: list[ImportRef]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for ref in refs:
        parts = ref.module.split(".")
        if len(parts) >= 2:
            edges.add((ref.source_package, parts[1]))
    return edges


def _cycles(edges: set[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for source, target in edges:
        graph[source].add(target)
        nodes.add(source)
        nodes.add(target)

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in graph[node]:
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])

        if lowlinks[node] == indexes[node]:
            component: list[str] = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(nodes):
        if node not in indexes:
            visit(node)

    return sorted(components)


def test_no_new_cross_package_deep_imports():
    refs = _iter_import_refs()
    current = {
        (ref.source_path, _first_three_parts(ref.module))
        for ref in refs
        if len(ref.module.split(".")) >= 3
    }

    new_violations = sorted(current - DOCUMENTED_DEEP_IMPORT_ALLOWLIST)
    stale_allowlist = sorted(DOCUMENTED_DEEP_IMPORT_ALLOWLIST - current)

    assert not new_violations, (
        "New cross-package deep imports detected. Import the target package facade "
        "instead, or document a narrow exception if there is no safe facade yet:\n"
        + "\n".join(f"- {path} imports {module}" for path, module in new_violations)
    )
    assert not stale_allowlist, (
        "Documented deep-import exceptions no longer exist; remove them from the "
        "allowlist:\n"
        + "\n".join(f"- {path} imports {module}" for path, module in stale_allowlist)
    )


def test_no_obvious_cross_package_import_cycles():
    refs = _iter_import_refs()
    cycles = _cycles(_cross_package_edges(refs))

    assert cycles == [], (
        "Cross-package import cycles detected. Invert the dependency through a "
        "facade, callback, registry, or port:\n"
        + "\n".join(f"- {' -> '.join(cycle)}" for cycle in cycles)
    )


# ---------------------------------------------------------------------------
# runtimes -> runs boundary (cycle inversion guard)
# ---------------------------------------------------------------------------

# app.* modules/packages runtimes may import. runtimes is a lower-level
# execution package: run evidence and process registration flow only through
# app.runtimes.ports implementations injected by the runs-owned composition
# root (app.runs.runtime_bridge) — never by importing app.runs.
RUNTIMES_ALLOWED_APP_IMPORTS: set[str] = {
    "capabilities",
    "config",
    "credentials",
    "memory",
    "models",
    "providers",
    "secrets",
}

# ORM names runtimes must never import from app.models: RunEvent persistence
# is owned by runs (reached via RuntimeEventSink only).
RUNTIMES_FORBIDDEN_MODEL_NAMES: set[str] = {"RunEvent"}


def _resolve_module_import(path: Path, node: ast.ImportFrom) -> list[str]:
    """PEP 328-exact resolution for any module file (``_resolve_relative_import``
    above is exact only for ``__init__.py``; it is kept as-is to avoid
    re-baselining the snapshot guard)."""
    if node.level == 0:
        return (node.module or "").split(".")
    package_parts = list(path.relative_to(APP_ROOT).with_suffix("").parts)[:-1]
    base = package_parts[: len(package_parts) - (node.level - 1)]
    suffix = node.module.split(".") if node.module else []
    return ["app", *base, *suffix]


def test_runtimes_package_does_not_import_runs():
    """backend/app/runtimes/** must not import app.runs (events, process
    registry, or anything else), must not import the RunEvent ORM model, and
    may only import the documented lower-level/shared app modules."""
    offenders: list[str] = []

    for path in sorted((APP_ROOT / "runtimes").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(APP_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            targets: list[tuple[list[str], list[ast.alias]]] = []
            if isinstance(node, ast.Import):
                targets.extend((alias.name.split("."), []) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                targets.append((_resolve_module_import(path, node), node.names))

            for parts, aliases in targets:
                if not parts or parts[0] != "app" or len(parts) < 2:
                    continue
                target = parts[1]
                module = ".".join(parts)
                if target == "runs":
                    offenders.append(f"{rel}:{node.lineno} imports {module}")
                elif target == "runtimes":
                    continue
                elif target not in RUNTIMES_ALLOWED_APP_IMPORTS:
                    offenders.append(
                        f"{rel}:{node.lineno} imports {module} "
                        "(not in RUNTIMES_ALLOWED_APP_IMPORTS)"
                    )
                if target == "models":
                    for alias in aliases:
                        if alias.name in RUNTIMES_FORBIDDEN_MODEL_NAMES:
                            offenders.append(
                                f"{rel}:{node.lineno} imports {alias.name} from app.models"
                            )

    assert offenders == [], (
        "runtimes must stay a lower-level execution package (runs -> runtimes "
        "only; evidence/process registration via app.runtimes.ports):\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


# ---------------------------------------------------------------------------
# runs <-> tasks boundary (cycle inversion guard)
# ---------------------------------------------------------------------------

def _imports_of_package(package: str) -> list[tuple[str, int, list[str]]]:
    """All ``app.*`` import targets in ``backend/app/<package>/**`` with
    PEP 328-exact relative resolution: (source_path, lineno, parts)."""
    packages = _backend_packages()
    package_submodules = _submodules(packages)
    results: list[tuple[str, int, list[str]]] = []
    for path in sorted((APP_ROOT / package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(APP_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for lineno, parts in _expanded_app_import_targets(
                path,
                node,
                packages=packages,
                package_submodules=package_submodules,
            ):
                results.append((rel, lineno, parts))
    return results


def _expanded_app_import_targets(
    path: Path,
    node: ast.AST,
    *,
    packages: set[str],
    package_submodules: dict[str, set[str]],
) -> list[tuple[int, list[str]]]:
    """Return import targets, including aliases that name packages/submodules.

    ``from app import tasks`` imports ``app.tasks`` even though the AST base is
    only ``app``. Likewise, ``from app.runs import finalization`` deep-imports
    ``app.runs.finalization`` when ``finalization`` is a real submodule.
    """
    targets: list[tuple[int, list[str]]] = []
    if isinstance(node, ast.Import):
        targets.extend((node.lineno, alias.name.split(".")) for alias in node.names)
        return targets
    if not isinstance(node, ast.ImportFrom):
        return targets

    base = _resolve_module_import(path, node)
    targets.append((node.lineno, base))
    if base == ["app"]:
        for alias in node.names:
            if alias.name in packages:
                targets.append((node.lineno, ["app", alias.name]))
    elif len(base) == 2 and base[0] == "app" and base[1] in package_submodules:
        for alias in node.names:
            if alias.name in package_submodules[base[1]]:
                targets.append((node.lineno, [*base, alias.name]))
    return targets


def test_import_target_expansion_catches_from_import_aliases():
    path = APP_ROOT / "runs" / "example.py"
    tree = ast.parse(
        "\n".join(
            [
                "from app import tasks",
                "from .. import tasks as task_module",
                "from app.runs import finalization",
            ]
        )
    )
    packages = {"runs", "tasks"}
    package_submodules = {"runs": {"finalization"}, "tasks": set()}

    expanded = [
        parts
        for node in ast.walk(tree)
        for _, parts in _expanded_app_import_targets(
            path,
            node,
            packages=packages,
            package_submodules=package_submodules,
        )
    ]

    assert ["app", "tasks"] in expanded
    assert ["app", "runs", "finalization"] in expanded


def test_runs_package_does_not_import_tasks():
    """``runs`` owns execution lifecycle/finalization/output; task-board side
    effects reach finalization only through tasks-registered hooks on the
    runs-owned ``app.runs.lifecycle_hooks.RunFinalizedHookRegistry``. Any
    ``runs -> tasks`` import re-creates the removed cycle."""
    offenders = [
        f"{rel}:{lineno} imports {'.'.join(parts)}"
        for rel, lineno, parts in _imports_of_package("runs")
        if len(parts) >= 2 and parts[0] == "app" and parts[1] == "tasks"
    ]
    assert offenders == [], (
        "runs must not import tasks (dependency direction is tasks -> runs; "
        "post-run side effects go through RunFinalizedHookRegistry):\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_tasks_imports_runs_only_via_public_facade():
    """``tasks`` may depend on ``runs`` only through the ``app.runs`` facade —
    never by deep-importing runs internals."""
    offenders = [
        f"{rel}:{lineno} imports {'.'.join(parts)}"
        for rel, lineno, parts in _imports_of_package("tasks")
        if len(parts) >= 3 and parts[0] == "app" and parts[1] == "runs"
    ]
    assert offenders == [], (
        "tasks must import runs through the app.runs facade only:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


# ---------------------------------------------------------------------------
# router ownership guard
# ---------------------------------------------------------------------------

def test_router_consumers_use_public_facade():
    """Intent/task/adapter routing decisions are owned by ``app.router``.

    Other packages may consume the public facade, but must not deep-import
    router internals. ``RouterService`` is the single routing owner.
    """
    offenders: list[str] = []
    for package in _backend_packages() - {"router"}:
        for rel, lineno, parts in _imports_of_package(package):
            if len(parts) >= 3 and parts[0] == "app" and parts[1] == "router":
                offenders.append(f"{rel}:{lineno} imports {'.'.join(parts)}")

    assert offenders == [], (
        "router consumers must import routing decisions through app.router:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_router_has_no_retired_wrapper_modules():
    """The pre-convergence ``IntentRouter`` / ``TaskRouter`` wrappers are gone.

    Reintroducing them would create a second public dispatch surface for routing
    behavior that now belongs to ``RouterService``.
    """
    stale_paths = [
        path.relative_to(APP_ROOT).as_posix()
        for path in (
            APP_ROOT / "router" / "intent_router.py",
            APP_ROOT / "router" / "task_router.py",
        )
        if path.exists()
    ]

    assert stale_paths == [], (
        "retired router wrapper modules must not be reintroduced:\n"
        + "\n".join(f"- {path}" for path in stale_paths)
    )


# ---------------------------------------------------------------------------
# model_api / provider ownership guards
# ---------------------------------------------------------------------------

def test_model_api_adapter_uses_provider_public_facade_only():
    """``model_api`` adapts runtime execution to provider invocation.

    It may import ``app.providers`` public exports, but must not reach into
    provider internals or import runs internals directly.
    """
    path = APP_ROOT / "runtimes" / "adapters" / "model_api.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    packages = _backend_packages()
    package_submodules = _submodules(packages)
    for node in ast.walk(tree):
        for lineno, parts in _expanded_app_import_targets(
            path,
            node,
            packages=packages,
            package_submodules=package_submodules,
        ):
            if len(parts) >= 3 and parts[0] == "app" and parts[1] == "providers":
                offenders.append(
                    f"runtimes/adapters/model_api.py:{lineno} imports {'.'.join(parts)}"
                )
            if len(parts) >= 2 and parts[0] == "app" and parts[1] == "runs":
                offenders.append(
                    f"runtimes/adapters/model_api.py:{lineno} imports {'.'.join(parts)}"
                )

    assert offenders == [], (
        "model_api must use provider public facade exports and runtime ports only:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_providers_package_does_not_import_runtimes_or_run_execution():
    """Providers own model invocation and provider credentials.

    The dependency direction is runtimes -> providers for the ``model_api``
    adapter, not providers -> runtimes. Providers must also stay out of run
    execution lifecycle internals.
    """
    offenders: list[str] = []
    for rel, lineno, parts in _imports_of_package("providers"):
        if len(parts) >= 2 and parts[0] == "app" and parts[1] == "runtimes":
            offenders.append(f"{rel}:{lineno} imports {'.'.join(parts)}")
        if len(parts) >= 3 and parts[:3] == ["app", "runs", "execution"]:
            offenders.append(f"{rel}:{lineno} imports {'.'.join(parts)}")

    assert offenders == [], (
        "providers must not import runtimes or run execution internals:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


# ---------------------------------------------------------------------------
# proposal applier registry boundary
# ---------------------------------------------------------------------------

def _app_imports_of_file(path: Path) -> list[tuple[int, list[str]]]:
    """All ``app.*`` import targets in one module file, PEP 328-exact."""
    packages = _backend_packages()
    package_submodules = _submodules(packages)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    results: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        for lineno, parts in _expanded_app_import_targets(
            path,
            node,
            packages=packages,
            package_submodules=package_submodules,
        ):
            if parts and parts[0] == "app" and len(parts) >= 2:
                results.append((lineno, parts))
    return results


# app.* targets proposals/applier_registry.py may import. The registry owns
# dispatch mechanics only: its single allowed app dependency is the lazy
# default-build hook into the backend module registry.
PROPOSAL_REGISTRY_ALLOWED_APP_IMPORTS: set[str] = {"modules"}


def test_proposal_applier_registry_imports_no_product_modules():
    """``app.proposals.applier_registry`` must never import memory, knowledge,
    policy, or any other product module — appliers reach it through
    module-owned ``register_proposal_appliers(registry)`` hooks only."""
    path = APP_ROOT / "proposals" / "applier_registry.py"
    offenders = [
        f"proposals/applier_registry.py:{lineno} imports {'.'.join(parts)}"
        for lineno, parts in _app_imports_of_file(path)
        if parts[1] not in PROPOSAL_REGISTRY_ALLOWED_APP_IMPORTS
    ]
    assert offenders == [], (
        "proposals/applier_registry.py owns dispatch mechanics only and must "
        "not import product modules:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_proposals_api_and_read_model_do_not_import_apply_internals():
    """``proposals/api.py`` and ``proposals/read_model.py`` may use the
    ``app.memory`` facade and ``app.knowledge.read_model`` (read model to read
    model), but must not import memory/knowledge/code-patch apply internals or
    any module's ``proposal_appliers`` registration hook."""
    offenders: list[str] = []
    for filename in ("api.py", "read_model.py"):
        path = APP_ROOT / "proposals" / filename
        for lineno, parts in _app_imports_of_file(path):
            module = ".".join(parts)
            if parts[1] == "memory" and len(parts) >= 3:
                offenders.append(f"proposals/{filename}:{lineno} imports {module}")
            elif parts[1] == "knowledge" and len(parts) >= 3 and parts[2] != "read_model":
                offenders.append(f"proposals/{filename}:{lineno} imports {module}")
            elif len(parts) >= 3 and parts[2] == "proposal_appliers":
                offenders.append(f"proposals/{filename}:{lineno} imports {module}")

    assert offenders == [], (
        "proposals API/read model must not import apply internals (use the "
        "registry result / package facades instead):\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_policy_package_does_not_import_appliers_or_apply_service():
    """``policy`` owns the proposal.apply gate and audit semantics. It may
    consult the proposal registry public API, but must never import the apply
    service or any module's appliers — that would re-create type dispatch in
    the gate."""
    offenders: list[str] = []
    for rel, lineno, parts in _imports_of_package("policy"):
        module = ".".join(parts)
        if parts[:3] == ["app", "memory", "apply_service"]:
            offenders.append(f"{rel}:{lineno} imports {module}")
        elif len(parts) >= 3 and parts[2] == "proposal_appliers":
            offenders.append(f"{rel}:{lineno} imports {module}")

    assert offenders == [], (
        "policy must consult the ProposalApplierRegistry public API only:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )


def test_proposal_applier_modules_import_registry_via_facade():
    """Modules registering proposal appliers import the registry types through
    the ``app.proposals`` facade — never by deep-importing
    ``app.proposals.applier_registry`` (the composition root in ``app.main``
    is the only intended consumer of the registry lifecycle functions)."""
    offenders: list[str] = []
    for package in _backend_packages():
        applier_file = APP_ROOT / package / "proposal_appliers.py"
        if not applier_file.exists():
            continue
        for lineno, parts in _app_imports_of_file(applier_file):
            if parts[1] == "proposals" and len(parts) >= 3:
                offenders.append(
                    f"{package}/proposal_appliers.py:{lineno} imports {'.'.join(parts)}"
                )

    assert offenders == [], (
        "proposal applier modules must import registry types via the "
        "app.proposals facade:\n"
        + "\n".join(f"- {offender}" for offender in offenders)
    )
