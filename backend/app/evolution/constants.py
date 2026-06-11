"""Application-level evolution substrate constants.

These values intentionally live in code/config rather than database enums so
new targets, signals, and engines do not require schema migrations.
"""

DEFAULT_CAPTURE_CAPABILITY_KEY = "capture-memory-extraction"
DEFAULT_CAPTURE_TARGET_TYPE = "prompt"

EVOLUTION_TARGET_TYPES: frozenset[str] = frozenset({
    "prompt",
    "capability",
    "agent_profile",
    "workflow",
    "policy",
})

EVOLUTION_SIGNAL_TYPES: frozenset[str] = frozenset({
    "memory_candidate_proposed",
    "memory_candidate_rejected",
    "memory_candidate_edited",
    "stable_preference_missed",
    "exploration_misclassified_as_decision",
    "temporary_note_saved_as_memory",
    "proposal_rejected",
    "user_repeated_same_correction",
    "run_validation_failed",
})

EVOLUTION_SIGNAL_SEVERITIES: frozenset[str] = frozenset({
    "low",
    "medium",
    "high",
    "critical",
})

EVOLUTION_ENGINE_NAMES: frozenset[str] = frozenset({
    "llm_prompt_review",
})

CAPABILITY_SCOPE_ORDER: tuple[str, ...] = (
    "agent",
    "user",
    "space",
    "instance",
    "core",
)
