import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import type { ApplyProposal } from "../src/modules/memory/memoryApplyRepository";
import { createDefaultProposalApplierRegistry } from "../src/modules/proposals/applierRegistry";

class FakeApplyDb {
  readonly dirtyUpdates: Array<{ kind: string; params: readonly unknown[] }> = [];
  readonly jobs: Array<{
    job_type: string;
    workspace_id: unknown;
    agent_id: unknown;
    payload: Record<string, unknown>;
  }> = [];
  readonly policies: Array<{
    name: unknown;
    domain: unknown;
    rule_json: unknown;
    applies_to_json: unknown;
  }> = [];

  async query(sql: string, params: readonly unknown[] = []) {
    const norm = sql.replace(/\s+/g, " ").trim();
    if (norm.startsWith("INSERT INTO policies")) {
      this.policies.push({
        name: params[2],
        domain: params[3],
        rule_json: params[8],
        applies_to_json: params[9],
      });
      return { rows: [], rowCount: 1 };
    }
    if (norm.startsWith("UPDATE context_digests")) {
      const kind = norm.includes("digest_type = 'policy_bundle'")
        ? "policy_bundle"
        : norm.includes("digest_type = 'workspace'")
          ? "workspace"
          : "agent";
      this.dirtyUpdates.push({ kind, params });
      return { rows: [], rowCount: 1 };
    }
    if (norm.startsWith("INSERT INTO jobs")) {
      this.jobs.push({
        job_type: String(params[5]),
        workspace_id: params[3],
        agent_id: params[4],
        payload: JSON.parse(String(params[7])) as Record<string, unknown>,
      });
      return {
        rows: [{
          id: String(params[0]),
          space_id: params[1],
          user_id: params[2],
          workspace_id: params[3],
          agent_id: params[4],
          job_type: params[5],
          status: "pending",
          priority: params[6],
          payload_json: JSON.parse(String(params[7])),
          result_json: null,
          error: null,
          attempts: 0,
          max_attempts: params[8],
          scheduled_at: params[9],
          claimed_by: null,
          claimed_at: null,
          started_at: null,
          completed_at: null,
          heartbeat_at: null,
          created_at: params[10],
          updated_at: params[10],
        }],
        rowCount: 1,
      };
    }
    if (norm.startsWith("UPDATE proposals")) {
      return { rows: [], rowCount: 1 };
    }
    if (norm.startsWith("UPDATE policies SET status = 'superseded'")) {
      return { rows: [], rowCount: 1 };
    }
    return { rows: [], rowCount: 0 };
  }
}

function proposal(overrides: Partial<ApplyProposal> = {}): ApplyProposal {
  return {
    id: "proposal-1",
    space_id: "space-1",
    proposal_type: "policy_change",
    title: "Change policy",
    workspace_id: null,
    created_by_user_id: "user-1",
    payload_json: {
      name: "Scoped policy",
      domain: "runtime",
      policy_json: { rule: "Use safe defaults." },
      rule_json: { effect: "allow" },
      applies_to_json: {
        workspace_ids: ["ws-1", "ws-1"],
        agents: [{ id: "agent-1" }],
      },
    },
    ...overrides,
  };
}

describe("proposal applier registry", () => {
  it("registers the code_patch proposal applier", () => {
    expect(createDefaultProposalApplierRegistry().registeredTypes()).toContain("code_patch");
  });

  it("refreshes only the policy_bundle digest, ignoring policy applies_to scopes", async () => {
    const db = new FakeApplyDb();

    const result = await createDefaultProposalApplierRegistry().apply({
      config: loadConfig({
        SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
        SERVER_INTERNAL_TOKEN: "internal-token",
      }),
      db: db as never,
      proposal: proposal(),
      userId: "user-1",
    });

    expect(result.result_type).toBe("policy_version");
    expect(db.policies[0]).toMatchObject({
      name: "Scoped policy",
      domain: "runtime",
      rule_json: JSON.stringify({ effect: "allow" }),
      applies_to_json: JSON.stringify({
        workspace_ids: ["ws-1", "ws-1"],
        agents: [{ id: "agent-1" }],
      }),
    });
    // Policies live only in the space-level policy_bundle. Even though this
    // policy's applies_to references ws-1 and agent-1, their memory-only digests
    // must NOT be invalidated (it would be a no-op refresh). Scoped policies are
    // surfaced per-run at consumption time, not folded into workspace/agent digests.
    expect(db.dirtyUpdates.map((u) => u.kind)).toEqual(["policy_bundle"]);
    expect(db.jobs.map((j) => j.payload)).toEqual([
      { space_id: "space-1", digest_type: "policy_bundle" },
    ]);
    expect(db.jobs.filter((j) => j.payload.digest_type === "workspace")).toHaveLength(0);
    expect(db.jobs.filter((j) => j.payload.digest_type === "agent")).toHaveLength(0);
  });
});
