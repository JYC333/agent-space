"""Contract: ``PolicyPort`` is a faithful seam over ``PolicyGateway``.

These tests protect the migration seam introduced for the TS-first migration
(see ``.agent/architecture/TS_MIGRATION_STRATEGY.md``). They assert that:

- the concrete ``PolicyGateway`` structurally satisfies ``PolicyPort``, so
  callers may type against the port without behavior change; and
- a fake can stand in for the port — returning a scripted ALLOW decision or
  raising ``PolicyGateBlocked`` on a deny — without a database.

No DB is required — the port is a pure structural contract.
"""

from __future__ import annotations

import pytest

from app.policy import PolicyPort
from app.policy.decisions import Decision
from app.policy.exceptions import PolicyGateBlocked
from app.policy.control_plane_client import ControlPlanePolicyGateway
from app.policy.gateway import PolicyGateway
from tests.support.fake_policy import FakePolicyGateway


def test_concrete_gateway_satisfies_port():
    """The authority implementation must conform to the published seam."""
    assert issubclass(PolicyGateway, PolicyPort)
    assert issubclass(ControlPlanePolicyGateway, PolicyPort)


def test_port_is_reexported_from_facade():
    from app.policy import PolicyPort as FromFacade
    from app.policy.ports import PolicyPort as FromModule

    assert FromFacade is FromModule


def test_fake_satisfies_port():
    assert isinstance(FakePolicyGateway(), PolicyPort)


def test_fake_allows_and_records_request():
    fake = FakePolicyGateway()
    req = object()
    decision = fake.enforce(req)
    assert decision.allowed
    assert decision.decision is Decision.ALLOW
    assert fake.enforce_calls == [req]


def test_fake_blocks_on_enforce():
    fake = FakePolicyGateway(block=True)
    with pytest.raises(PolicyGateBlocked):
        fake.enforce(object())


def test_fake_proposal_apply_records_and_allows():
    fake = FakePolicyGateway()
    decision = fake.enforce_proposal_apply(
        user_id="u1", space_id="s1", proposal=object(), metadata_json={"k": "v"}
    )
    assert decision.allowed
    call = fake.proposal_apply_calls[-1]
    assert call["user_id"] == "u1"
    assert call["space_id"] == "s1"
    assert call["metadata_json"] == {"k": "v"}


def test_fake_blocks_on_proposal_apply():
    fake = FakePolicyGateway(block=True)
    with pytest.raises(PolicyGateBlocked):
        fake.enforce_proposal_apply(user_id="u1", space_id="s1", proposal=object())
