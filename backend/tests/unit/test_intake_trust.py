from __future__ import annotations

import pytest

from app.intake.trust import (
    activity_source_trust_to_evidence_trust,
    evidence_trust_to_context_metadata,
    source_connection_trust_to_evidence_trust,
)


def test_source_connection_trust_maps_only_evidence_vocabulary():
    assert source_connection_trust_to_evidence_trust("trusted") == "trusted"
    assert source_connection_trust_to_evidence_trust("normal") == "normal"
    assert source_connection_trust_to_evidence_trust("untrusted") == "untrusted"

    with pytest.raises(ValueError):
        source_connection_trust_to_evidence_trust("high")


def test_activity_source_trust_mapping_is_explicit():
    assert activity_source_trust_to_evidence_trust("user_confirmed") == "trusted"
    assert activity_source_trust_to_evidence_trust("trusted_external") == "trusted"
    assert activity_source_trust_to_evidence_trust("internal_system") == "normal"
    assert activity_source_trust_to_evidence_trust("untrusted_external") == "untrusted"
    assert activity_source_trust_to_evidence_trust("agent_inferred") == "untrusted"

    with pytest.raises(ValueError):
        activity_source_trust_to_evidence_trust("medium")


def test_evidence_trust_context_metadata_rejects_runtime_vocabulary():
    assert evidence_trust_to_context_metadata("trusted") == {"provenance_trust": "trusted"}

    with pytest.raises(ValueError):
        evidence_trust_to_context_metadata("low")
