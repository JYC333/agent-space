from __future__ import annotations

from .candidate import MemoryCandidate, ValidationResult

_ALLOWED_SCOPES = frozenset({"user", "workspace", "agent", "space", "system", "capability"})


class MemoryCandidateValidator:
    """Deterministic gate — candidates never become proposals without passing here."""

    def __init__(self, *, space_id: str, acting_user_id: str) -> None:
        self._space_id = space_id
        self._acting_user_id = acting_user_id

    def validate(self, candidate: MemoryCandidate) -> ValidationResult:
        if candidate.space_id != self._space_id:
            return ValidationResult("reject", "cross_space_candidate")

        if candidate.scope_type not in _ALLOWED_SCOPES:
            return ValidationResult("reject", "invalid_scope_type")

        if not candidate.provenance_entries:
            return ValidationResult("reject", "missing_provenance")

        if candidate.operation == "update" and not candidate.target_memory_id:
            return ValidationResult("reject", "semantic_update_missing_target")

        if candidate.candidate_type == "ignore":
            return ValidationResult("preview_only", "ignore_candidate")

        if candidate.candidate_type in ("archive_activity", "discard_activity"):
            return ValidationResult("preview_only", "non_memory_candidate")

        if candidate.candidate_type == "semantic_memory" and candidate.source_trust == "agent_inferred":
            return ValidationResult("reject", "agent_inferred_semantic")

        if candidate.candidate_type == "semantic_memory" and candidate.source_trust == "untrusted_external":
            return ValidationResult("create_review_proposal", "untrusted_semantic_review")

        if candidate.visibility == "private":
            subj = candidate.subject_user_id
            if subj is not None and subj != self._acting_user_id:
                return ValidationResult("reject", "private_memory_other_user")

        if candidate.candidate_type == "policy_candidate":
            return ValidationResult("create_review_proposal", "policy_requires_review")

        if candidate.candidate_type == "semantic_memory":
            return ValidationResult("create_review_proposal", "semantic_versioned_review")

        if candidate.candidate_type in ("episodic_memory", "case_memory"):
            if candidate.source_trust == "untrusted_external":
                return ValidationResult("create_review_proposal", "untrusted_episodic_review")
            if candidate.source_trust == "agent_inferred":
                return ValidationResult("create_review_proposal", "agent_inferred_episodic_review")
            if candidate.source_trust in ("user_confirmed", "internal_system", "trusted_external"):
                return ValidationResult("create_review_proposal", "episodic_reviewable")

        return ValidationResult("reject", "unsupported_candidate")
