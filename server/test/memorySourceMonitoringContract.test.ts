import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  evaluateMemoryProposal,
  monitoringSnapshot,
  type AcceptContext,
} from "../src/modules/memory/sourceMonitoring";

/**
 * Memory source-monitoring compatibility fixture.
 *
 * The fixture covers every provenance-trust composition, accept context,
 * semantic/episodic signal, and legacy flat-key normalization. Because this is
 * the apply gate that decides reject / require_review / allow, any outcome
 * drift fails the build.
 */

const fixturePath = join(__dirname, "fixtures", "memory_source_monitoring_contract.json");

interface ContractCase {
  input: {
    proposal_type: string;
    accept_context: AcceptContext;
    payload: Record<string, unknown>;
  };
  expected: {
    action: string;
    reason_code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

const cases: ContractCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("memory source-monitoring compatibility", () => {
  it("matches the frozen proposal-evaluation fixture over every case", () => {
    expect(cases.length).toBeGreaterThan(0);
    for (const { input, expected } of cases) {
      const outcome = evaluateMemoryProposal({
        proposalType: input.proposal_type,
        payload: input.payload,
        acceptContext: input.accept_context,
      });
      expect(monitoringSnapshot(outcome)).toEqual(expected);
    }
  });
});
