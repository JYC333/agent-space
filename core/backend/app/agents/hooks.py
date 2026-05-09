from __future__ import annotations
"""
Built-in post-run hooks for agent-space.

Imported once at startup (from main.py) so hooks are registered before any run fires.
Add new hooks here or register them externally via register_post_run_hook().
"""

import logging
from .runner import register_post_run_hook

log = logging.getLogger(__name__)

# Structural files → the .agent/ docs that cover them.
_STRUCTURAL_DOC_MAP: dict[str, list[str]] = {
    "models.py":           ["modules/space.md", "modules/agents.md", "modules/memory.md", "modules/proposals.md", "GLOSSARY.md"],
    "schemas.py":          ["modules/space.md", "modules/agents.md", "modules/memory.md"],
    "runner.py":           ["modules/agents.md", "modules/sandbox.md"],
    "sandbox_manager.py":  ["modules/sandbox.md"],
    "context_builder.py":  ["modules/memory.md", "modules/context-compiler.md"],
    "context_compiler.py": ["modules/context-compiler.md"],
    "agent_service.py":    ["modules/agents.md"],
    "seeder.py":           ["modules/agents.md"],
    "engine.py":           ["modules/policy.md"],
    "rules.py":            ["modules/policy.md", "BOUNDARIES.md"],
    "path_policy.py":      ["modules/sandbox.md", "modules/workspace-console.md"],
    "reflector.py":        ["modules/memory.md", "modules/proposals.md"],
    "evolver.py":          ["modules/memory.md"],
    "proposals.py":        ["modules/proposals.md", "modules/memory.md"],
}


@register_post_run_hook
def docs_sync_reminder(run, result) -> None:
    """
    Scan the run output for mentions of structural filenames.
    If any are found, log which .agent/ docs should be reviewed.

    This is a best-effort signal — it can't parse diffs, only scan text.
    For precise tracking, use the in-sandbox PostToolUse hook written by ContextCompiler.
    """
    if not result or not result.output:
        return

    output_lower = result.output.lower()
    flagged: dict[str, list[str]] = {}
    for filename, docs in _STRUCTURAL_DOC_MAP.items():
        if filename.lower() in output_lower:
            flagged[filename] = docs

    if not flagged:
        return

    log.info(
        "run=%s adapter=%s — output mentions structural files; review .agent/ docs: %s",
        run.id,
        run.adapter_type,
        {f: d for f, d in flagged.items()},
    )
