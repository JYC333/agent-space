"""Canonical intake and evidence domain."""

from .ports import (
    ContextEvidencePort,
    ContextEvidenceSelection,
    get_context_evidence_port,
)

__all__ = [
    "ContextEvidencePort",
    "ContextEvidenceSelection",
    "get_context_evidence_port",
]
