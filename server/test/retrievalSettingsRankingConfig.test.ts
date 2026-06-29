import { describe, expect, it } from "vitest";
import { updateSpaceRetrievalSettings } from "../src/modules/retrieval/settings";

function settingsRow(overrides: Record<string, unknown> = {}) {
  return {
    space_id: "space-1",
    default_search_mode: "hybrid",
    rerank_enabled: false,
    query_rewrite_enabled: false,
    query_rewrite_default: false,
    use_query_cache: true,
    include_trace: false,
    external_egress_enabled: true,
    retrieval_tool_mode: "off",
    context_ops_review_mode: "private_only",
    context_ops_scan_mode: "admins",
    embedding_dimensions: 2560,
    max_results_default: 50,
    ranking_config_json: {},
    created_at: "2026-06-26T00:00:00.000Z",
    updated_at: "2026-06-26T00:00:00.000Z",
    ...overrides,
  };
}

class FakeDb {
  constructor(private readonly artifact: Record<string, unknown> | null) {}
  current = settingsRow();

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: Row[]; rowCount: number | null }> {
    const norm = sql.replace(/\s+/g, " ").trim();
    if (norm.startsWith("INSERT INTO space_retrieval_settings")) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    if (/SELECT .* FROM space_retrieval_settings/.test(norm)) {
      return { rows: [this.current] as Row[], rowCount: 1 };
    }
    if (/FROM artifacts/.test(norm)) {
      return this.artifact?.visibility === "space_shared"
        ? { rows: [this.artifact] as Row[], rowCount: 1 }
        : { rows: [] as Row[], rowCount: 0 };
    }
    if (norm.startsWith("UPDATE space_retrieval_settings")) {
      this.current = settingsRow({
        ranking_config_json: JSON.parse(String(params[13])),
        updated_at: "2026-06-26T00:01:00.000Z",
      });
      return { rows: [this.current] as Row[], rowCount: 1 };
    }
    return { rows: [] as Row[], rowCount: 0 };
  }
}

describe("space retrieval ranking config", () => {
  it("ships a mechanic only after the calibration eval gate passes", async () => {
    const db = new FakeDb({
      metadata_json: {
        decisions: [{
          mechanic: "visible_edge_backlink",
          decision: "adopt",
          evidence_artifact_ids: ["artifact-eval"],
          eval_delta: { recall_at_10: 0.03 },
        }],
      },
      owner_user_id: "user-1",
      visibility: "space_shared",
    });

    const updated = await updateSpaceRetrievalSettings(db, "space-1", {
      ranking_config: {
        version: 1,
        eval_gate: { min_primary_metric_delta: 0.01, required_evidence_artifacts: 1 },
        mechanics: {
          visible_edge_backlink: {
            state: "shipped",
            calibration_artifact_id: "artifact-calibration",
            shipped_at: null,
            eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null },
          },
          candidate_owned_salience: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          richer_dedup: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          autocut: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          semantic_results_cache: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
        },
      },
    }, { actorUserId: "user-1" });

    expect(updated.ranking_config.mechanics.visible_edge_backlink.state).toBe("shipped");
    expect(updated.ranking_config.mechanics.visible_edge_backlink.eval_gate).toMatchObject({
      status: "passed",
      metric: "recall_at_10",
      value: 0.03,
      threshold: 0.01,
    });
  });

  it("rejects shipping without a visible adopted calibration artifact", async () => {
    const db = new FakeDb(null);
    await expect(updateSpaceRetrievalSettings(db, "space-1", {
      ranking_config: {
        version: 1,
        eval_gate: { min_primary_metric_delta: 0, required_evidence_artifacts: 1 },
        mechanics: {
          visible_edge_backlink: {
            state: "shipped",
            calibration_artifact_id: "missing",
            shipped_at: null,
            eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null },
          },
          candidate_owned_salience: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          richer_dedup: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          autocut: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          semantic_results_cache: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
        },
      },
    }, { actorUserId: "user-1" })).rejects.toThrow(/calibration artifact not found/);
  });

  it("rejects private calibration artifacts for space-wide runtime ranking settings", async () => {
    const db = new FakeDb({
      metadata_json: {
        decisions: [{
          mechanic: "visible_edge_backlink",
          decision: "adopt",
          evidence_artifact_ids: ["artifact-eval"],
          eval_delta: { recall_at_10: 0.03 },
        }],
      },
      owner_user_id: "user-1",
      visibility: "private",
    });

    await expect(updateSpaceRetrievalSettings(db, "space-1", {
      ranking_config: {
        version: 1,
        eval_gate: { min_primary_metric_delta: 0, required_evidence_artifacts: 1 },
        mechanics: {
          visible_edge_backlink: {
            state: "shipped",
            calibration_artifact_id: "private-calibration",
            shipped_at: null,
            eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null },
          },
          candidate_owned_salience: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          richer_dedup: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          autocut: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
          semantic_results_cache: { state: "disabled", calibration_artifact_id: null, shipped_at: null, eval_gate: { status: "not_run", metric: null, value: null, threshold: 0, checked_at: null } },
        },
      },
    }, { actorUserId: "user-1" })).rejects.toThrow(/calibration artifact not found/);
  });
});
