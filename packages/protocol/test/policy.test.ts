import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  POLICY_ACTION_REGISTRY,
  PolicyActionDefinitionSchema,
  PolicyAuditEnvelopeSchema,
  PolicyCheckRequestSchema,
  PolicyDecisionSchema,
  PolicyEnforceResultSchema,
  PolicyProposalApplyRequestSchema,
} from "../src/policy.js";

/**
 * The canonical action registry fixture is generated from the Python
 * `app.policy.actions` registry (`list_action_definitions()`), and the Python
 * contract test (`backend/tests/contracts/test_policy_action_registry.py`)
 * asserts the same file. It is the shared source of truth: if either side
 * diverges, one of the two tests fails.
 */
const fixturePath = fileURLToPath(
  new URL("./fixtures/policy_action_registry.json", import.meta.url),
);
const pythonRegistry = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("policy action registry", () => {
  it("every TS entry validates against the definition schema", () => {
    for (const def of POLICY_ACTION_REGISTRY) {
      expect(() => PolicyActionDefinitionSchema.parse(def)).not.toThrow();
    }
  });

  it("action names are unique", () => {
    const names = POLICY_ACTION_REGISTRY.map((d) => d.action);
    expect(new Set(names).size).toBe(names.length);
  });

  it("matches the Python registry 1:1 (count, order, and every field)", () => {
    expect(POLICY_ACTION_REGISTRY.length).toBe(pythonRegistry.length);
    // Deep, order-sensitive equality — registries must be byte-identical data.
    expect(POLICY_ACTION_REGISTRY.map((d) => ({ ...d }))).toEqual(
      pythonRegistry,
    );
  });

  it("reserved actions never default to allow", () => {
    for (const def of POLICY_ACTION_REGISTRY) {
      if (def.lifecycle_status === "reserved") {
        expect(def.default_decision).not.toBe("allow");
      }
    }
  });
});

describe("policy enforcement request/decision contracts", () => {
  it("accepts a minimal enforce request", () => {
    const req = PolicyCheckRequestSchema.parse({ action: "runtime.execute" });
    expect(req.force_record).toBe(false);
  });

  it("rejects unknown top-level fields (strict)", () => {
    expect(() =>
      PolicyCheckRequestSchema.parse({
        action: "runtime.execute",
        approved_by_user: true,
      }),
    ).toThrow();
  });

  it("decision defaults match the Python dataclass", () => {
    const dec = PolicyDecisionSchema.parse({
      decision: "allow",
      message: "ok",
    });
    expect(dec.risk_level).toBe("low");
    expect(dec.policy_source).toBe("builtin");
  });

  it("proposal-apply request requires user/space/proposal identity", () => {
    expect(() =>
      PolicyProposalApplyRequestSchema.parse({
        space_id: "s1",
        proposal_id: "p1",
        proposal_type: "memory_create",
      }),
    ).toThrow();
    const ok = PolicyProposalApplyRequestSchema.parse({
      user_id: "u1",
      space_id: "s1",
      proposal_id: "p1",
      proposal_type: "memory_create",
      membership_role: "owner",
      supported_proposal_types: ["memory_create"],
    });
    expect(ok.user_id).toBe("u1");
    expect(ok.supported_proposal_types).toEqual(["memory_create"]);
  });

  it("audit envelope requires a created_at timestamp", () => {
    expect(() =>
      PolicyAuditEnvelopeSchema.parse({
        action: "runtime.use_credential",
        decision: "allow",
        risk_level: "high",
      }),
    ).toThrow();
  });

  it("enforce result models allow / blocked / error", () => {
    expect(
      PolicyEnforceResultSchema.parse({
        status: "blocked",
        error_code: "policy_requires_approval",
      }).status,
    ).toBe("blocked");
  });
});
