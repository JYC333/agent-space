import json, sys
sys.path.insert(0, '.')
from app.policy.gateway import PolicyGateway, PolicyCheckRequest

# Representative request matrix exercising every lifecycle branch, every hard
# invariant, and every built-in rule. DB is never touched by _compute_decision.
cases = [
    {"action": "made.up.action"},
    {"action": "artifact.export"},  # reserved
    {"action": "memory.create"},    # wired_via_proposal
    {"action": "knowledge.update"}, # wired_via_proposal
    {"action": "runtime.execute"},
    {"action": "runtime.execute", "context": {"risk_level": "high"}},
    {"action": "runtime.execute", "context": {"tool_name": "codex_cli", "agent_tool_permissions": ["claude_code"]}},
    {"action": "runtime.execute", "context": {"agent_status": "disabled"}},
    {"action": "runtime.use_credential", "space_id": "s1", "resource_space_id": "s1", "context": {"trigger_origin": "manual"}},
    {"action": "runtime.use_credential", "space_id": "s1", "resource_space_id": "s1", "context": {"trigger_origin": "automation"}},
    {"action": "runtime.use_credential", "space_id": "s1", "resource_space_id": "s1", "context": {"trigger_origin": "automation", "automation_pre_authorized": True}},
    {"action": "runtime.use_credential", "space_id": "s1", "resource_space_id": "s2"},
    {"action": "context.inject_memory", "space_id": "s1", "resource_space_id": "s2"},
    {"action": "context.inject_memory", "space_id": "s1", "resource_space_id": "s2", "context": {"has_personal_memory_grant": True}},
    {"action": "context.inject_memory", "space_id": "s1", "resource_space_id": "s1"},
    {"action": "artifact.persist", "context": {"raw_private_memory_included": True}},
    {"action": "artifact.persist", "context": {"derived_from_personal_memory_grant": True, "target_visibility": "public"}},
    {"action": "artifact.persist", "context": {"target_space_id": "  "}},
    {"action": "artifact.persist", "space_id": "s1"},
    {"action": "workspace.write_patch", "proposal_id": "p1", "context": {"proposal_type": "code_patch", "proposal_apply_allowed": True}},
    {"action": "workspace.write_patch"},
    {"action": "automation.create", "context": {"membership_role": "admin"}},
    {"action": "automation.create", "context": {"membership_role": "member"}},
    {"action": "automation.fire", "context": {"membership_role": "owner"}},
    {"action": "proposal.create", "space_id": "s1"},
    {"action": "agent.config_update", "space_id": "s1"},
    {"action": "intake.item_create", "space_id": "s1"},
    {"action": "context.select_evidence", "space_id": "s1"},
]

FIELDS = ["decision", "risk_level", "reason_code", "required_approver_role",
          "policy_rule_id", "policy_source", "approval_capability", "audit_code",
          "resource_type", "message", "action"]

gw = PolicyGateway(db=None)
out = []
for c in cases:
    req = PolicyCheckRequest(
        action=c["action"],
        space_id=c.get("space_id"),
        resource_space_id=c.get("resource_space_id"),
        resource_id=c.get("resource_id"),
        proposal_id=c.get("proposal_id"),
        actor_id=c.get("actor_id"),
        actor_type=c.get("actor_type"),
        context=c.get("context"),
        payload=c.get("payload"),
        metadata_json=c.get("metadata_json"),
        force_record=c.get("force_record", False),
    )
    defn, dec = gw._compute_decision(req)
    norm = {}
    for f in FIELDS:
        v = getattr(dec, f, None)
        if hasattr(v, "value"):
            v = v.value
        norm[f] = v
    out.append({"request": c, "decision": norm})

print(json.dumps(out, indent=2))
