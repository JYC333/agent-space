import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { loadActionRegistry } from "../src/modules/policy/actionRegistry";
import { computeDecision, type Registry } from "../src/modules/policy/gateway";

/**
 * Cross-language decision parity (Stage 5, gate P6 — done deterministically).
 *
 * The fixture is generated from the real Python `PolicyGateway._compute_decision`
 * over a request matrix that exercises every lifecycle branch, every hard
 * invariant, and every built-in rule
 * (`backend/tests/support/gen_policy_decision_parity.py`). This test runs the
 * TS `computeDecision` over the same requests and asserts the decision fields
 * are identical. If the two engines diverge, this fails — which is the
 * authority-flip gate: TS must produce the same decision Python does before any
 * routing flip.
 */

const fixturePath = join(__dirname, "fixtures", "policy_decision_parity.json");

interface ParityCase {
  request: Record<string, unknown>;
  decision: Record<string, unknown>;
}
const cases: ParityCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

const FIELDS = [
  "decision",
  "risk_level",
  "reason_code",
  "required_approver_role",
  "policy_rule_id",
  "policy_source",
  "approval_capability",
  "audit_code",
  "resource_type",
  "message",
  "action",
] as const;

let registry: Registry;
beforeAll(async () => {
  registry = await loadActionRegistry();
});

describe("policy decision parity (TS computeDecision vs Python)", () => {
  it("covers every lifecycle branch + invariant + rule", () => {
    expect(cases.length).toBeGreaterThanOrEqual(28);
  });

  for (const [i, c] of cases.entries()) {
    it(`case ${i}: ${c.request.action}`, () => {
      const req = { force_record: false, ...c.request } as never;
      const { decision } = computeDecision(registry, req);
      const normalized: Record<string, unknown> = {};
      for (const f of FIELDS) {
        normalized[f] = (decision as unknown as Record<string, unknown>)[f] ?? null;
      }
      expect(normalized).toEqual(c.decision);
    });
  }
});
