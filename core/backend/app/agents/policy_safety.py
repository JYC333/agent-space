"""Shared safety-bounded policy merges for agent config edits.

Both the owner config edit (`AgentService.update_config`) and create-from-template
overrides apply user-supplied policy on top of a source snapshot. These helpers
re-stamp the hard-safety guarantees from the source so a frontend override can
never grant direct memory write, disable the proposal requirement, or turn off
proposal-only outputs. Tool/runtime policy is never merged here — it is copied
verbatim by the callers.
"""

from __future__ import annotations


def merge_memory_policy_safe(base: dict | None, override: dict) -> dict:
    """Merge a memory_policy override, re-stamping write/proposal guarantees from base."""
    base = base or {}
    merged = {**base, **(override or {})}
    # HARD SAFETY: write access cannot be expanded; proposal requirement cannot be dropped.
    merged["writable_scopes"] = list(base.get("writable_scopes", []))
    if base.get("requires_proposal"):
        merged["requires_proposal"] = True
    return merged


def merge_output_policy_safe(base: dict | None, override: dict) -> dict:
    """Merge an output_policy override, keeping the agent's hard output guarantees.

    A frontend override may narrow the enabled outputs but can never expand the
    ``allowed_output_types`` ceiling beyond the template's set, drop the
    proposal-only flag, or drop a required run output.
    """
    base = base or {}
    merged = {**base, **(override or {})}
    if base.get("proposal_only"):
        merged["proposal_only"] = True
    # HARD SAFETY: allowed_output_types is a ceiling. An override may only narrow it
    # (intersection with the base set); it can never add a new output type.
    ceiling = list(base.get("allowed_output_types", []))
    requested = merged.get("allowed_output_types", ceiling)
    merged["allowed_output_types"] = [t for t in requested if t in ceiling]
    # Required run outputs cannot be dropped by an override.
    if base.get("required_run_outputs"):
        merged["required_run_outputs"] = list(base["required_run_outputs"])
    return merged


def merge_context_policy_safe(base: dict | None, override: dict) -> dict:
    """Merge a context_policy override, keeping the input-context ceiling locked.

    ``allowed_input_contexts`` is copied verbatim from the source and can never be
    expanded by an override; ``default_input_contexts`` is clamped to that ceiling.
    """
    base = base or {}
    merged = {**base, **(override or {})}
    ceiling = list(base.get("allowed_input_contexts", []))
    merged["allowed_input_contexts"] = ceiling
    if ceiling:
        merged["default_input_contexts"] = [
            c for c in merged.get("default_input_contexts", []) if c in ceiling
        ]
    return merged
