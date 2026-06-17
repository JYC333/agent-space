import { describe, expect, it } from "vitest";
import {
  dominantSourceTrust,
  firstActivityId,
  mergeDistinctProvenanceEntries,
  proposalProvenanceEntry,
  userConfirmationEntry,
} from "../src/modules/memory/memoryApplyProvenance";
import type { ProvenanceEntry } from "../src/modules/memory/sourceMonitoring";

const e = (source_type: string, source_id: string, source_trust?: string): ProvenanceEntry => ({
  source_type,
  source_id,
  ...(source_trust ? { source_trust } : {}),
});

describe("memory apply provenance helpers", () => {
  it("dominantSourceTrust ranks user_confirmed > trusted_external > internal_system > untrusted > agent", () => {
    expect(dominantSourceTrust([e("a", "1", "agent_inferred"), e("a", "2", "trusted_external")])).toBe(
      "trusted_external",
    );
    expect(
      dominantSourceTrust([e("a", "1", "internal_system"), e("a", "2", "trusted_external")]),
    ).toBe("trusted_external");
    expect(dominantSourceTrust([e("a", "1", "user_confirmed"), e("a", "2", "trusted_external")])).toBe(
      "user_confirmed",
    );
    expect(dominantSourceTrust([e("a", "1", "untrusted_external"), e("a", "2", "agent_inferred")])).toBe(
      "untrusted_external",
    );
    expect(dominantSourceTrust([e("a", "1")])).toBeNull(); // no valid trust
    expect(dominantSourceTrust([e("a", "1", "bogus")])).toBeNull();
  });

  it("firstActivityId returns the first activity source id", () => {
    expect(firstActivityId([e("proposal", "p"), e("activity", "act-1"), e("activity", "act-2")])).toBe(
      "act-1",
    );
    expect(firstActivityId([e("proposal", "p")])).toBeNull();
  });

  it("mergeDistinctProvenanceEntries dedups by (type, id, trust), stable order", () => {
    const merged = mergeDistinctProvenanceEntries(
      [e("activity", "a", "agent_inferred"), e("activity", "a", "agent_inferred")],
      [e("activity", "a", "user_confirmed"), e("proposal", "p", "internal_system")],
    );
    expect(merged.map((m) => `${m.source_type}:${m.source_id}:${m.source_trust ?? ""}`)).toEqual([
      "activity:a:agent_inferred",
      "activity:a:user_confirmed", // different trust → distinct
      "proposal:p:internal_system",
    ]);
  });

  it("entry builders set canonical trust + channel", () => {
    expect(userConfirmationEntry("u1")).toEqual({
      source_type: "user_confirmation",
      source_id: "u1",
      source_trust: "user_confirmed",
      evidence_json: { channel: "explicit_user_action" },
    });
    expect(proposalProvenanceEntry("p1", { proposal_type: "memory_create" })).toEqual({
      source_type: "proposal",
      source_id: "p1",
      source_trust: "internal_system",
      evidence_json: { proposal_type: "memory_create" },
    });
  });
});
