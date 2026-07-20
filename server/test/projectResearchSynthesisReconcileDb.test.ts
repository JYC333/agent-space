import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
import { migrate } from "../src/db/migrator";
import { ProjectResearchOrchestrator } from "../src/modules/projectResearch/orchestrator";
import { syncBuiltinPrompts } from "../src/modules/prompts/builtins";

// Real-Postgres coverage for reconcileOperation's synthesis stage. The
// synthesis run's terminal state is normally projected by a one-shot hook in
// the agent_run job handler; before this coverage existed the periodic
// reconciler ignored the synthesis stage entirely, so (a) the UI had no live
// run-status feedback at all while synthesis executed and (b) an operation
// whose one-shot projection was missed waited forever with no recovery.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const WORKFLOW = "66666666-6666-4666-8666-666666666666";
const OPERATION = "77777777-7777-4777-8777-777777777777";
const AGENT = "99999999-9999-4999-8999-999999999999";
const VERSION = "84444444-4444-4444-8444-444444444444";
const RUNTIME_PROFILE = "83333333-3333-4333-8333-333333333333";
const CATALOG_ROOT = join(process.cwd(), "..", "catalog");

let container: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await getTestPostgres(__filename);
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    await syncBuiltinPrompts(pool, CATALOG_ROOT);
    available = true;
  } catch (err) {
    console.warn(`[project-research-synthesis-reconcile-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE runs, agent_versions, agents, project_research_checkpoints, project_research_workflows,
       project_operations, project_members, projects, space_memberships, users, spaces CASCADE`,
  );
  const now = new Date().toISOString();
  await pool.query(`INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Main','personal',$2,$2)`, [SPACE, now]);
  await pool.query(`INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,$1,'active',$2,$2)`, [OWNER, now]);
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at) VALUES ($1,$2,$3,'owner','active',$4,$4)`,
    [randomUUID(), SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at) VALUES ($1,$2,$3,'Research','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO project_research_workflows (id, space_id, project_id, workflow_type, current_stage, status, mode, state_json, created_at, updated_at)
     VALUES ($1,$2,$3,'literature_review','synthesis','active','agent_assisted','{}'::jsonb,$4,$4)`,
    [WORKFLOW, SPACE, PROJECT, now],
  );
  await pool.query(
    `INSERT INTO agents (id, space_id, owner_user_id, name, status, current_version_id, created_at, updated_at, visibility)
     VALUES ($1,$2,$3,'Research Agent','active',NULL,$4,$4,'space_shared')`,
    [AGENT, SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO agent_versions (
       id, agent_id, space_id, version_label, system_prompt,
       model_config_json, runtime_config_json, context_policy_json,
       memory_policy_json, capabilities_json, tool_permissions_json,
       runtime_policy_json, created_at
     ) VALUES ($1, $2, $3, 'v1', 'Test agent.',
               '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
               '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, $4)`,
    [VERSION, AGENT, SPACE, now],
  );
  await pool.query(`UPDATE agents SET current_version_id=$2 WHERE id=$1`, [AGENT, VERSION]);
  await pool.query(
    `INSERT INTO agent_runtime_profiles (
       id,space_id,agent_id,name,adapter_type,runtime_config_json,runtime_policy_json,enabled,is_default,created_at,updated_at
     ) VALUES ($1,$2,$3,'Research','model_api','{}'::jsonb,'{}'::jsonb,true,true,$4,$4)`,
    [RUNTIME_PROFILE, SPACE, AGENT, now],
  );
  await syncBuiltinPrompts(pool, CATALOG_ROOT);
});

async function seedSynthesisRun(runId: string, status: string, contract: Record<string, unknown> | null, errorMessage: string | null = null): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO runs (
       id, space_id, agent_id, agent_version_id, run_type, trigger_origin, status, mode,
       adapter_type, instructed_by_user_id, owner_user_id, project_id,
       contract_snapshot_json, error_message, created_at, updated_at, started_at
     ) VALUES ($1,$2,$3,$4,'agent','system',$5,'live','model_api',$6,$6,$7,$8::jsonb,$9,$10,$10,$11)`,
    [
      runId, SPACE, AGENT, VERSION, status, OWNER, PROJECT,
      JSON.stringify(contract ?? {}),
      errorMessage,
      now,
      status === "queued" ? null : now,
    ],
  );
}

async function seedSynthesisOperation(runId: string | null): Promise<void> {
  const now = new Date().toISOString();
  const progress = {
    schema_version: "project_research_operation.v1",
    run_kind: "baseline",
    workflow_id: WORKFLOW,
    source_backfill_plan_ids: [],
    source_backfill_plan_id: null,
    current_stage: "synthesis",
    stage_state: "running",
    partial: false,
    channel_ids: [],
    source_item_ids: [],
    checkpoint_ids: [],
    artifact_ids: [],
    synthesis_run_id: runId,
    watermark: { before: null, after: null, overlap_hours: 48 },
  };
  await pool!.query(
    `INSERT INTO project_operations (id, space_id, project_id, kind, title, status, created_by_user_id, progress_json, created_at, updated_at)
     VALUES ($1,$2,$3,'research','Initial literature intake','active',$4,$5::jsonb,$6,$6)`,
    [OPERATION, SPACE, PROJECT, OWNER, JSON.stringify(progress), now],
  );
}

function synthesisContract(): Record<string, unknown> {
  return {
    workflow_input_json: {
      project_research: { workflow_id: WORKFLOW, operation_id: OPERATION, run_kind: "baseline", stage_key: "synthesis" },
    },
  };
}

function critiqueContract(): Record<string, unknown> {
  return {
    workflow_input_json: {
      project_research: { workflow_id: WORKFLOW, operation_id: OPERATION, run_kind: "baseline", stage_key: "synthesis_critique" },
    },
  };
}

const report = {
  schema_version: "research_report.v1",
  research_question: "Does X improve Y?",
  summary: "A bounded synthesis.",
  findings: [{ claim: "X may improve Y.", support: "multi-source evidence", references: [{ arxiv_id: "2601.12345" }] }],
  limitations: ["Coverage ends in 2026."],
  sources: [{ title: "Paper", authors: ["Author"], year: 2026, relevance: "relevant", summary: "Evidence.", references: [{ arxiv_id: "2601.12345" }] }],
  ideas: [],
};

async function seedCritiqueScenario(input: { depth: "quick" | "full"; round: number; revisionCount: number; output: Record<string, unknown> }): Promise<{ candidateRunId: string; critiqueRunId: string; archiveArtifactId: string }> {
  const candidateRunId = randomUUID();
  const critiqueRunId = randomUUID();
  const archiveArtifactId = randomUUID();
  await seedSynthesisRun(candidateRunId, "succeeded", synthesisContract());
  await seedSynthesisRun(critiqueRunId, "succeeded", critiqueContract());
  await pool!.query(`UPDATE runs SET output_json=$2::jsonb WHERE id=$1`, [critiqueRunId, JSON.stringify(input.output)]);
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO artifacts (
       id,space_id,run_id,project_id,artifact_type,surface_role,title,content,mime_type,
       exportable,export_formats_json,canonical_format,preview,created_at,updated_at,visibility,owner_user_id,trust_level
     ) VALUES ($1,$2,$3,$4,'research_report.archive.v1','system_archive','Draft',$5,'application/json',
       true,'["json"]'::jsonb,'json',false,$6,$6,'space_shared',$7,'high')`,
    [archiveArtifactId, SPACE, candidateRunId, PROJECT, JSON.stringify(report), now, OWNER],
  );
  await seedSynthesisOperation(critiqueRunId);
  await pool!.query(
    `UPDATE project_operations SET progress_json=progress_json || $2::jsonb WHERE id=$1`,
    [OPERATION, JSON.stringify({
      research_question: report.research_question,
      research_question_version: 1,
      report_depth: input.depth,
      question_refine_skipped: false,
      agent_id: AGENT,
      runtime_profile_id: RUNTIME_PROFILE,
      synthesis_critique: {
        status: "queued", run_id: critiqueRunId, report_run_id: candidateRunId,
        archive_artifact_id: archiveArtifactId, round: input.round, revision_count: input.revisionCount,
        issues: [], all_issues: [], artifact_ids: [],
      },
    })],
  );
  return { candidateRunId, critiqueRunId, archiveArtifactId };
}

describe("ProjectResearchOrchestrator.reconcileOperation synthesis stage (real Postgres)", () => {
  it("materializes a report only after a passing critique", async () => {
    if (!available || !pool) return;
    const seeded = await seedCritiqueScenario({ depth: "full", round: 0, revisionCount: 0, output: { verdict: "pass", issues: [] } });

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool.query<{ status: string; progress_json: Record<string, unknown> }>(`SELECT status,progress_json FROM project_operations WHERE id=$1`, [OPERATION]);
    expect(operation.rows[0]).toMatchObject({ status: "waiting_review", progress_json: { current_stage: "idea_review" } });
    const reports = await pool.query<{ synthesis_run_id: string }>(`SELECT synthesis_run_id FROM project_research_reports WHERE operation_id=$1`, [OPERATION]);
    expect(reports.rows).toEqual([{ synthesis_run_id: seeded.candidateRunId }]);
    const critiques = await pool.query<{ id: string; visibility: string; owner_user_id: string }>(
      `SELECT id,visibility,owner_user_id FROM artifacts WHERE run_id=$1 AND artifact_type='research_critique'`,
      [seeded.critiqueRunId],
    );
    expect(critiques.rows).toEqual([expect.objectContaining({ visibility: "private", owner_user_id: OWNER })]);
  });

  it("keeps quick reports bounded by recording critical critique issues without a revision run", async () => {
    if (!available || !pool) return;
    await seedCritiqueScenario({ depth: "quick", round: 0, revisionCount: 0, output: {
      verdict: "revise",
      issues: [{ severity: "critical", kind: "unsupported_claim", detail: "The main claim is too strong.", affected_refs: ["ref-1"] }],
    } });

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const stored = await pool.query<{ content_json: { limitations: string[] } }>(`SELECT content_json FROM project_research_reports WHERE operation_id=$1`, [OPERATION]);
    expect(stored.rows[0]!.content_json.limitations.some((item) => item.includes("[unresolved critique]") && item.includes("too strong"))).toBe(true);
    const revisionRuns = await pool.query(`SELECT id FROM runs WHERE contract_snapshot_json->'workflow_input_json'->'project_research'->>'stage_key'='synthesis_revision'`);
    expect(revisionRuns.rows).toHaveLength(0);
  });

  it("stops after one full-report revision and records a still-critical second critique", async () => {
    if (!available || !pool) return;
    await seedCritiqueScenario({ depth: "full", round: 1, revisionCount: 1, output: {
      verdict: "revise",
      issues: [{ severity: "critical", kind: "missing_contradiction", detail: "Contradictory evidence remains omitted.", affected_refs: ["ref-1"] }],
    } });

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const stored = await pool.query<{ content_json: { limitations: string[] } }>(`SELECT content_json FROM project_research_reports WHERE operation_id=$1`, [OPERATION]);
    expect(stored.rows[0]!.content_json.limitations.some((item) => item.includes("[unresolved critique]") && item.includes("Contradictory evidence"))).toBe(true);
    const operation = await pool.query<{ progress_json: Record<string, unknown> }>(`SELECT progress_json FROM project_operations WHERE id=$1`, [OPERATION]);
    expect(operation.rows[0]!.progress_json).toMatchObject({ current_stage: "idea_review", synthesis_critique: { revision_count: 1, status: "completed" } });
  });

  it("queues exactly one full-report revision after the first critical critique", async () => {
    if (!available || !pool) return;
    await seedCritiqueScenario({ depth: "full", round: 0, revisionCount: 0, output: {
      verdict: "revise",
      issues: [{ severity: "critical", kind: "overreach", detail: "The conclusion exceeds the evidence.", affected_refs: ["ref-1"] }],
    } });

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const revisionRuns = await pool.query<{ id: string; contract_snapshot_json: Record<string, unknown> }>(
      `SELECT id,contract_snapshot_json FROM runs WHERE contract_snapshot_json->'workflow_input_json'->'project_research'->>'stage_key'='synthesis_revision'`,
    );
    expect(revisionRuns.rows).toHaveLength(1);
    const operation = await pool.query<{ progress_json: Record<string, unknown> }>(`SELECT progress_json FROM project_operations WHERE id=$1`, [OPERATION]);
    expect(operation.rows[0]!.progress_json).toMatchObject({
      current_stage: "synthesis",
      synthesis_run_id: revisionRuns.rows[0]!.id,
      synthesis_critique: { revision_count: 1, status: "queued", run_id: revisionRuns.rows[0]!.id },
    });
  });

  it("writes a live synthesis_progress read model while the run is still executing", async () => {
    if (!available || !pool) return;
    const runId = randomUUID();
    await seedSynthesisRun(runId, "running", synthesisContract());
    const now = new Date().toISOString();
    const jobId = randomUUID();
    await pool.query(
      `INSERT INTO jobs (
         id, space_id, user_id, agent_id, job_type, status, priority, payload_json,
         attempts, max_attempts, created_at, updated_at, heartbeat_at
       ) VALUES ($1,$2,$3,$4,'agent_run','running',0,$5::jsonb,1,3,$6,$6,$6)`,
      [jobId, SPACE, OWNER, AGENT, JSON.stringify({ run_id: runId }), now],
    );
    await pool.query(
      `INSERT INTO run_events (
         id, space_id, run_id, event_index, event_type, status, summary, created_at
       ) VALUES ($1,$2,$3,0,'adapter_invoked','running','Synthesis adapter invoked',$4)`,
      [randomUUID(), SPACE, runId, now],
    );
    await seedSynthesisOperation(runId);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { current_stage?: string; synthesis_progress?: Record<string, unknown> } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("active");
    expect(operation.rows[0]!.progress_json.current_stage).toBe("synthesis");
    expect(operation.rows[0]!.progress_json.synthesis_progress).toMatchObject({
      run_id: runId,
      run_status: "running",
      job_id: jobId,
      job_status: "running",
      job_attempts: 1,
      last_event_type: "adapter_invoked",
    });
    expect(operation.rows[0]!.progress_json.synthesis_progress!.started_at).toBeTruthy();
    expect(operation.rows[0]!.progress_json.synthesis_progress!.job_heartbeat_at).toBeTruthy();
    expect(operation.rows[0]!.progress_json.synthesis_progress!.last_event_at).toBeTruthy();
  });

  it("fails the operation with the run's actual error detail when the synthesis run already failed (missed one-shot projection)", async () => {
    if (!available || !pool) return;
    const runId = randomUUID();
    await seedSynthesisRun(runId, "failed", synthesisContract(), "provider_rate_limited: model quota exhausted");
    await seedSynthesisOperation(runId);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { error?: { message?: string } } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(String(operation.rows[0]!.progress_json.error?.message ?? "")).toContain("provider_rate_limited: model quota exhausted");
  });

  it("propagates a semantic synthesis rejection and its suggestions to the operation API state", async () => {
    if (!available || !pool) return;
    const runId = randomUUID();
    await seedSynthesisRun(runId, "succeeded", synthesisContract());
    await pool.query(
      `UPDATE runs SET output_json=$2::jsonb WHERE id=$1 AND space_id=$3`,
      [runId, JSON.stringify({
        status: "rejected",
        artifacts: [],
        rejection: {
          code: "research_question_not_actionable",
          message: "The research question does not define an actionable synthesis target.",
          reason: "The value `test` is too vague to connect the approved papers into a defensible synthesis.",
          suggestions: ["Provide a specific research question or thematic lens."],
        },
        materialization: [],
      }), SPACE],
    );
    await seedSynthesisOperation(runId);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool.query<{
      status: string;
      progress_json: {
        error?: {
          code?: string;
          message?: string;
          rejection?: { code?: string; reason?: string; suggestions?: string[] };
        };
      };
    }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(operation.rows[0]!.progress_json.error).toMatchObject({
      code: "synthesis_rejected",
      message: "The research question does not define an actionable synthesis target.",
      rejection: {
        code: "research_question_not_actionable",
        reason: "The value `test` is too vague to connect the approved papers into a defensible synthesis.",
        suggestions: ["Provide a specific research question or thematic lens."],
      },
    });
  });

  it("never leaves a terminal run silently stuck: a succeeded run whose output cannot be applied fails the operation with a retryable message", async () => {
    if (!available || !pool) return;
    const runId = randomUUID();
    // Contract missing the project_research block — reconcileCompletedRun
    // cannot project it, so the fallback guard must fail the operation
    // instead of waiting forever.
    await seedSynthesisRun(runId, "succeeded", {});
    await seedSynthesisOperation(runId);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { error?: { message?: string } } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(String(operation.rows[0]!.progress_json.error?.message ?? "")).toContain("could not be applied");
  });

  it("adopts the newest synthesis run for the operation when the binding was lost and applies its terminal state", async () => {
    if (!available || !pool) return;
    const staleRunId = randomUUID();
    const latestRunId = randomUUID();
    await seedSynthesisRun(staleRunId, "degraded", synthesisContract(), "Research artifact research_report.archive.v1 is not valid JSON");
    await pool.query(`UPDATE runs SET created_at=created_at - interval '1 hour' WHERE id=$1`, [staleRunId]);
    await seedSynthesisRun(latestRunId, "failed", synthesisContract(), "structured_output_invalid: stub tool call");
    // The binding write was lost (e.g. skipped as a stale transition), so the
    // operation sits in synthesis with no bound run and would otherwise only
    // ever refresh its heartbeat.
    await seedSynthesisOperation(null);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { synthesis_run_id?: string | null; error?: { message?: string } } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(operation.rows[0]!.progress_json.synthesis_run_id).toBe(latestRunId);
    expect(String(operation.rows[0]!.progress_json.error?.message ?? "")).toContain("structured_output_invalid: stub tool call");
  });

  it("fails the operation into a retryable state when the synthesis stage has no bound run and no synthesis run exists", async () => {
    if (!available || !pool) return;
    await seedSynthesisOperation(null);

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { failed_stage?: string; error?: { message?: string } } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(operation.rows[0]!.progress_json.failed_stage).toBe("synthesis");
    expect(String(operation.rows[0]!.progress_json.error?.message ?? "")).toContain("no synthesis run bound");
  });

  it("fails the operation with a clear message when the queued synthesis run row no longer exists", async () => {
    if (!available || !pool) return;
    await seedSynthesisOperation(randomUUID());

    await new ProjectResearchOrchestrator(pool!).reconcileOperation(SPACE, OPERATION);

    const operation = await pool!.query<{ status: string; progress_json: { error?: { message?: string } } }>(
      `SELECT status, progress_json FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(operation.rows[0]!.status).toBe("failed");
    expect(String(operation.rows[0]!.progress_json.error?.message ?? "")).toContain("no longer exists");
  });

  it("completes an incremental comparison and writes contradictions into the notebook with a revision", async () => {
    if (!available || !pool) return;
    const now = new Date().toISOString(); const runId = randomUUID(); const sourceItem = randomUUID(); const notebook = randomUUID();
    await pool.query(`UPDATE project_research_workflows SET current_stage='comparison' WHERE id=$1`, [WORKFLOW]);
    await pool.query(`INSERT INTO research_notebooks (id,space_id,project_id,created_at,updated_at) VALUES ($1,$2,$3,$4,$4)`, [notebook, SPACE, PROJECT, now]);
    await pool.query(
      `INSERT INTO research_notebook_sections (id,space_id,notebook_id,section_key,content_json,normalized_text,content_hash,refs_json,version,updated_at)
       VALUES ($1,$2,$3,'understanding','{"type":"doc","content":[]}'::jsonb,'Current claim','hash','[]'::jsonb,1,$4)`,
      [randomUUID(), SPACE, notebook, now],
    );
    await pool.query(
      `INSERT INTO source_items (id,space_id,owner_user_id,visibility,item_type,title,excerpt,first_seen_at,last_seen_at,content_state,retention_policy,created_at,updated_at)
       VALUES ($1,$2,$3,'space_shared','feed_entry','Contradicting paper','No effect under stronger controls.',$4,$4,'excerpt_saved','summary_only',$4,$4)`,
      [sourceItem, SPACE, OWNER, now],
    );
    const corpusItemId = randomUUID();
    await pool.query(
      `INSERT INTO project_corpus_items (id,space_id,project_id,source_item_id,role,status,triage_status,triage_confirmed_by_user,read_status,created_at,updated_at)
       VALUES ($1,$2,$3,$4,'candidate','active','relevant',true,'unread',$5,$5)`,
      [corpusItemId, SPACE, PROJECT, sourceItem, now],
    );
    await pool.query(
      `INSERT INTO project_corpus_item_sources (id,corpus_item_id,space_id,project_id,source_item_id,created_at)
       VALUES ($1,$2,$3,$4,$5,$6)`,
      [randomUUID(), corpusItemId, SPACE, PROJECT, sourceItem, now],
    );
    await pool.query(
      `INSERT INTO project_operations (
         id, space_id, project_id, kind, title, status, created_by_user_id,
         progress_json, created_at, updated_at
       ) VALUES ($1, $2, $3, 'research', 'Monitor comparison', 'active', $4,
                 '{}'::jsonb, $5, $5)`,
      [OPERATION, SPACE, PROJECT, OWNER, now],
    );
    await pool.query(
      `INSERT INTO research_scan_summaries (id,space_id,project_id,workflow_id,operation_id,scan_key,scanned_at,new_item_count,relevant_count,maybe_count,excluded_count,created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,1,1,0,0,$7)`,
      [randomUUID(), SPACE, PROJECT, WORKFLOW, OPERATION, `operation:${OPERATION}`, now],
    );
    await seedSynthesisRun(runId, "succeeded", { workflow_input_json: { project_research: {
      workflow_id: WORKFLOW, operation_id: OPERATION, run_kind: "incremental", stage_key: "monitor_compare", source_item_ids: [sourceItem],
    } } });
    await pool.query(`UPDATE runs SET output_json=$2::jsonb WHERE id=$1`, [runId, JSON.stringify({ comparisons: [
      { source_item_id: sourceItem, stance: "contradicts", detail: "No effect under stronger controls.", affected_sections: ["understanding"] },
    ] })]);
    const progress = {
      schema_version: "project_research_operation.v1", run_kind: "incremental", workflow_id: WORKFLOW,
      current_stage: "comparison", stage_state: "running", comparison_run_id: runId,
      comparison_source_item_ids: [sourceItem], source_item_ids: [sourceItem], channel_ids: [], checkpoint_ids: [], artifact_ids: [],
      source_backfill_plan_ids: [], source_backfill_plan_id: null, partial: false, monitoring_active: false,
      watermark: { before: null, after: now, overlap_hours: 48 },
    };
    await pool.query(
      `UPDATE project_operations
          SET progress_json = $4::jsonb, updated_at = $5
        WHERE id = $1 AND space_id = $2 AND project_id = $3`,
      [OPERATION, SPACE, PROJECT, JSON.stringify(progress), now],
    );
    await new ProjectResearchOrchestrator(pool).reconcileOperation(SPACE, OPERATION);
    const operation = (await pool.query(`SELECT status,progress_json FROM project_operations WHERE id=$1`, [OPERATION])).rows[0];
    expect(operation).toMatchObject({ status: "completed", progress_json: { current_stage: "complete", monitoring_active: true } });
    expect((await pool.query(`SELECT stance,comparison_detail FROM research_paper_cards WHERE source_item_id=$1`, [sourceItem])).rows[0]).toEqual({ stance: "contradicts", comparison_detail: "No effect under stronger controls." });
    const section = (await pool.query(`SELECT id,version,normalized_text,refs_json,updated_by_run_id FROM research_notebook_sections WHERE notebook_id=$1 AND section_key='understanding'`, [notebook])).rows[0];
    expect(section).toMatchObject({ version: 2, refs_json: [sourceItem], updated_by_run_id: runId });
    expect(String(section?.normalized_text)).toContain("Contradiction");
    expect((await pool.query(`SELECT source,created_by_run_id FROM research_notebook_section_revisions WHERE section_id=$1 AND version=2`, [section?.id])).rows[0])
      .toEqual({ source: "ai_monitoring", created_by_run_id: runId });
  });

  it("applies ad-hoc notebook ops on run completion and degrades to a labeled append after a conflict", async () => {
    if (!available || !pool) return;
    const now = new Date().toISOString(); const notebook = randomUUID(); const sectionId = randomUUID();
    await pool.query(`INSERT INTO research_notebooks (id,space_id,project_id,created_at,updated_at) VALUES ($1,$2,$3,$4,$4)`, [notebook, SPACE, PROJECT, now]);
    await pool.query(
      `INSERT INTO research_notebook_sections (id,space_id,notebook_id,section_key,content_json,normalized_text,content_hash,refs_json,version,updated_at)
       VALUES ($1,$2,$3,'understanding','{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Old claim"}]},{"type":"paragraph","content":[{"type":"text","text":"Kept block"}]}]}'::jsonb,'Old claim\n\nKept block','hash','[]'::jsonb,3,$4)`,
      [sectionId, SPACE, notebook, now],
    );
    const adhocContract = (baseVersion: number) => ({ workflow_input_json: { research_adhoc: {
      notebook_id: notebook, section_key: "understanding", base_version: baseVersion, source_item_ids: [],
    } } });
    const output = { notebook_update: { section_key: "understanding", refs: ["source-9"], ops: [
      { op: "replace", index: 0, count: 1, markdown: "Revised claim", },
    ] } };
    const runId = randomUUID();
    await seedSynthesisRun(runId, "succeeded", adhocContract(3));
    await pool.query(`UPDATE runs SET output_json=$2::jsonb WHERE id=$1`, [runId, JSON.stringify(output)]);
    await new ProjectResearchOrchestrator(pool).reconcileRun(SPACE, runId);
    await new ProjectResearchOrchestrator(pool).reconcileRun(SPACE, runId);
    const applied = (await pool.query(`SELECT version,normalized_text,refs_json FROM research_notebook_sections WHERE id=$1`, [sectionId])).rows[0];
    expect(applied).toMatchObject({ version: 4, normalized_text: "Revised claim\n\nKept block", refs_json: ["source-9"] });
    expect(Number((await pool.query(`SELECT count(*) AS count FROM research_notebook_section_revisions WHERE section_id=$1`, [sectionId])).rows[0]?.count)).toBe(1);
    const staleRun = randomUUID();
    await seedSynthesisRun(staleRun, "succeeded", adhocContract(3));
    await pool.query(`UPDATE runs SET output_json=$2::jsonb WHERE id=$1`, [staleRun, JSON.stringify(output)]);
    await new ProjectResearchOrchestrator(pool).reconcileRun(SPACE, staleRun);
    const conflicted = (await pool.query(`SELECT version,normalized_text FROM research_notebook_sections WHERE id=$1`, [sectionId])).rows[0];
    expect(conflicted?.version).toBe(5);
    expect(String(conflicted?.normalized_text)).toContain("AI update (section changed since v3)");
    expect(String(conflicted?.normalized_text)).toContain("Kept block");
    expect((await pool.query(`SELECT source,diff_json FROM research_notebook_section_revisions WHERE section_id=$1 AND version=5`, [sectionId])).rows[0])
      .toMatchObject({ source: "ai_adhoc", diff_json: { conflict: true } });
  });
});
