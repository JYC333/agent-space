"""Invariant: canonical Intake/Evidence foundation."""
from __future__ import annotations

import pytest
from pathlib import Path
from sqlalchemy import func
from ulid import ULID

from app.config import settings
from app.intake.service import IntakeDuplicateError, IntakeNotFound, IntakeService, IntakeValidationError
from app.models import (
    ActivityRecord,
    AgentVersion,
    Artifact,
    ContextSnapshot,
    EvidenceLink,
    ExtractedEvidence,
    ExtractionJob,
    IntakeItem,
    KnowledgeItem,
    MemoryEntry,
    Policy,
    Proposal,
    RunEvent,
    SourceConnection,
    SourceConnector,
    SourceSnapshot,
    Task,
)
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from tests.support import factories


def _counts(db, space_id: str) -> dict[str, int]:
    return {
        "memory": db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == space_id).scalar(),
        "knowledge": db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space_id).scalar(),
        "proposals": db.query(func.count(Proposal.id)).filter(Proposal.space_id == space_id).scalar(),
        "policies": db.query(func.count(Policy.id)).filter(Policy.space_id == space_id).scalar(),
        "tasks": db.query(func.count(Task.id)).filter(Task.space_id == space_id).scalar(),
    }


def test_builtin_connectors_and_manual_url_create_intake_only(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    before = _counts(db, space_id)

    svc = IntakeService(db)
    connectors = svc.list_connectors()
    keys = {c.connector_key for c in connectors}
    assert {"rss", "atom", "manual_url", "activity_record", "artifact", "run_event"}.issubset(keys)

    item, job = svc.fetch_manual_url(space_id=space_id, url="https://example.com/article", title="Article")
    db.flush()

    assert item.id
    assert item.space_id == space_id
    assert item.item_type == "external_url"
    assert item.connection_id is None
    assert job.job_type == "manual_url"
    assert job.status == "succeeded"
    assert db.query(func.count(IntakeItem.id)).filter(IntakeItem.space_id == space_id).scalar() == 1
    assert db.query(func.count(ExtractionJob.id)).filter(ExtractionJob.space_id == space_id).scalar() == 1
    assert _counts(db, space_id) == before


def test_source_connection_workspace_binding_does_not_duplicate_intake_data(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)

    svc = IntakeService(db)
    conn = svc.create_connection(
        space_id=space_id,
        owner_user_id=user_id,
        connector_key="manual_url",
        name="Manual URLs",
    )
    item, _job = svc.fetch_manual_url(
        space_id=space_id,
        connection_id=conn.id,
        url="https://example.com/bound",
        title="Bound item",
    )
    profile = svc.create_workspace_profile(
        space_id=space_id,
        workspace_id=workspace.id,
        name="Workspace intake",
        created_by_user_id=user_id,
    )
    binding = svc.create_workspace_binding(
        space_id=space_id,
        workspace_id=workspace.id,
        source_connection_id=conn.id,
        created_by_user_id=user_id,
    )
    db.flush()

    assert db.query(func.count(SourceConnector.id)).scalar() >= 1
    assert db.query(func.count(SourceConnection.id)).filter(SourceConnection.space_id == space_id).scalar() == 1
    assert item.connection_id == conn.id
    assert profile.workspace_id == workspace.id
    assert binding.source_connection_id == conn.id
    assert db.query(func.count(IntakeItem.id)).filter(IntakeItem.space_id == space_id).scalar() == 1


def test_source_connection_credential_reference_stays_in_space(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space_id = cross_space_pair_db["space_b_id"]
    user_id = cross_space_pair_db["user_a"].id
    other_user_id = cross_space_pair_db["user_b"].id
    credential = factories.create_test_credential_stub(
        db,
        space_id=space_id,
        name="same-space intake credential",
    )
    other_credential = factories.create_test_credential_stub(
        db,
        space_id=other_space_id,
        name="cross-space intake credential",
    )
    replacement_credential = factories.create_test_credential_stub(
        db,
        space_id=space_id,
        name="same-space replacement intake credential",
    )

    svc = IntakeService(db)
    conn = svc.create_connection(
        space_id=space_id,
        owner_user_id=user_id,
        connector_key="manual_url",
        name="Credentialed manual URLs",
        credential_id=credential.id,
    )
    assert conn.credential_id == credential.id

    with pytest.raises(IntakeNotFound):
        svc.create_connection(
            space_id=space_id,
            owner_user_id=user_id,
            connector_key="manual_url",
            name="Cross-space credential",
            credential_id=other_credential.id,
        )

    with pytest.raises(IntakeNotFound):
        svc.create_connection(
            space_id=space_id,
            owner_user_id=user_id,
            connector_key="manual_url",
            name="Missing credential",
            credential_id=str(ULID()),
        )

    protected = svc.create_connection(
        space_id=space_id,
        owner_user_id=user_id,
        connector_key="manual_url",
        name="Protected credential",
        credential_id=credential.id,
    )
    updated = svc.update_connection(space_id, protected.id, credential_id=replacement_credential.id)
    assert updated.credential_id == replacement_credential.id
    original_name = protected.name
    original_credential_id = protected.credential_id

    with pytest.raises(IntakeNotFound):
        svc.update_connection(
            space_id,
            protected.id,
            name="Should not apply",
            credential_id=other_credential.id,
        )
    assert protected.name == original_name
    assert protected.credential_id == original_credential_id

    with pytest.raises(IntakeNotFound):
        svc.update_connection(
            space_id,
            protected.id,
            name="Still should not apply",
            credential_id=str(ULID()),
        )
    assert protected.name == original_name
    assert protected.credential_id == original_credential_id

    other_conn = svc.create_connection(
        space_id=other_space_id,
        owner_user_id=other_user_id,
        connector_key="manual_url",
        name="Other space valid credential",
        credential_id=other_credential.id,
    )
    assert other_conn.credential_id == other_credential.id


def test_one_evidence_item_can_link_to_multiple_targets(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space_id = cross_space_pair_db["space_b_id"]
    user_id = cross_space_pair_db["user_a"].id
    other_user_id = cross_space_pair_db["user_b"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    other_workspace = factories.create_test_workspace(db, space_id=other_space_id, created_by_user_id=other_user_id)
    project = factories.create_test_project(db, space_id=space_id, owner_user_id=user_id)

    svc = IntakeService(db)
    evidence = svc.create_evidence(
        space_id=space_id,
        evidence_type="claim",
        title="Reusable fact",
        content_excerpt="This fact can support several targets.",
        status="active",
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(space_id=space_id, evidence_id=evidence.id, target_type="space", created_by_user_id=user_id)
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=evidence.id,
        target_type="workspace",
        target_id=workspace.id,
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=evidence.id,
        target_type="project",
        target_id=project.id,
        created_by_user_id=user_id,
    )
    db.flush()

    links = db.query(EvidenceLink).filter(EvidenceLink.evidence_id == evidence.id).all()
    assert {link.target_type for link in links} == {"space", "workspace", "project"}
    assert db.query(func.count(ExtractedEvidence.id)).filter(ExtractedEvidence.space_id == space_id).scalar() == 1

    with pytest.raises(IntakeNotFound):
        svc.create_evidence_link(
            space_id=space_id,
            evidence_id=evidence.id,
            target_type="workspace",
            target_id=other_workspace.id,
            created_by_user_id=user_id,
        )


def test_context_snapshot_freezes_only_linked_active_evidence(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    run.workspace_id = workspace.id
    run.prompt = "Use linked evidence"
    version = db.get(AgentVersion, run.agent_version_id)

    svc = IntakeService(db)
    active = svc.create_evidence(
        space_id=space_id,
        evidence_type="excerpt",
        title="Selected evidence",
        content_excerpt="Only this linked active evidence should enter context.",
        status="active",
        created_by_user_id=user_id,
    )
    unlinked = svc.create_evidence(
        space_id=space_id,
        evidence_type="excerpt",
        title="Unlinked evidence",
        content_excerpt="This evidence is active but has no context link.",
        status="active",
        created_by_user_id=user_id,
    )
    rejected = svc.create_evidence(
        space_id=space_id,
        evidence_type="excerpt",
        title="Rejected evidence",
        content_excerpt="This evidence is linked but inactive.",
        status="rejected",
        created_by_user_id=user_id,
    )
    audit_only = svc.create_evidence(
        space_id=space_id,
        evidence_type="excerpt",
        title="Audit-only evidence",
        content_excerpt="A prior used_in_context link must not make this selectable.",
        status="active",
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=active.id,
        target_type="workspace",
        target_id=workspace.id,
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=rejected.id,
        target_type="workspace",
        target_id=workspace.id,
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=audit_only.id,
        target_type="run",
        target_id=run.id,
        link_type="used_in_context",
        status="active",
        created_by_run_id=run.id,
    )
    db.flush()

    ContextSnapshotPopulator(db).populate(run, version)
    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).one()

    refs = snap.included_evidence_refs_json or []
    ref_ids = {ref["source_id"] for ref in refs}
    assert active.id in ref_ids
    assert unlinked.id not in ref_ids
    assert rejected.id not in ref_ids
    assert audit_only.id not in ref_ids
    assert "Only this linked active evidence should enter context." in (snap.compiled_tail_text or "")
    assert "A prior used_in_context link must not make this selectable." not in (snap.compiled_tail_text or "")
    used_links = (
        db.query(EvidenceLink)
        .filter(
            EvidenceLink.evidence_id == active.id,
            EvidenceLink.target_type == "run",
            EvidenceLink.target_id == run.id,
            EvidenceLink.link_type == "used_in_context",
            EvidenceLink.status == "active",
        )
        .all()
    )
    assert len(used_links) == 1
    assert used_links[0].created_by_run_id == run.id
    assert not (
        db.query(EvidenceLink)
        .filter(
            EvidenceLink.evidence_id.in_([unlinked.id, rejected.id]),
            EvidenceLink.link_type == "used_in_context",
        )
        .first()
    )
    assert (
        db.query(func.count(EvidenceLink.id))
        .filter(
            EvidenceLink.evidence_id == audit_only.id,
            EvidenceLink.target_type == "run",
            EvidenceLink.target_id == run.id,
            EvidenceLink.link_type == "used_in_context",
            EvidenceLink.status == "active",
        )
        .scalar()
        == 1
    )

    ContextSnapshotPopulator(db).populate(run, version)
    assert (
        db.query(func.count(EvidenceLink.id))
        .filter(
            EvidenceLink.evidence_id == active.id,
            EvidenceLink.target_type == "run",
            EvidenceLink.target_id == run.id,
            EvidenceLink.link_type == "used_in_context",
            EvidenceLink.status == "active",
        )
        .scalar()
        == 1
    )


def test_context_population_fails_if_used_in_context_audit_link_fails(db, cross_space_pair_db, monkeypatch):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    run.workspace_id = workspace.id
    run.prompt = "This run must not receive unaudited evidence"
    version = db.get(AgentVersion, run.agent_version_id)

    svc = IntakeService(db)
    evidence = svc.create_evidence(
        space_id=space_id,
        evidence_type="excerpt",
        title="Unaudited failure candidate",
        content_excerpt="This evidence should not be silently injected.",
        status="active",
        created_by_user_id=user_id,
    )
    svc.create_evidence_link(
        space_id=space_id,
        evidence_id=evidence.id,
        target_type="workspace",
        target_id=workspace.id,
        created_by_user_id=user_id,
    )
    db.flush()

    original_create_evidence_link = IntakeService.create_evidence_link

    def fail_used_in_context(self, **kwargs):
        if kwargs.get("link_type") == "used_in_context":
            raise RuntimeError("used_in_context audit failed")
        return original_create_evidence_link(self, **kwargs)

    monkeypatch.setattr(IntakeService, "create_evidence_link", fail_used_in_context)

    with pytest.raises(RuntimeError, match="used_in_context audit failed"):
        ContextSnapshotPopulator(db).populate(run, version)

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).one()
    assert not (snap.included_evidence_refs_json or [])
    assert "This evidence should not be silently injected." not in (snap.compiled_tail_text or "")
    assert (
        db.query(func.count(EvidenceLink.id))
        .filter(
            EvidenceLink.evidence_id == evidence.id,
            EvidenceLink.target_type == "run",
            EvidenceLink.target_id == run.id,
            EvidenceLink.link_type == "used_in_context",
        )
        .scalar()
        == 0
    )


def test_evidence_link_target_validation_and_idempotence(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent)
    proposal = factories.create_test_proposal(db, space_id=space_id, run_id=run.id, created_by_user_id=user_id)
    task = Task(
        id=str(ULID()),
        space_id=space_id,
        title="Evidence target task",
        created_by_user_id=user_id,
    )
    db.add(task)
    db.flush()

    svc = IntakeService(db)
    evidence = svc.create_evidence(
        space_id=space_id,
        evidence_type="claim",
        title="Validated fact",
        content_excerpt="Target validation covers supported target types.",
        status="active",
        created_by_user_id=user_id,
    )

    space_link = svc.create_evidence_link(space_id=space_id, evidence_id=evidence.id, target_type="space")
    assert space_link.target_id == space_id

    with pytest.raises(IntakeValidationError):
        svc.create_evidence_link(space_id=space_id, evidence_id=evidence.id, target_type="workspace")
    with pytest.raises(IntakeValidationError):
        svc.create_evidence_link(space_id=space_id, evidence_id=evidence.id, target_type="unsupported")

    first = svc.create_evidence_link(
        space_id=space_id,
        evidence_id=evidence.id,
        target_type="workspace",
        target_id=workspace.id,
        link_type="supports",
        status="active",
    )
    duplicate = svc.create_evidence_link(
        space_id=space_id,
        evidence_id=evidence.id,
        target_type="workspace",
        target_id=workspace.id,
        link_type="supports",
        status="active",
    )
    assert duplicate.id == first.id

    for target_type, target_id in [
        ("user", user_id),
        ("agent", agent.id),
        ("run", run.id),
        ("proposal", proposal.id),
        ("task", task.id),
    ]:
        link = svc.create_evidence_link(
            space_id=space_id,
            evidence_id=evidence.id,
            target_type=target_type,
            target_id=target_id,
        )
        assert link.target_id == target_id


def test_evidence_link_rejects_cross_space_targets(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space_id = cross_space_pair_db["space_b_id"]
    user_id = cross_space_pair_db["user_a"].id
    other_user_id = cross_space_pair_db["user_b"].id

    other_workspace = factories.create_test_workspace(db, space_id=other_space_id, created_by_user_id=other_user_id)
    other_project = factories.create_test_project(db, space_id=other_space_id, owner_user_id=other_user_id)
    other_agent = factories.create_test_agent(db, space_id=other_space_id, owner_user_id=other_user_id)
    other_run = factories.create_test_run(db, space_id=other_space_id, user_id=other_user_id, agent=other_agent)
    other_proposal = factories.create_test_proposal(
        db,
        space_id=other_space_id,
        run_id=other_run.id,
        created_by_user_id=other_user_id,
    )
    other_artifact = factories.create_test_artifact(db, space_id=other_space_id, run_id=other_run.id)
    other_memory = factories.create_test_memory_entry(db, space_id=other_space_id)
    other_knowledge = factories.create_test_knowledge_item(db, space_id=other_space_id)
    other_task = Task(
        id=str(ULID()),
        space_id=other_space_id,
        title="Other evidence target task",
        created_by_user_id=other_user_id,
    )
    db.add(other_task)
    db.flush()

    svc = IntakeService(db)
    evidence = svc.create_evidence(
        space_id=space_id,
        evidence_type="claim",
        title="Cross-space target rejection",
        content_excerpt="Targets from another space must not link.",
        status="active",
        created_by_user_id=user_id,
    )

    for target_type, target_id in [
        ("user", other_user_id),
        ("agent", other_agent.id),
        ("workspace", other_workspace.id),
        ("project", other_project.id),
        ("run", other_run.id),
        ("proposal", other_proposal.id),
        ("artifact", other_artifact.id),
        ("memory", other_memory.id),
        ("knowledge", other_knowledge.id),
        ("task", other_task.id),
    ]:
        with pytest.raises(IntakeNotFound):
            svc.create_evidence_link(
                space_id=space_id,
                evidence_id=evidence.id,
                target_type=target_type,
                target_id=target_id,
            )


def test_workspace_source_binding_project_boundary_and_binding_key(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space_id = cross_space_pair_db["space_b_id"]
    user_id = cross_space_pair_db["user_a"].id
    other_user_id = cross_space_pair_db["user_b"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    other_workspace = factories.create_test_workspace(db, space_id=other_space_id, created_by_user_id=other_user_id)
    linked_project = factories.create_test_project(db, space_id=space_id, owner_user_id=user_id)
    unlinked_project = factories.create_test_project(db, space_id=space_id, owner_user_id=user_id)
    other_project = factories.create_test_project(db, space_id=other_space_id, owner_user_id=other_user_id)
    factories.create_test_project_workspace_link(db, project=linked_project, workspace=workspace)

    svc = IntakeService(db)
    conn = svc.create_connection(
        space_id=space_id,
        owner_user_id=user_id,
        connector_key="manual_url",
        name="Workspace binding source",
    )
    other_conn = svc.create_connection(
        space_id=other_space_id,
        owner_user_id=other_user_id,
        connector_key="manual_url",
        name="Other workspace binding source",
    )

    default_binding = svc.create_workspace_binding(
        space_id=space_id,
        workspace_id=workspace.id,
        source_connection_id=conn.id,
        created_by_user_id=user_id,
    )
    assert default_binding.binding_key == "default"

    with pytest.raises(IntakeDuplicateError):
        svc.create_workspace_binding(
            space_id=space_id,
            workspace_id=workspace.id,
            source_connection_id=conn.id,
            binding_key="default",
            created_by_user_id=user_id,
        )

    filtered_binding = svc.create_workspace_binding(
        space_id=space_id,
        workspace_id=workspace.id,
        source_connection_id=conn.id,
        binding_key="filtered",
        created_by_user_id=user_id,
    )
    assert filtered_binding.binding_key == "filtered"

    linked_binding = svc.create_workspace_binding(
        space_id=space_id,
        workspace_id=workspace.id,
        source_connection_id=conn.id,
        project_id=linked_project.id,
        binding_key="linked-project",
        created_by_user_id=user_id,
    )
    assert linked_binding.project_id == linked_project.id

    with pytest.raises(IntakeValidationError):
        svc.create_workspace_binding(
            space_id=space_id,
            workspace_id=workspace.id,
            source_connection_id=conn.id,
            project_id=unlinked_project.id,
            binding_key="unlinked-project",
            created_by_user_id=user_id,
        )
    with pytest.raises(IntakeNotFound):
        svc.create_workspace_binding(
            space_id=space_id,
            workspace_id=workspace.id,
            source_connection_id=conn.id,
            project_id=other_project.id,
            binding_key="cross-space-project",
            created_by_user_id=user_id,
        )
    with pytest.raises(IntakeNotFound):
        svc.create_workspace_binding(
            space_id=space_id,
            workspace_id=other_workspace.id,
            source_connection_id=conn.id,
            binding_key="cross-space-workspace",
            created_by_user_id=user_id,
        )
    with pytest.raises(IntakeNotFound):
        svc.create_workspace_binding(
            space_id=space_id,
            workspace_id=workspace.id,
            source_connection_id=other_conn.id,
            binding_key="cross-space-connection",
            created_by_user_id=user_id,
        )


def test_intake_service_validation_errors_are_explicit(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)

    svc = IntakeService(db)
    with pytest.raises(IntakeValidationError):
        svc.create_evidence(
            space_id=space_id,
            evidence_type="unsupported",
            title="Bad evidence type",
        )

    evidence = svc.create_evidence(
        space_id=space_id,
        evidence_type="claim",
        title="Valid evidence",
        status="active",
        created_by_user_id=user_id,
    )
    with pytest.raises(IntakeValidationError):
        svc.create_evidence_link(space_id=space_id, evidence_id=evidence.id, target_type="workspace")
    with pytest.raises(IntakeValidationError):
        svc.update_evidence(space_id, evidence.id, confidence=1.5)
    with pytest.raises(IntakeValidationError):
        svc.create_workspace_profile(
            space_id=space_id,
            workspace_id=workspace.id,
            name="Invalid profile",
            observation_policy="unsupported",
            created_by_user_id=user_id,
        )


def test_activity_normalization_creates_intake_and_evidence_only(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    activity = factories.create_test_activity(
        db,
        space_id=space_id,
        actor_user_id=user_id,
        title="Captured activity",
        content="<b>Internal activity evidence</b>" + (" x" * 3000),
        source_kind="system_event",
        source_trust="internal_system",
    )
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item, evidence, job = svc.normalize_activity_record(
        space_id=space_id,
        activity_record_id=activity.id,
        created_by_user_id=user_id,
    )

    assert item.item_type == "activity_record"
    assert item.source_object_type == "activity_record"
    assert item.source_object_id == activity.id
    assert item.source_uri is None
    assert evidence.evidence_type == "event"
    assert evidence.source_uri is None
    assert evidence.metadata_json["internal_ref"] == {"type": "activity_record", "id": activity.id}
    assert "<b>" not in (evidence.content_excerpt or "")
    assert len(evidence.content_excerpt or "") <= 4096
    assert job.job_type == "normalize_activity"
    assert db.query(func.count(SourceSnapshot.id)).filter(SourceSnapshot.intake_item_id == item.id).scalar() == 1
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_activity_normalization_is_idempotent(db, cross_space_pair_db, tmp_path):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    workspace_file = workspace_root / "tracked.txt"
    workspace_file.write_text("unchanged", encoding="utf-8")
    workspace = factories.create_test_workspace(
        db,
        space_id=space_id,
        created_by_user_id=user_id,
        root_path=str(workspace_root),
    )
    activity = factories.create_test_activity(
        db,
        space_id=space_id,
        actor_user_id=user_id,
        title="Idempotent activity",
        content="Internal activity evidence",
        source_kind="system_event",
        source_trust="internal_system",
        workspace_id=workspace.id,
    )
    capability_settings = Path(settings.instance_root) / "config" / "settings.yaml"
    capability_state_before = capability_settings.read_text(encoding="utf-8") if capability_settings.exists() else None
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item1, evidence1, job1 = svc.normalize_activity_record(
        space_id=space_id,
        activity_record_id=activity.id,
        created_by_user_id=user_id,
    )
    item2, evidence2, job2 = svc.normalize_activity_record(
        space_id=space_id,
        activity_record_id=activity.id,
        created_by_user_id=user_id,
    )

    assert item2.id == item1.id
    assert evidence2.id == evidence1.id
    assert job1.status == "succeeded"
    assert job2.status == "skipped"
    assert job2.metadata_json["reason"] == "already_normalized"
    assert db.query(func.count(IntakeItem.id)).filter(
        IntakeItem.space_id == space_id,
        IntakeItem.source_object_type == "activity_record",
        IntakeItem.source_object_id == activity.id,
        IntakeItem.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(ExtractedEvidence.id)).filter(
        ExtractedEvidence.space_id == space_id,
        ExtractedEvidence.source_object_type == "activity_record",
        ExtractedEvidence.source_object_id == activity.id,
        ExtractedEvidence.evidence_type == "event",
        ExtractedEvidence.status.in_(["candidate", "active"]),
        ExtractedEvidence.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(SourceSnapshot.id)).filter(SourceSnapshot.intake_item_id == item1.id).scalar() == 1
    assert workspace_file.read_text(encoding="utf-8") == "unchanged"
    capability_state_after = capability_settings.read_text(encoding="utf-8") if capability_settings.exists() else None
    assert capability_state_after == capability_state_before
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_artifact_normalization_creates_intake_and_evidence_only(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    artifact = factories.create_test_artifact(
        db,
        space_id=space_id,
        run_id=run.id,
        title="Runtime artifact",
        content="Artifact content for citation.",
    )
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item, evidence, job = svc.normalize_artifact(
        space_id=space_id,
        artifact_id=artifact.id,
        created_by_user_id=user_id,
    )

    assert item.item_type == "artifact"
    assert item.source_object_type == "artifact"
    assert item.source_object_id == artifact.id
    assert item.source_uri is None
    assert evidence.evidence_type == "artifact"
    assert evidence.artifact_id == artifact.id
    assert evidence.source_uri is None
    assert evidence.metadata_json["internal_ref"] == {"type": "artifact", "id": artifact.id}
    assert job.job_type == "normalize_artifact"
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_artifact_normalization_is_idempotent(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    artifact = factories.create_test_artifact(
        db,
        space_id=space_id,
        run_id=run.id,
        title="Idempotent artifact",
        content="Artifact content for citation.",
    )
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item1, evidence1, job1 = svc.normalize_artifact(
        space_id=space_id,
        artifact_id=artifact.id,
        created_by_user_id=user_id,
    )
    item2, evidence2, job2 = svc.normalize_artifact(
        space_id=space_id,
        artifact_id=artifact.id,
        created_by_user_id=user_id,
    )

    assert item2.id == item1.id
    assert evidence2.id == evidence1.id
    assert job1.status == "succeeded"
    assert job2.status == "skipped"
    assert db.query(func.count(IntakeItem.id)).filter(
        IntakeItem.space_id == space_id,
        IntakeItem.source_object_type == "artifact",
        IntakeItem.source_object_id == artifact.id,
        IntakeItem.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(ExtractedEvidence.id)).filter(
        ExtractedEvidence.space_id == space_id,
        ExtractedEvidence.source_object_type == "artifact",
        ExtractedEvidence.source_object_id == artifact.id,
        ExtractedEvidence.evidence_type == "artifact",
        ExtractedEvidence.status.in_(["candidate", "active"]),
        ExtractedEvidence.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(SourceSnapshot.id)).filter(SourceSnapshot.intake_item_id == item1.id).scalar() == 1
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_run_event_normalization_creates_intake_and_evidence_only(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    event = RunEvent(
        id=str(ULID()),
        space_id=space_id,
        run_id=run.id,
        event_index=0,
        event_type="adapter_completed",
        status="succeeded",
        summary="Adapter completed with structured output.",
        trust_level="high",
        metadata_json={"tokens": 12},
    )
    db.add(event)
    db.flush()
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item, evidence, job = svc.normalize_run_event(
        space_id=space_id,
        run_event_id=event.id,
        created_by_user_id=user_id,
    )

    assert item.item_type == "run_event"
    assert item.source_object_type == "run_event"
    assert item.source_object_id == event.id
    assert item.source_uri is None
    assert evidence.evidence_type == "event"
    assert evidence.source_uri is None
    assert evidence.created_by_run_id == run.id
    assert evidence.metadata_json["runtime_trust_level"] == "high"
    assert evidence.metadata_json["internal_ref"] == {"type": "run_event", "id": event.id}
    assert job.job_type == "normalize_run_event"
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_run_event_normalization_is_idempotent(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    event = RunEvent(
        id=str(ULID()),
        space_id=space_id,
        run_id=run.id,
        event_index=0,
        event_type="adapter_completed",
        status="succeeded",
        summary="Adapter completed with structured output.",
        trust_level="high",
        metadata_json={"tokens": 12},
    )
    db.add(event)
    db.flush()
    before = _counts(db, space_id)

    svc = IntakeService(db)
    item1, evidence1, job1 = svc.normalize_run_event(
        space_id=space_id,
        run_event_id=event.id,
        created_by_user_id=user_id,
    )
    item2, evidence2, job2 = svc.normalize_run_event(
        space_id=space_id,
        run_event_id=event.id,
        created_by_user_id=user_id,
    )

    assert item2.id == item1.id
    assert evidence2.id == evidence1.id
    assert job1.status == "succeeded"
    assert job2.status == "skipped"
    assert db.query(func.count(IntakeItem.id)).filter(
        IntakeItem.space_id == space_id,
        IntakeItem.source_object_type == "run_event",
        IntakeItem.source_object_id == event.id,
        IntakeItem.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(ExtractedEvidence.id)).filter(
        ExtractedEvidence.space_id == space_id,
        ExtractedEvidence.source_object_type == "run_event",
        ExtractedEvidence.source_object_id == event.id,
        ExtractedEvidence.evidence_type == "event",
        ExtractedEvidence.status.in_(["candidate", "active"]),
        ExtractedEvidence.deleted_at.is_(None),
    ).scalar() == 1
    assert db.query(func.count(SourceSnapshot.id)).filter(SourceSnapshot.intake_item_id == item1.id).scalar() == 1
    svc.assert_no_durable_mutation_side_effects(space_id, before)


def test_internal_normalization_rejects_cross_space_objects(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space_id = cross_space_pair_db["space_b_id"]
    other_user_id = cross_space_pair_db["user_b"].id
    other_activity = factories.create_test_activity(db, space_id=other_space_id, actor_user_id=other_user_id)
    other_run = factories.create_test_run(db, space_id=other_space_id, user_id=other_user_id)
    other_artifact = factories.create_test_artifact(db, space_id=other_space_id, run_id=other_run.id)
    other_event = RunEvent(
        id=str(ULID()),
        space_id=other_space_id,
        run_id=other_run.id,
        event_index=0,
        event_type="adapter_completed",
        status="succeeded",
        summary="Other-space event",
    )
    db.add(other_event)
    db.flush()

    svc = IntakeService(db)
    with pytest.raises(IntakeNotFound):
        svc.normalize_activity_record(space_id=space_id, activity_record_id=other_activity.id)
    with pytest.raises(IntakeNotFound):
        svc.normalize_artifact(space_id=space_id, artifact_id=other_artifact.id)
    with pytest.raises(IntakeNotFound):
        svc.normalize_run_event(space_id=space_id, run_event_id=other_event.id)
