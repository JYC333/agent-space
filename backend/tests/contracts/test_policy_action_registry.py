"""Contract: the Python policy action registry matches the shared wire fixture.

The canonical action registry is a durable cross-language contract (Stage 5,
gate P3). The fixture
``packages/protocol/test/fixtures/policy_action_registry.json`` is the shared
snapshot; the TS parity test (``packages/protocol/test/policy.test.ts``)
asserts ``POLICY_ACTION_REGISTRY`` equals it, and this test asserts the Python
``app.policy.actions`` registry equals the same file. If either side changes an
action's enforcement metadata without updating the fixture (and the other
side), one of the two tests fails — which is the point: neither registry may
drift silently.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.policy.actions import list_action_definitions

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "protocol"
    / "test"
    / "fixtures"
    / "policy_action_registry.json"
)


def _serialize_registry() -> list[dict]:
    out: list[dict] = []
    for d in list_action_definitions():
        row = asdict(d)
        row["default_risk_level"] = d.default_risk_level.value
        row["default_decision"] = d.default_decision.value
        row["lifecycle_status"] = d.lifecycle_status.value
        row["record_failure_mode"] = d.record_failure_mode.value
        out.append(row)
    return out


def test_python_registry_matches_shared_fixture():
    expected = json.loads(_FIXTURE.read_text())
    actual = _serialize_registry()
    assert actual == expected, (
        "Python policy action registry diverged from the shared wire fixture. "
        "Regenerate the fixture and update packages/protocol/src/policy.ts in "
        "the same change."
    )


def test_reserved_actions_never_default_allow():
    for d in list_action_definitions():
        if d.lifecycle_status.value == "reserved":
            assert d.default_decision.value != "allow", d.action
