"""
Run sub-resources, proposal resilience read paths, and artifact export.

Read/review/export only — no execution, no synthetic in-process runtime, no adapter calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

pytestmark = pytest.mark.canonical

from app.models import ActivityRecord, Agent, AgentVersion, Artifact, Proposal, Run
from app.memory.proposals import MemoryProposalService
from app.runs.run_service import RunService
from app.schemas import AgentCreate, RunCreate
from tests.conftest import SPACE, USER, ensure_space


def _seed_agent_and_run(db):
    from app.agents.agent_service import AgentService

    agent = AgentService(db).create(
        AgentCreate(name="Task bundle agent"),
        requesting_user_id=USER,
    )
    run = RunService(db).create_run(
        agent_id=agent.id,
        data=RunCreate(),
        space_id=SPACE,
        user_id=USER,
    )
    return agent, run


def _auth_q():
    return f"space_id={SPACE}&user_id={USER}"


class TestRunSubresources:
    def test_activities_filtered_by_source_run_id_and_space(self, client, db):
        _, run = _seed_agent_and_run(db)
        other_run = RunService(db).create_run(
            agent_id=db.query(Agent).filter(Agent.space_id == SPACE).first().id,
            data=RunCreate(),
            space_id=SPACE,
            user_id=USER,
        )
        db.add(
            ActivityRecord(
                id="act-on-run",
                space_id=SPACE,
                source_run_id=run.id,
                activity_type="log",
                title="A1",
            )
        )
        db.add(
            ActivityRecord(
                id="act-other-run",
                space_id=SPACE,
                source_run_id=other_run.id,
                activity_type="log",
                title="A2",
            )
        )
        db.commit()

        r = client.get(f"/api/v1/runs/{run.id}/activities?{_auth_q()}")
        assert r.status_code == 200
        data = r.json()
        ids = {x["id"] for x in data["items"]}
        assert "act-on-run" in ids
        assert "act-other-run" not in ids

    def test_activities_cross_space_404(self, client, db):
        ensure_space(db, "other-sp-5", "O")
        agent = Agent(
            id=str(ULID()),
            space_id="other-sp-5",
            owner_user_id=USER,
            name="A",
            status="active",
            visibility="private",
        )
        db.add(agent)
        db.flush()
        v = AgentVersion(
            id=str(ULID()),
            agent_id=agent.id,
            space_id="other-sp-5",
            version_label="v1",
            model_config_json={},
            runtime_config_json={},
            context_policy_json={},
            memory_policy_json={},
            capabilities_json=[],
            tool_permissions_json={},
            runtime_policy_json={},
        )
        db.add(v)
        agent.current_version_id = v.id
        db.flush()
        run = Run(
            id=str(ULID()),
            space_id="other-sp-5",
            agent_id=agent.id,
            agent_version_id=v.id,
            status="queued",
        )
        db.add(run)
        db.commit()

        r = client.get(f"/api/v1/runs/{run.id}/activities?{_auth_q()}")
        assert r.status_code == 404

    def test_activities_limit_offset(self, client, db):
        _, run = _seed_agent_and_run(db)
        for i in range(3):
            db.add(
                ActivityRecord(
                    id=f"act-{i}",
                    space_id=SPACE,
                    source_run_id=run.id,
                    activity_type="log",
                    title=f"T{i}",
                )
            )
        db.commit()
        r = client.get(f"/api/v1/runs/{run.id}/activities?{_auth_q()}&limit=1&offset=1")
        assert r.status_code == 200
        assert r.json()["total"] == 3
        assert len(r.json()["items"]) == 1

    def test_activities_get_does_not_create_rows(self, client, db):
        _, run = _seed_agent_and_run(db)
        before = db.query(ActivityRecord).count()
        r = client.get(f"/api/v1/runs/{run.id}/activities?{_auth_q()}")
        assert r.status_code == 200
        assert db.query(ActivityRecord).count() == before

    def test_artifacts_filtered_by_run_id_and_type(self, client, db):
        _, run = _seed_agent_and_run(db)
        _, run2 = _seed_agent_and_run(db)
        db.add(
            Artifact(
                id="art1",
                space_id=SPACE,
                run_id=run.id,
                artifact_type="log",
                title="L1",
                exportable=True,
            )
        )
        db.add(
            Artifact(
                id="art2",
                space_id=SPACE,
                run_id=run.id,
                artifact_type="diff",
                title="D1",
                exportable=True,
            )
        )
        db.add(
            Artifact(
                id="art3",
                space_id=SPACE,
                run_id=run2.id,
                artifact_type="log",
                title="Other",
                exportable=True,
            )
        )
        db.commit()

        r = client.get(f"/api/v1/runs/{run.id}/artifacts?{_auth_q()}&artifact_type=log")
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["items"]}
        assert ids == {"art1"}

    def test_proposals_filtered_by_created_by_run_id(self, client, db):
        _, run = _seed_agent_and_run(db)
        _, run2 = _seed_agent_and_run(db)
        db.add(
            Proposal(
                id="pr1",
                space_id=SPACE,
                created_by_run_id=run.id,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="normal",
                title="P1",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
            )
        )
        db.add(
            Proposal(
                id="pr2",
                space_id=SPACE,
                created_by_run_id=run2.id,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="normal",
                title="P2",
                payload_json={"proposed_content": "y", "memory_type": "preference"},
                created_by_user_id=USER,
            )
        )
        db.commit()

        r = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}")
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["items"]}
        assert ids == {"pr1"}

    def test_run_proposals_status_filter(self, client, db):
        _, run = _seed_agent_and_run(db)
        db.add(
            Proposal(
                id="p-pend",
                space_id=SPACE,
                created_by_run_id=run.id,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="normal",
                title="T",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
            )
        )
        db.add(
            Proposal(
                id="p-acc",
                space_id=SPACE,
                created_by_run_id=run.id,
                proposal_type="memory_update",
                status="accepted",
                risk_level="low",
                urgency="normal",
                title="T2",
                payload_json={"proposed_content": "y", "memory_type": "preference"},
                created_by_user_id=USER,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}&status=pending")
        assert r.status_code == 200
        assert {x["id"] for x in r.json()["items"]} == {"p-pend"}


class TestProposalResilience:
    def test_top_level_proposals_includes_resilience_fields(self, client, db):
        svc = MemoryProposalService(db)
        now = datetime.now(UTC)
        p = svc.create_proposal(
            space_id=SPACE,
            user_id=USER,
            target_scope="user",
            target_namespace="n",
            memory_type="preference",
            proposed_title="T",
            proposed_content="c",
            rationale="r",
            urgency="high",
            review_deadline=now + timedelta(days=1),
            expires_at=now + timedelta(days=2),
        )
        r = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending")
        assert r.status_code == 200
        row = next(x for x in r.json()["items"] if x["id"] == p.id)
        assert row["urgency"] == "high"
        assert row["review_deadline"] is not None
        assert row["expires_at"] is not None
        assert row["expired"] is False
        assert row["proposal_type"] == "memory_update"
        assert "created_by_run_id" in row

    def test_expired_true_for_reviewable_past_expires(self, client, db):
        now = datetime.now(UTC)
        db.add(
            Proposal(
                id="exp-p",
                space_id=SPACE,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="normal",
                title="E",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                expires_at=now - timedelta(hours=1),
            )
        )
        db.commit()
        r = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending&expired=true")
        assert r.status_code == 200
        assert any(x["id"] == "exp-p" for x in r.json()["items"])

    def test_accepted_not_expired_when_expires_passed(self, client, db):
        now = datetime.now(UTC)
        db.add(
            Proposal(
                id="exp-a",
                space_id=SPACE,
                proposal_type="memory_update",
                status="accepted",
                risk_level="low",
                urgency="normal",
                title="E",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                expires_at=now - timedelta(hours=1),
            )
        )
        db.commit()
        r = client.get(f"/api/v1/proposals?{_auth_q()}&status=accepted")
        assert r.status_code == 200
        row = next(x for x in r.json()["items"] if x["id"] == "exp-a")
        assert row["expired"] is False

    def test_urgency_and_expired_filters(self, client, db):
        now = datetime.now(UTC)
        for u in ("critical", "low"):
            db.add(
                Proposal(
                    id=f"urg-{u}",
                    space_id=SPACE,
                    proposal_type="memory_update",
                    status="pending",
                    risk_level="low",
                    urgency=u,
                    title=u,
                    payload_json={"proposed_content": "x", "memory_type": "preference"},
                    created_by_user_id=USER,
                    expires_at=now - timedelta(hours=1) if u == "critical" else None,
                )
            )
        db.commit()
        r = client.get(f"/api/v1/proposals?{_auth_q()}&urgency=critical&status=pending")
        assert r.status_code == 200
        data = r.json()["items"]
        assert data
        assert all(x["urgency"] == "critical" for x in data)

        r2 = client.get(f"/api/v1/proposals?{_auth_q()}&expired=false&status=pending")
        assert r2.status_code == 200
        ids = {x["id"] for x in r2.json()["items"]}
        assert "urg-low" in ids
        assert "urg-critical" not in ids

    def test_sorting_urgency_deadline_expiry(self, client, db):
        now = datetime.now(UTC)
        db.add(
            Proposal(
                id="s-low",
                space_id=SPACE,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="low",
                title="a",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                review_deadline=now + timedelta(days=2),
                expires_at=now + timedelta(days=3),
            )
        )
        db.add(
            Proposal(
                id="s-crit",
                space_id=SPACE,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="critical",
                title="b",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                review_deadline=now + timedelta(days=3),
                expires_at=now + timedelta(days=4),
            )
        )
        db.commit()
        r = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending")
        assert r.status_code == 200
        items = r.json()["items"]
        # critical should appear before low
        crit_idx = next(i for i, x in enumerate(items) if x["id"] == "s-crit")
        low_idx = next(i for i, x in enumerate(items) if x["id"] == "s-low")
        assert crit_idx < low_idx

    def test_invalid_urgency_rejected(self, client, db):
        r = client.get(f"/api/v1/proposals?{_auth_q()}&urgency=mega&status=pending")
        assert r.status_code == 422

    def test_invalid_temporal_on_create(self, db):
        svc = MemoryProposalService(db)
        now = datetime.now(UTC)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            svc.create_proposal(
                space_id=SPACE,
                user_id=USER,
                target_scope="user",
                target_namespace="n",
                memory_type="preference",
                proposed_title="T",
                proposed_content="c",
                rationale="r",
                review_deadline=now - timedelta(hours=1),
            )
        assert exc.value.status_code == 422

        with pytest.raises(HTTPException) as exc2:
            svc.create_proposal(
                space_id=SPACE,
                user_id=USER,
                target_scope="user",
                target_namespace="n",
                memory_type="preference",
                proposed_title="T",
                proposed_content="c",
                rationale="r",
                review_deadline=now + timedelta(days=2),
                expires_at=now + timedelta(days=1),
            )
        assert exc2.value.status_code == 422

    def test_run_proposals_same_output_shape(self, client, db):
        _, run = _seed_agent_and_run(db)
        now = datetime.now(UTC)
        db.add(
            Proposal(
                id="rp1",
                space_id=SPACE,
                created_by_run_id=run.id,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="high",
                title="R",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                review_deadline=now + timedelta(days=1),
                expires_at=now + timedelta(days=2),
            )
        )
        db.commit()
        r = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}")
        assert r.status_code == 200
        rows = [x for x in r.json()["items"] if x["id"] == "rp1"]
        assert len(rows) == 1
        row = rows[0]
        for k in (
            "urgency",
            "review_deadline",
            "expires_at",
            "expired",
            "proposal_type",
            "created_by_run_id",
        ):
            assert k in row


class TestProposalOutConsistency:
    """``ProposalOut`` shape and computed ``expired`` across list routes."""

    _REVIEW_KEYS = (
        "urgency",
        "review_deadline",
        "expires_at",
        "expired",
        "proposal_type",
        "created_by_run_id",
    )

    def test_expired_is_not_a_persisted_column(self):
        from app.models import Proposal

        assert "expired" not in {c.name for c in Proposal.__table__.columns}

    def test_global_and_run_subresource_proposal_review_field_parity(self, client, db):
        _, run = _seed_agent_and_run(db)
        now = datetime.now(UTC)
        db.add(
            Proposal(
                id="parity-p",
                space_id=SPACE,
                created_by_run_id=run.id,
                proposal_type="memory_update",
                status="pending",
                risk_level="low",
                urgency="normal",
                title="Parity",
                payload_json={"proposed_content": "x", "memory_type": "preference"},
                created_by_user_id=USER,
                review_deadline=now + timedelta(days=1),
                expires_at=now + timedelta(days=2),
            )
        )
        db.commit()
        g = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending")
        r = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}&status=pending")
        assert g.status_code == 200 and r.status_code == 200
        g_row = next(x for x in g.json()["items"] if x["id"] == "parity-p")
        r_row = next(x for x in r.json()["items"] if x["id"] == "parity-p")
        for k in self._REVIEW_KEYS:
            assert g_row[k] == r_row[k], k

    def test_rejected_superseded_and_accepted_never_expired_true(self, client, db):
        now = datetime.now(UTC)
        rows = (
            ("prop-rej", "rejected"),
            ("prop-sup", "superseded"),
            ("prop-acc2", "accepted"),
        )
        for pid, st in rows:
            db.add(
                Proposal(
                    id=pid,
                    space_id=SPACE,
                    proposal_type="memory_update",
                    status=st,
                    risk_level="low",
                    urgency="normal",
                    title=pid,
                    payload_json={"proposed_content": "x", "memory_type": "preference"},
                    created_by_user_id=USER,
                    expires_at=now - timedelta(days=1),
                )
            )
        db.commit()
        for st, pid in (
            ("rejected", "prop-rej"),
            ("superseded", "prop-sup"),
            ("accepted", "prop-acc2"),
        ):
            resp = client.get(f"/api/v1/proposals?{_auth_q()}&status={st}")
            assert resp.status_code == 200
            row = next(x for x in resp.json()["items"] if x["id"] == pid)
            assert row["expired"] is False


class TestArtifactExport:
    def test_inline_export(self, client, db):
        db.add(
            Artifact(
                id="inline-1",
                space_id=SPACE,
                artifact_type="text",
                title="hello.txt",
                content="hello world",
                mime_type="text/plain",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/inline-1/export?{_auth_q()}")
        assert r.status_code == 200
        assert r.content == b"hello world"
        assert "content-disposition" in {k.lower() for k in r.headers.keys()}

    def test_stored_export_from_configured_root(self, client, db, tmp_path, monkeypatch):
        root = tmp_path / "artifact_root"
        root.mkdir()
        sub = root / "pack"
        sub.mkdir()
        f = sub / "blob.bin"
        f.write_bytes(b"xyz")

        class _Cfg:
            artifact_storage_root = str(root)
            sandbox_root = str(tmp_path / "sandboxes")

        monkeypatch.setattr("app.artifacts.service.settings", _Cfg())

        db.add(
            Artifact(
                id="store-1",
                space_id=SPACE,
                artifact_type="binary",
                title="blob.bin",
                storage_path="pack/blob.bin",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/store-1/export?{_auth_q()}")
        assert r.status_code == 200
        assert r.content == b"xyz"

    def test_export_404_no_content_no_file(self, client, db):
        db.add(
            Artifact(
                id="empty-1",
                space_id=SPACE,
                artifact_type="binary",
                title="x",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/empty-1/export?{_auth_q()}")
        assert r.status_code == 404

    def test_export_cross_space(self, client, db):
        ensure_space(db, "sp-x", "X")
        db.add(
            Artifact(
                id="other-art",
                space_id="sp-x",
                artifact_type="t",
                title="t",
                content="nope",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/other-art/export?{_auth_q()}")
        assert r.status_code == 404

    def test_global_artifact_type_filter(self, client, db):
        db.add(
            Artifact(
                id="g1",
                space_id=SPACE,
                artifact_type="alpha",
                title="a",
                exportable=True,
            )
        )
        db.add(
            Artifact(
                id="g2",
                space_id=SPACE,
                artifact_type="beta",
                title="b",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts?{_auth_q()}&artifact_type=alpha")
        assert r.status_code == 200
        assert {x["id"] for x in r.json()["items"]} == {"g1"}

    def test_preview_artifact_exports(self, client, db):
        db.add(
            Artifact(
                id="pv-1",
                space_id=SPACE,
                artifact_type="preview",
                title="pv",
                content="pv-body",
                preview=True,
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/pv-1/export?{_auth_q()}")
        assert r.status_code == 200
        assert b"pv-body" in r.content

    def test_export_does_not_mutate_row(self, client, db):
        db.add(
            Artifact(
                id="mut-1",
                space_id=SPACE,
                artifact_type="t",
                title="t",
                content="c",
                exportable=True,
            )
        )
        db.commit()
        art = db.query(Artifact).filter(Artifact.id == "mut-1").first()
        before = art.updated_at
        r = client.get(f"/api/v1/artifacts/mut-1/export?{_auth_q()}")
        assert r.status_code == 200
        db.refresh(art)
        assert art.updated_at == before

    def test_export_rejects_path_traversal_outside_artifact_root(self, client, db, tmp_path, monkeypatch):
        root = tmp_path / "aroot"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.bin").write_bytes(b"leak")

        class _Cfg:
            artifact_storage_root = str(root.resolve())
            sandbox_root = str((tmp_path / "sandboxes").resolve())

        monkeypatch.setattr("app.artifacts.service.settings", _Cfg())

        db.add(
            Artifact(
                id="trav-1",
                space_id=SPACE,
                artifact_type="bin",
                title="x",
                storage_path="../outside/secret.bin",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/trav-1/export?{_auth_q()}")
        assert r.status_code == 404

    def test_export_rejects_resolved_path_inside_sandbox_root(self, client, db, tmp_path, monkeypatch):
        root = tmp_path / "aroot"
        root.mkdir()
        sbx = root / "sandbox_area"
        sbx.mkdir()
        (sbx / "blocked.txt").write_bytes(b"no")

        class _Cfg:
            artifact_storage_root = str(root.resolve())
            sandbox_root = str(sbx.resolve())

        monkeypatch.setattr("app.artifacts.service.settings", _Cfg())

        db.add(
            Artifact(
                id="sbx-block",
                space_id=SPACE,
                artifact_type="bin",
                title="b",
                storage_path="sandbox_area/blocked.txt",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/sbx-block/export?{_auth_q()}")
        assert r.status_code == 404

    def test_export_rejects_file_resolved_under_sandbox_sibling(self, client, db, tmp_path, monkeypatch):
        root = tmp_path / "aroot"
        root.mkdir()
        sibling_sb = tmp_path / "sibling_sandbox"
        sibling_sb.mkdir()
        (sibling_sb / "secret.dat").write_bytes(b"x")

        class _Cfg:
            artifact_storage_root = str(root.resolve())
            sandbox_root = str(sibling_sb.resolve())

        monkeypatch.setattr("app.artifacts.service.settings", _Cfg())

        db.add(
            Artifact(
                id="sbx-sib",
                space_id=SPACE,
                artifact_type="bin",
                title="s",
                storage_path="../sibling_sandbox/secret.dat",
                exportable=True,
            )
        )
        db.commit()
        r = client.get(f"/api/v1/artifacts/sbx-sib/export?{_auth_q()}")
        assert r.status_code == 404
