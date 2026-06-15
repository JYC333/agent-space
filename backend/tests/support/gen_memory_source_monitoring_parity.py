"""Generate the cross-language memory source-monitoring parity fixture.

Runs the real Python ``SourceMonitoringService.evaluate_memory_proposal`` (and
the ``provenance_entries_from_payload`` normalizer it consumes) over a matrix
that exercises every provenance-trust composition, accept context, memory
layer, and the legacy flat-key normalization. The TS ``evaluateMemoryProposal``
must match byte-for-byte — this is the apply security gate, so any divergence is
a governance hole.

Usage (from backend/):
    .venv/bin/python -m tests.support.gen_memory_source_monitoring_parity \
        > ../control-plane/test/fixtures/memory_source_monitoring_parity.json
"""

import json
import sys

sys.path.insert(0, ".")

from app.memory.source_monitoring import (  # noqa: E402
    SourceMonitoringService,
    monitoring_snapshot,
)

PROPOSAL_TYPES = ["memory_create", "memory_update", "memory_archive", "policy_change"]
ACCEPT_CONTEXTS = ["explicit_user_accept", "internal_seed", "direct_apply"]

# How the proposal signals semantic vs episodic.
MEMORY_CONFIGS = [
    {},
    {"memory_type": "semantic"},
    {"memory_type": "episodic"},
    {"memory_layer": "episodic"},
    {"target_layer": "episodic"},
]

# Trust compositions covering every gate branch (empty, single, mixed, invalid).
TRUST_COMBOS = [
    [],
    ["user_confirmed"],
    ["internal_system"],
    ["trusted_external"],
    ["untrusted_external"],
    ["agent_inferred"],
    ["agent_inferred", "user_confirmed"],
    ["agent_inferred", "untrusted_external"],
    ["untrusted_external", "trusted_external"],
    ["untrusted_external", "agent_inferred"],
    ["user_confirmed", "trusted_external"],
    ["bogus"],  # invalid trust → filtered out (entry survives without trust)
    [None],  # no trust key
]


def _entries_for(trusts: list) -> list[dict]:
    out = []
    for i, t in enumerate(trusts):
        e: dict = {"source_type": "activity", "source_id": f"act-{i}"}
        if t is not None:
            e["source_trust"] = t
        out.append(e)
    return out


def _cases() -> list[dict]:
    svc = SourceMonitoringService()
    cases: list[dict] = []

    for ptype in PROPOSAL_TYPES:
        for ctx in ACCEPT_CONTEXTS:
            for mem_cfg in MEMORY_CONFIGS:
                for combo in TRUST_COMBOS:
                    payload = dict(mem_cfg)
                    payload["provenance_entries"] = _entries_for(combo)
                    out = svc.evaluate_memory_proposal(
                        proposal_type=ptype,
                        payload=payload,
                        accept_context=ctx,  # type: ignore[arg-type]
                    )
                    cases.append(
                        {
                            "input": {
                                "proposal_type": ptype,
                                "accept_context": ctx,
                                "payload": payload,
                            },
                            "expected": monitoring_snapshot(out),
                        }
                    )

    # Legacy flat-key normalization paths.
    legacy_payloads = [
        {"source_activity_id": "a1", "activity_source_trust": "user_confirmed"},
        {"source_activity_id": "a1", "activity_source_trust": "agent_inferred"},
        {"source_activity_id": "a1", "source_evidence": "note text"},
        {"source_run_id": "r1"},  # → run_step internal_system (core trust)
        {"source_memory_id": "m1", "memory_source_trust": "trusted_external"},
        {"derived_from_memory_id": "m2", "memory_source_trust": "untrusted_external"},
        # Dedup: same entry twice collapses to one.
        {
            "provenance_entries": [
                {"source_type": "activity", "source_id": "dup", "source_trust": "agent_inferred"},
                {"source_type": "activity", "source_id": "dup", "source_trust": "agent_inferred"},
            ]
        },
        # Invalid source_type is dropped entirely.
        {"provenance_entries": [{"source_type": "not_a_type", "source_id": "x", "source_trust": "user_confirmed"}]},
    ]
    for ptype in ["memory_create", "memory_archive"]:
        for ctx in ["explicit_user_accept", "direct_apply"]:
            for payload in legacy_payloads:
                out = svc.evaluate_memory_proposal(
                    proposal_type=ptype,
                    payload=dict(payload),
                    accept_context=ctx,  # type: ignore[arg-type]
                )
                cases.append(
                    {
                        "input": {
                            "proposal_type": ptype,
                            "accept_context": ctx,
                            "payload": payload,
                        },
                        "expected": monitoring_snapshot(out),
                    }
                )

    return cases


def main() -> None:
    json.dump(_cases(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
