"""Workflow tests for follow_up_task proposal apply path.

Verifies:
- Valid accepted proposals create exactly one Task row with correct field mapping.
- Default values are set when optional fields are omitted.
- Malformed payloads raise ProposalApplyError without partial writes.
- Cross-space workspace references are rejected before any write.
- follow_up_task never writes MemoryEntry or Policy rows.
- Other unsupported learning proposal types remain unsupported.
- supported_types() includes follow_up_task only (not other learning types).
- ReflectionProposalBuilder normalizes missing and explicit task titles correctly.
- ProposalService.accept() path creates Task (not just direct apply).
- API accept endpoint returns result_type="follow_up_task" with task_id and title.
"""
from __future__ import annotations
import uuid

import pytest

from app.proposals import ProposalApplyService, ProposalApplyError
from app.proposals import ProposalService
from app.models import ContextSnapshot, MemoryEntry, Policy, Proposal, Run, Task
from tests.support import factories

SPACE = "space-fup-01"
USER = "user-fup-01"


def _setup(db):
    factories.create_test_space(db, space_id=SPACE)
    factories.create_test_user(db, space_id=SPACE, user_id=USER)


def _make_proposal(db, *, payload, run_id=None, workspace_id=None):
    """Create a pending follow_up_task proposal with the given payload (flush only, no commit)."""
    return factories.create_test_proposal(
        db,
        space_id=SPACE,
        created_by_user_id=USER,
        proposal_type="follow_up_task",
        run_id=run_id,
        workspace_id=workspace_id,
        payload_json=payload,
        commit=False,
    )


# ---------------------------------------------------------------------------
# A. Full field mapping
# ---------------------------------------------------------------------------


class TestApplyFollowUpTaskCreatesTask:
    def test_creates_exactly_one_task(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={
            "task": {
                "title": "Improve test coverage",
                "description": "Add missing unit tests for the parser module.",
                "task_type": "improvement",
                "priority": "high",
                "risk_level": "medium",
                "acceptance_criteria_json": {"min_coverage": 80},
                "required_outputs_json": ["coverage_report.xml"],
                "tags": ["testing", "parser"],
                "metadata_json": {"ticket": "PROJ-42"},
            }
        })

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        tasks = db.query(Task).filter(Task.space_id == SPACE).all()
        assert len(tasks) == 1

        task = tasks[0]
        assert task.title == "Improve test coverage"
        assert task.description == "Add missing unit tests for the parser module."
        assert task.task_type == "improvement"
        assert task.priority == "high"
        assert task.risk_level == "medium"
        assert task.acceptance_criteria_json == {"min_coverage": 80}
        assert task.required_outputs_json == ["coverage_report.xml"]
        assert task.tags == ["testing", "parser"]

        assert task.source_proposal_id == prop.id
        assert result.task is not None
        assert result.task.id == task.id

    def test_provenance_fields_set_from_proposal(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        prop = _make_proposal(db, payload={"task": {"title": "Fix bug"}}, run_id=run.id)

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        assert result.task.source_proposal_id == prop.id
        assert result.task.source_run_id == run.id
        assert result.task.created_by_user_id == USER

    def test_metadata_includes_provenance_keys(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={
            "task": {"title": "Write docs"},
            "reflection_id": "refl-abc123",
        })

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        meta = result.task.metadata_json
        assert meta["source"] == "follow_up_task_proposal"
        assert meta["proposal_id"] == prop.id
        assert meta["created_from_proposal_type"] == "follow_up_task"
        assert meta["reflection_id"] == "refl-abc123"


# ---------------------------------------------------------------------------
# B. Default values
# ---------------------------------------------------------------------------


class TestApplyFollowUpTaskSetsCleanDefaults:
    def test_minimal_payload_defaults(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={"task": {"title": "  Minimal task  "}})

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        task = result.task
        assert task.title == "Minimal task"  # stripped
        assert task.task_type == "general"
        assert task.priority == "normal"
        assert task.risk_level == "low"
        assert task.status == "inbox"
        assert task.visibility == "space_shared"

    def test_description_defaults_to_none(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={"task": {"title": "No description"}})

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        assert result.task.description is None

    def test_optional_fields_absent_are_none(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={"task": {"title": "Sparse"}})

        svc = ProposalApplyService(db)
        result = svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        task = result.task
        assert task.acceptance_criteria_json is None
        assert task.required_outputs_json is None
        assert task.tags is None


# ---------------------------------------------------------------------------
# C. Malformed payload rejection without partial write
# ---------------------------------------------------------------------------

INVALID_PAYLOADS = [
    pytest.param(
        {},
        id="missing_task",
    ),
    pytest.param(
        {"task": "not-a-dict"},
        id="task_not_dict",
    ),
    pytest.param(
        {"task": {"description": "No title here"}},
        id="missing_title",
    ),
    pytest.param(
        {"task": {"title": "   "}},
        id="blank_title",
    ),
    pytest.param(
        {"task": {"title": "T", "unknown_field": "x"}},
        id="unknown_task_field",
    ),
    pytest.param(
        {"task": {"title": "T", "priority": "invalid_priority"}},
        id="invalid_priority",
    ),
    pytest.param(
        {"task": {"title": "T", "risk_level": "extreme"}},
        id="invalid_risk_level",
    ),
    pytest.param(
        {"task": {"title": "T", "acceptance_criteria_json": ["not", "a", "dict"]}},
        id="acceptance_criteria_not_dict",
    ),
    pytest.param(
        {"task": {"title": "T", "required_outputs_json": {"not": "a-list"}}},
        id="required_outputs_not_list",
    ),
]


class TestMalformedPayloadRejection:
    @pytest.mark.parametrize("payload", INVALID_PAYLOADS)
    def test_raises_without_partial_write(self, db, payload):
        _setup(db)
        prop = _make_proposal(db, payload=payload)
        before = db.query(Task).filter(Task.space_id == SPACE).count()

        svc = ProposalApplyService(db)
        with pytest.raises(ProposalApplyError):
            svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        db.expire_all()
        after = db.query(Task).filter(Task.space_id == SPACE).count()
        assert after == before

    def test_unknown_toplevel_field_rejected(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={"task": {"title": "T"}, "rogue_key": True})
        before = db.query(Task).filter(Task.space_id == SPACE).count()

        svc = ProposalApplyService(db)
        with pytest.raises(ProposalApplyError):
            svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        db.expire_all()
        assert db.query(Task).filter(Task.space_id == SPACE).count() == before


# ---------------------------------------------------------------------------
# D. Cross-space workspace rejection
# ---------------------------------------------------------------------------


class TestCrossSpaceWorkspaceRejection:
    def test_workspace_from_other_space_rejected(self, db):
        _setup(db)
        other_space = str(uuid.uuid4())
        factories.create_test_space(db, space_id=other_space)
        ws = factories.create_test_workspace(db, space_id=other_space)
        db.flush()

        # Proposal is in SPACE but workspace belongs to other_space.
        prop = _make_proposal(db, payload={"task": {"title": "Cross-space task"}},
                              workspace_id=ws.id)

        svc = ProposalApplyService(db)
        with pytest.raises(ProposalApplyError):
            svc.apply(prop, user_id=USER, bypass_source_monitoring=True)

        db.expire_all()
        assert db.query(Task).filter(Task.space_id == SPACE).count() == 0



# ---------------------------------------------------------------------------
# E. Unsupported learning proposal types remain unsupported
# ---------------------------------------------------------------------------

UNSUPPORTED_LEARNING_TYPES = [
    "workspace_profile_update",
    "validation_recipe_update",
    "capability_update",
    "policy_update",
    "automation_update",
    "tool_binding_update",
]


class TestUnsupportedTypesRemainUnsupported:
    @pytest.mark.parametrize("proposal_type", UNSUPPORTED_LEARNING_TYPES)
    def test_raises_unsupported(self, db, proposal_type):
        _setup(db)
        prop = factories.create_test_proposal(
            db,
            space_id=SPACE,
            created_by_user_id=USER,
            proposal_type=proposal_type,
            commit=False,
        )
        with pytest.raises(ProposalApplyError, match="unsupported proposal type"):
            ProposalApplyService(db).apply(prop, user_id=USER, bypass_source_monitoring=True)


# ---------------------------------------------------------------------------
# F. follow_up_task does not write memory or policy
# ---------------------------------------------------------------------------


class TestFollowUpTaskDoesNotWriteMemoryOrPolicy:
    def test_counts_unchanged(self, db):
        _setup(db)
        prop = _make_proposal(db, payload={"task": {"title": "No side effects"}})

        mem_before = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE).count()
        pol_before = db.query(Policy).filter(Policy.space_id == SPACE).count()

        ProposalApplyService(db).apply(prop, user_id=USER, bypass_source_monitoring=True)

        db.expire_all()
        assert db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE).count() == mem_before
        assert db.query(Policy).filter(Policy.space_id == SPACE).count() == pol_before


# ---------------------------------------------------------------------------
# G. supported_types includes only expected new type
# ---------------------------------------------------------------------------


class TestSupportedTypes:
    def test_follow_up_task_is_supported(self):
        assert "follow_up_task" in ProposalApplyService.supported_types()

    def test_unsupported_learning_types_remain_absent(self):
        supported = ProposalApplyService.supported_types()
        for t in UNSUPPORTED_LEARNING_TYPES:
            assert t not in supported, f"Expected {t!r} to remain unsupported"


# ---------------------------------------------------------------------------
# H. ReflectionProposalBuilder normalizes task title into payload
# ---------------------------------------------------------------------------


def _make_reflection(db, space_id, run, **kwargs):
    from app.models import RunReflection

    r = RunReflection(
        id=str(uuid.uuid4()),
        space_id=space_id,
        run_id=run.id,
        source="native",
        **kwargs,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


class TestReflectionProposalBuilderTitleNormalization:
    """ReflectionProposalBuilder normalizes payload_json["task"]["title"] to match proposal.title."""

    def test_missing_title_uses_generated_default(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id,
                                        commit=True)
        refl = _make_reflection(
            db, test_space.id, run,
            follow_up_tasks_json=[{"description": "Cover edge cases in parser"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.proposal_type == "follow_up_task"

        # Generated title must be consistent between proposal.title and payload.
        assert prop.title.startswith("Follow-up task")
        assert prop.payload_json["task"]["title"] == prop.title

        # The normalized proposal should apply cleanly.
        result = ProposalApplyService(db).apply(prop, user_id=test_user.id, bypass_source_monitoring=True)
        assert result.task is not None
        assert result.task.title == prop.title

    def test_explicit_title_preserved_consistently(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id,
                                        commit=True)
        refl = _make_reflection(
            db, test_space.id, run,
            follow_up_tasks_json=[
                {"title": "Specific follow-up", "description": "Do the thing"},
            ],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.title == "Specific follow-up"
        assert prop.payload_json["task"]["title"] == "Specific follow-up"

        result = ProposalApplyService(db).apply(prop, user_id=test_user.id, bypass_source_monitoring=True)
        assert result.task is not None
        assert result.task.title == "Specific follow-up"

    def test_whitespace_only_title_uses_generated_default(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id,
                                        commit=True)
        refl = _make_reflection(
            db, test_space.id, run,
            follow_up_tasks_json=[{"title": "   ", "description": "Some task"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 1
        prop = proposals[0]
        # Whitespace-only title must be replaced with the generated default.
        assert prop.title.startswith("Follow-up task")
        assert prop.payload_json["task"]["title"] == prop.title


# ---------------------------------------------------------------------------
# I. ProposalService.accept path creates Task (not just direct apply)
# ---------------------------------------------------------------------------


class TestProposalServiceAcceptPath:
    def test_accept_creates_task(self, db, cross_space_pair_db):
        a = cross_space_pair_db["space_a_id"]
        ua = cross_space_pair_db["user_a"]

        run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=True)
        prop = factories.create_test_proposal(
            db,
            space_id=a,
            created_by_user_id=ua.id,
            proposal_type="follow_up_task",
            run_id=run.id,
            payload_json={"task": {"title": "Service-level task", "priority": "high"}},
            commit=True,
        )

        result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

        assert result is not None
        assert result.task is not None
        assert result.proposal.status == "accepted"

        db.expire_all()
        tasks = db.query(Task).filter(Task.space_id == a).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.source_proposal_id == prop.id
        assert task.source_run_id == run.id
        assert task.title == "Service-level task"
        assert task.priority == "high"


# ---------------------------------------------------------------------------
# J. API accept endpoint returns follow_up_task result
# ---------------------------------------------------------------------------


class TestApiAcceptFollowUpTask:
    def test_accept_returns_follow_up_task_result(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        client_a = cross_space_pair["client_a"]

        run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=True)
        prop = factories.create_test_proposal(
            db,
            space_id=a,
            created_by_user_id=ua.id,
            proposal_type="follow_up_task",
            run_id=run.id,
            payload_json={"task": {"title": "API-accepted task"}},
            commit=True,
        )

        r = client_a.post(
            f"/api/v1/proposals/{prop.id}/accept",
            params={"space_id": a},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["result_type"] == "follow_up_task"
        assert body["result"]["title"] == "API-accepted task"
        assert "task_id" in body["result"]
        assert body["proposal"]["status"] == "accepted"


# ---------------------------------------------------------------------------
# K. Builder sets created_by_user_id from source Run.instructed_by_user_id
# ---------------------------------------------------------------------------


class TestBuilderProposalOwnership:
    def test_builder_created_follow_up_task_can_be_accepted_by_source_run_user(self, db):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        space_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        factories.create_test_space(db, space_id=space_id)
        factories.create_test_user(db, space_id=space_id, user_id=user_id)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, commit=True)

        refl = _make_reflection(
            db, space_id, run,
            follow_up_tasks_json=[{"title": "Implement feature X", "description": "Add feature X to module Y"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, space_id)

        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.proposal_type == "follow_up_task"
        assert prop.created_by_user_id == run.instructed_by_user_id

        result = ProposalService(db).accept(prop.id, space_id=space_id, user_id=user_id)

        assert result is not None
        assert result.task is not None
        assert result.proposal.status == "accepted"

        db.expire_all()
        tasks = db.query(Task).filter(Task.space_id == space_id).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.source_proposal_id == prop.id
        assert task.source_run_id == run.id

    def test_builder_created_follow_up_task_owner_can_accept_system_proposal(self, db):
        """An owner can accept a system-created proposal (no creator user).

        The proposal.apply gate checks space membership, not proposal creator.
        A member-role user cannot accept, but an owner can.
        """
        from app.policy.exceptions import PolicyGateBlocked
        from app.models import SpaceMembership, User
        from app.runs.proposal_builder import ReflectionProposalBuilder

        space_id = str(uuid.uuid4())
        factories.create_test_space(db, space_id=space_id)
        owner_user = factories.create_test_user(db, space_id=space_id)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=owner_user.id, commit=False)

        # Create a member-role user who should be denied
        member_id = str(uuid.uuid4())
        member_user = User(id=member_id, display_name="member", email=f"{member_id}@t.invalid")
        db.add(member_user)
        db.add(SpaceMembership(id=str(uuid.uuid4()), space_id=space_id, user_id=member_id, role="member", status="active"))
        db.flush()

        snapshot = ContextSnapshot(
            id=str(uuid.uuid4()),
            space_id=space_id,
            source_refs_json=[],
            compiled_summary=None,
            token_estimate=None,
        )
        db.add(snapshot)
        db.flush()

        run = Run(
            id=str(uuid.uuid4()),
            space_id=space_id,
            agent_id=agent.id,
            agent_version_id=agent.current_version_id,
            context_snapshot_id=snapshot.id,
            instructed_by_user_id=None,
            status="queued",
            mode="live",
            required_sandbox_level="none",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        refl = _make_reflection(
            db, space_id, run,
            follow_up_tasks_json=[{"title": "Agent-only task"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, space_id)

        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.created_by_user_id is None  # system-created proposal, no user creator

        # Member cannot accept — policy gate denies
        with pytest.raises(PolicyGateBlocked):
            ProposalService(db).accept(prop.id, space_id=space_id, user_id=member_id)
        db.expire_all()
        assert db.query(Task).filter(Task.space_id == space_id).count() == 0

        # Owner CAN accept — policy gate allows
        result = ProposalService(db).accept(prop.id, space_id=space_id, user_id=owner_user.id)
        assert result is not None
        assert result.task is not None
        db.expire_all()
        assert db.query(Task).filter(Task.space_id == space_id).count() == 1

    def test_builder_rejects_non_dict_follow_up_task_item(self, db):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        space_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        factories.create_test_space(db, space_id=space_id)
        factories.create_test_user(db, space_id=space_id, user_id=user_id)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, commit=True)

        refl = _make_reflection(
            db, space_id, run,
            follow_up_tasks_json=["not-a-dict"],
        )

        before = db.query(Proposal).filter(Proposal.space_id == space_id).count()

        with pytest.raises(ValueError, match="must be a dict"):
            ReflectionProposalBuilder(db).create_learning_proposals_from_reflection(refl.id, space_id)

        db.expire_all()
        assert db.query(Proposal).filter(Proposal.space_id == space_id).count() == before
