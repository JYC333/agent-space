import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  evaluateMemoryProposal,
  monitoringSnapshot,
  type AcceptContext,
} from "../src/modules/memory/sourceMonitoring";

/**
 * Cross-language memory source-monitoring parity (Stage 6 slice 7b flip gate).
 *
 * The fixture is generated from the real Python
 * `SourceMonitoringService.evaluate_memory_proposal` over a matrix covering every
 * provenance-trust composition, accept context, semantic/episodic signal, and
 * the legacy flat-key normalization
 * (`backend/tests/support/gen_memory_source_monitoring_parity.py`). This runs the
 * TS evaluator over the same inputs and asserts identical outcomes. Because this
 * is the apply gate that decides reject / require_review / allow, any divergence
 * fails the build.
 */

const fixturePath = join(__dirname, "fixtures", "memory_source_monitoring_parity.json");

interface ParityCase {
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

const cases: ParityCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("memory source-monitoring parity (TS vs Python)", () => {
  it("matches Python evaluate_memory_proposal over every fixture case", () => {
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
