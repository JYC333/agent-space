import { beforeAll, describe, expect, it } from "vitest";
import { loadActionRegistry } from "../src/modules/policy/actionRegistry";
import {
  checkHardInvariants,
  engineCheck,
  hasRoleAtLeast,
  normalizeRole,
} from "../src/modules/policy/decisionCore";
import {
  buildAuditEnvelope,
  checkProposalApplyPolicy,
  computeDecision,
  effectiveProposalRisk,
  isDurableAuditRequired,
  resolveFailureMode,
  SUPPORTED_PROPOSAL_TYPES,
  type Registry,
} from "../src/modules/policy/gateway";
import { sanitizePolicyMetadata } from "../src/modules/policy/sanitizer";

let registry: Registry;
beforeAll(async () => {
  registry = await loadActionRegistry();
});

function req(action: string, extra: Record<string, unknown> = {}) {
  return { action, force_record: false, ...extra } as never;
}

describe("roles", () => {
  it("normalizes unknown roles to guest", () => {
    expect(normalizeRole("ADMIN")).toBe("admin");
    expect(normalizeRole("superuser")).toBe("guest");
    expect(normalizeRole("")).toBe("guest");
  });
  it("ranks authority", () => {
    expect(hasRoleAtLeast("owner", "admin")).toBe(true);
    expect(hasRoleAtLeast("member", "admin")).toBe(false);
  });
});

describe("hard invariants", () => {
  it("denies cross-space memory read without grant", () => {
    const d = checkHardInvariants({
      action: "context.inject_memory",
      space_id: "s1",
      resource_space_id: "s2",
    });
    expect(d?.decision).toBe("deny");
    expect(d?.reason_code).toBe("hard_invariant_cross_space_memory");
    expect(d?.risk_level).toBe("critical");
  });
  it("allows same-space memory read", () => {
    expect(
      checkHardInvariants({
        action: "context.inject_memory",
        space_id: "s1",
        resource_space_id: "s1",
      }),
    ).toBeNull();
  });
  it("permits cross-space read with grant", () => {
    expect(
      checkHardInvariants({
        action: "context.inject_memory",
        space_id: "s1",
        resource_space_id: "s2",
        has_personal_memory_grant: true,
      }),
    ).toBeNull();
  });
  it("blocks raw private memory egress", () => {
    const d = checkHardInvariants({
      action: "artifact.persist",
      raw_private_memory_included: true,
    });
    expect(d?.audit_code).toBe("raw_private_memory_egress_blocked");
  });
  it("rejects approval-proof flags on proposal.apply", () => {
    const d = checkHardInvariants({
      action: "proposal.apply",
      payload: { is_approved: true },
    });
    expect(d?.reason_code).toBe("hard_invariant_payload_not_approval_proof");
  });
  it("rejects personal_context_block persistence", () => {
    const d = checkHardInvariants({
      action: "memory.create",
      metadata_json: { personal_context_block: "x" },
    });
    expect(d?.audit_code).toBe("personal_context_block_persist_attempt");
  });
  it("fails closed on empty target_space_id in egress", () => {
    const d = checkHardInvariants({
      action: "artifact.persist",
      target_space_id: "  ",
    });
    expect(d?.reason_code).toBe("hard_invariant_unknown_target_space");
  });
});

describe("engine + registry default", () => {
  it("unknown action fails closed", () => {
    const d = engineCheck(registry, { action: "made.up" });
    expect(d.decision).toBe("deny");
    expect(d.audit_code).toBe("unknown_policy_action");
  });
  it("runtime.execute defaults to allow", () => {
    const d = engineCheck(registry, { action: "runtime.execute" });
    expect(d.decision).toBe("allow");
  });
  it("runtime_skill.render requires enablement proof before allowing render", () => {
    const d = engineCheck(registry, {
      action: "runtime_skill.render",
      risk_level: "medium",
    });
    expect(d.decision).toBe("require_approval");
    expect(d.policy_rule_id).toBe("registry_default");
  });
  it("runtime_skill.render allows enabled bindings (review happens at enablement)", () => {
    const d = engineCheck(registry, {
      action: "runtime_skill.render",
      risk_level: "medium",
      enabled_binding: true,
      capability_enablement_id: "enable-1",
    });
    expect(d.decision).toBe("allow");
    expect(d.policy_rule_id).toBe("runtime_skill_render_enabled_binding");
  });
  it("runtime_skill.render allows enabled bindings even without a context risk_level", () => {
    const d = engineCheck(registry, {
      action: "runtime_skill.render",
      enabled_binding: true,
      capability_enablement_id: "enable-1",
    });
    expect(d.decision).toBe("allow");
    expect(d.policy_rule_id).toBe("runtime_skill_render_enabled_binding");
  });
  it("runtime_skill.render allows enabled high-risk bindings (enablement was the review gate)", () => {
    const d = engineCheck(registry, {
      action: "runtime_skill.render",
      risk_level: "high",
      enabled_binding: true,
      capability_enablement_id: "enable-1",
    });
    expect(d.decision).toBe("allow");
    expect(d.policy_rule_id).toBe("runtime_skill_render_enabled_binding");
    expect(d.risk_level).toBe("high");
  });
  it("runtime.use_credential same-space manual allows", () => {
    const d = engineCheck(registry, {
      action: "runtime.use_credential",
      space_id: "s1",
      resource_space_id: "s1",
      trigger_origin: "manual",
    });
    expect(d.decision).toBe("allow");
    expect(d.policy_rule_id).toBe("credential_same_space_manual_allow");
  });
  it("runtime.use_credential automation requires approval", () => {
    const d = engineCheck(registry, {
      action: "runtime.use_credential",
      space_id: "s1",
      resource_space_id: "s1",
      trigger_origin: "automation",
    });
    expect(d.decision).toBe("require_approval");
  });
  it("runtime.use_credential cross-space denies via space_boundary (runs before the credential rule)", () => {
    // rule_space_boundary precedes rule_use_credential, so a cross-space
    // credential request denies as space_boundary, not credential_cross_space.
    const d = engineCheck(registry, {
      action: "runtime.use_credential",
      space_id: "s1",
      resource_space_id: "s2",
    });
    expect(d.decision).toBe("deny");
    expect(d.reason_code).toBe("space_boundary");
  });
  it("tool not in permission list denies runtime.execute", () => {
    const d = engineCheck(registry, {
      action: "runtime.execute",
      tool_name: "codex_cli",
      agent_tool_permissions: ["claude_code"],
    });
    expect(d.decision).toBe("deny");
    expect(d.reason_code).toBe("tool_not_permitted");
  });
});

describe("computeDecision lifecycle gating", () => {
  it("reserved action denies before engine", () => {
    const { decision } = computeDecision(registry, req("artifact.export"));
    expect(decision.decision).toBe("deny");
    expect(decision.audit_code).toBe("policy_action_not_implemented");
  });
  it("wired_via_proposal action denies standalone", () => {
    const { decision } = computeDecision(registry, req("memory.create"));
    expect(decision.decision).toBe("deny");
    expect(decision.audit_code).toBe("policy_action_via_proposal_only");
  });
  it("wired_direct runtime.execute allows and back-fills actor", () => {
    const { decision } = computeDecision(
      registry,
      req("runtime.execute", { actor_id: "u1", space_id: "s1" }),
    );
    expect(decision.decision).toBe("allow");
    expect(decision.actor_id).toBe("u1");
    expect(decision.space_id).toBe("s1");
  });
});

describe("durable audit + failure mode", () => {
  it("use_credential allow is audit-required and fail-closed", () => {
    const r = req("runtime.use_credential", {
      space_id: "s1",
      resource_space_id: "s1",
      context: { trigger_origin: "manual" },
    });
    const { defn, decision } = computeDecision(registry, r);
    expect(isDurableAuditRequired(defn, decision, r)).toBe(true);
    expect(resolveFailureMode(defn, decision, r)).toBe("fail_closed");
  });
  it("context.inject_memory allow is best-effort, not required", () => {
    const r = req("context.inject_memory", { space_id: "s1" });
    const { defn, decision } = computeDecision(registry, r);
    expect(isDurableAuditRequired(defn, decision, r)).toBe(false);
    expect(resolveFailureMode(defn, decision, r)).toBe("best_effort");
  });
  it("automation-origin escalates to fail-closed", () => {
    const r = req("runtime.execute", {
      space_id: "s1",
      context: { trigger_origin: "automation" },
    });
    const { defn, decision } = computeDecision(registry, r);
    expect(resolveFailureMode(defn, decision, r)).toBe("fail_closed");
  });
  it("audit envelope sanitizes metadata and is secret-free", () => {
    const r = req("runtime.use_credential", {
      space_id: "s1",
      resource_space_id: "s1",
      metadata_json: { api_key: "sk-123", note: "ok" },
      context: { trigger_origin: "manual" },
    });
    const { defn, decision } = computeDecision(registry, r);
    const env = buildAuditEnvelope(r, decision, defn, "2026-06-14T00:00:00Z");
    expect(env.metadata_json).toEqual({ api_key: "[REDACTED]", note: "ok" });
  });
});

describe("sanitizer", () => {
  it("redacts nested dangerous keys and truncates", () => {
    const out = sanitizePolicyMetadata({
      ctx: { password: "x", ok: "y" },
      long: "a".repeat(600),
    }) as Record<string, Record<string, string> | string>;
    expect((out.ctx as Record<string, string>).password).toBe("[REDACTED]");
    expect((out.ctx as Record<string, string>).ok).toBe("y");
    expect((out.long as string).length).toBe(512);
  });
  it("returns null for null", () => {
    expect(sanitizePolicyMetadata(null)).toBeNull();
  });
});

describe("proposal.apply gate", () => {
  const base = {
    user_id: "u1",
    space_id: "s1",
    proposal_id: "p1",
    proposal_type: "memory_create",
    declared_risk: null,
    proposal_payload: {},
  };

  it("unsupported type denies", () => {
    const d = checkProposalApplyPolicy(
      { ...base, proposal_type: "weird_type" },
      "owner",
      SUPPORTED_PROPOSAL_TYPES,
    );
    expect(d.decision).toBe("deny");
    expect(d.audit_code).toBe("unsupported_proposal_type");
  });
  it("owner approves", () => {
    const d = checkProposalApplyPolicy(base, "owner", SUPPORTED_PROPOSAL_TYPES);
    expect(d.decision).toBe("allow");
    expect(d.audit_code).toBe("approved_owner");
  });
  it("reviewer cannot approve high-risk code_patch", () => {
    const d = checkProposalApplyPolicy(
      { ...base, proposal_type: "code_patch" },
      "reviewer",
      SUPPORTED_PROPOSAL_TYPES,
    );
    expect(d.decision).toBe("require_approval");
    expect(d.audit_code).toBe("insufficient_role");
  });
  it("admin approves high-risk but not critical", () => {
    const high = checkProposalApplyPolicy(
      { ...base, proposal_type: "code_patch" },
      "admin",
      SUPPORTED_PROPOSAL_TYPES,
    );
    expect(high.decision).toBe("allow");
    const crit = checkProposalApplyPolicy(
      { ...base, proposal_type: "code_patch", declared_risk: "critical" },
      "admin",
      SUPPORTED_PROPOSAL_TYPES,
    );
    expect(crit.decision).toBe("require_approval");
  });
  it("non-member requires approval", () => {
    const d = checkProposalApplyPolicy(base, null, SUPPORTED_PROPOSAL_TYPES);
    expect(d.decision).toBe("require_approval");
    expect(d.audit_code).toBe("no_membership");
  });
  it("effective risk is max(type_default, declared)", () => {
    expect(effectiveProposalRisk("memory_create", null)).toBe("medium");
    expect(effectiveProposalRisk("memory_create", "high")).toBe("high");
    expect(effectiveProposalRisk("code_patch", "low")).toBe("high");
  });
  it("invalid declared risk throws", () => {
    expect(() => effectiveProposalRisk("memory_create", "bogus")).toThrow();
  });
});
