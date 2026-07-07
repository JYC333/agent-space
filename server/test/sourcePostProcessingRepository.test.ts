import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import {
  PgSourcePostProcessingRepository,
  SOURCE_POST_PROCESSING_TASK_TYPE,
  normalizeActions,
  normalizeInputConfig,
  normalizeTriggerConfig,
} from "../src/modules/intake/postProcessing/repository";
import type { SourceConnectionRow } from "../src/modules/intake/intakeRepositoryRows";

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const AGENT = "77777777-7777-4777-8777-777777777777";
const AGENT_VERSION = "88888888-8888-4888-8888-888888888888";
const CONNECTOR = "33333333-3333-4333-8333-333333333333";
const CONNECTION = "44444444-4444-4444-8444-444444444444";

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (err) {
    console.warn(
      `[source-post-processing-db] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE source_post_processing_item_decisions, source_post_processing_runs, source_post_processing_rules,
       jobs, retrieval_edges, retrieval_chunks, retrieval_aliases, retrieval_objects,
       extracted_evidence, intake_items, scheduler_tasks, source_connections,
       source_connectors, agent_runtime_profiles, agent_versions, agents,
       projects, space_memberships, users, spaces CASCADE`,
  );
  const now = new Date().toISOString();
  await pool.query(
    `INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Main','personal',$2,$2)`,
    [SPACE, now],
  );
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,'Owner','active',$2,$2)`,
    [OWNER, now],
  );
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,'owner','active',$4,$4)`,
    [randomUUID(), SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at)
     VALUES ($1,$2,$3,'Research','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO agents (id, space_id, owner_user_id, name, status, current_version_id, created_at, updated_at, visibility)
     VALUES ($1,$2,$3,'Reusable Intake Agent','active',NULL,$4,$4,'space_shared')`,
    [AGENT, SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO agent_versions (
       id, agent_id, space_id, version_label, system_prompt, model_config_json,
       runtime_config_json, context_policy_json, memory_policy_json,
       capabilities_json, tool_permissions_json, runtime_policy_json, created_at
     ) VALUES ($1,$2,$3,'v1','Summarize intake','{}'::jsonb,'{"adapter_type":"model_api"}'::jsonb,
       '{}'::jsonb,'{}'::jsonb,'[]'::jsonb,'{}'::jsonb,'{}'::jsonb,$4)`,
    [AGENT_VERSION, AGENT, SPACE, now],
  );
  await pool.query(`UPDATE agents SET current_version_id = $2 WHERE id = $1`, [AGENT, AGENT_VERSION]);
  await pool.query(
    `INSERT INTO agent_runtime_profiles (
       id, space_id, agent_id, name, adapter_type, model_provider_id, model_name,
       runtime_config_json, runtime_policy_json, enabled, is_default, created_at, updated_at
     ) VALUES ($1,$2,$3,'Default','model_api',NULL,NULL,
       '{"adapter_type":"model_api"}'::jsonb,'{"default_adapter_type":"model_api"}'::jsonb,true,true,$4,$4)`,
    [randomUUID(), SPACE, AGENT, now],
  );
  await pool.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES ($1,'rss','RSS','external_feed','pull','active','{}'::jsonb,$2,$2)`,
    [CONNECTOR, now],
  );
  await pool.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status,
       fetch_frequency, capture_policy, trust_level, consent_json, policy_json,
       config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'arXiv','https://example.org/rss','active',
       'daily','reference_only','normal','{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$5,$5)`,
    [CONNECTION, SPACE, CONNECTOR, OWNER, now],
  );
});

function repo(): PgSourcePostProcessingRepository {
  return new PgSourcePostProcessingRepository(pool!);
}

class FakePostProcessingDb {
  calls: Array<{ sql: string; params: unknown[] }> = [];

  async query<T>(sql: string, params: unknown[] = []): Promise<{ rows: T[] }> {
    this.calls.push({ sql, params });
    return { rows: [{ id: "job-1", intake_item_id: "item-1" } as T] };
  }
}

function sourceConnection(overrides: Partial<SourceConnectionRow> = {}): SourceConnectionRow {
  const now = new Date().toISOString();
  return {
    id: CONNECTION,
    space_id: SPACE,
    connector_id: CONNECTOR,
    owner_user_id: OWNER,
    credential_id: null,
    name: "arXiv",
    endpoint_url: "https://example.org/rss",
    status: "active",
    fetch_frequency: "daily",
    capture_policy: "extract_text",
    trust_level: "normal",
    topic_hints_json: [],
    consent_json: {},
    policy_json: {},
    config_json: {},
    last_checked_at: null,
    next_check_at: null,
    schedule_rule_json: {},
    handler_kind: "rss",
    active_handler_version_id: null,
    active_recipe_version_id: null,
    repair_status: "ok",
    last_handler_run_id: null,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

async function seedItem(title: string, createdAt: string): Promise<string> {
  const id = randomUUID();
  await pool!.query(
    `INSERT INTO intake_items (
       id, space_id, connection_id, item_type, source_object_type, source_object_id,
       title, source_uri, excerpt, first_seen_at, last_seen_at, status, read_status,
       content_state, retention_policy, created_at, updated_at
     ) VALUES ($1,$2,$3,'external_url','intake_item',$1,$4,$6,'Paper abstract',
       $5,$5,'new','unread','excerpt_saved','summary_only',$5,$5)`,
    [id, SPACE, CONNECTION, title, createdAt, `https://example.org/paper/${id}`],
  );
  return id;
}

async function seedEvidence(itemId: string, title: string): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO extracted_evidence (
       id, space_id, intake_item_id, source_object_type, source_object_id,
       evidence_type, title, content_excerpt, trust_level, extraction_method,
       confidence, status, metadata_json, created_at, updated_at
     ) VALUES ($1,$2,$3,'intake_item',$3,'excerpt',$4,'Important excerpt',
       'normal','manual',0.8,'candidate','{}'::jsonb,$5,$5)`,
    [id, SPACE, itemId, title, now],
  );
  return id;
}

describe("source post-processing config normalization", () => {
  it("preserves preset content profile hints", () => {
    expect(normalizeInputConfig({
      content_profile: "arxiv_new_papers",
      summary_goal: "Summarize newly captured arXiv papers for categories: cs.AI.",
      output_instructions: "Include arXiv ids and categories.",
    })).toMatchObject({
      content_profile: "arxiv_new_papers",
      summary_goal: "Summarize newly captured arXiv papers for categories: cs.AI.",
      output_instructions: "Include arXiv ids and categories.",
    });
  });
});

describe("source post-processing repository queue helpers", () => {
  it("allows extracted text queueing for items that only have saved snapshots", async () => {
    const db = new FakePostProcessingDb();
    await new PgSourcePostProcessingRepository(db as never).queueFullTextExtractionForItems({
      spaceId: SPACE,
      connection: sourceConnection(),
      itemIds: ["item-1"],
      metadata: { source: "test" },
    });

    const sql = db.calls[0]?.sql ?? "";
    expect(sql).toContain("ii.content_state <> 'content_saved'");
    expect(sql).not.toContain("snapshot_saved");
  });

  it("appends source post-processing follow-ups instead of overwriting extraction metadata", async () => {
    const db = new FakePostProcessingDb();
    await new PgSourcePostProcessingRepository(db as never).queueFullTextExtractionForItems({
      spaceId: SPACE,
      connection: sourceConnection(),
      itemIds: ["item-1"],
      metadata: {
        source: "source_post_processing",
        source_post_processing_followups: [{
          phase: "deep_analysis",
          source_post_processing_rule_id: "rule-1",
          source_post_processing_run_id: "run-1",
        }],
      },
    });

    const sql = db.calls[0]?.sql ?? "";
    expect(sql).toContain("source_post_processing_followups");
    expect(sql).toContain("jsonb_build_object");
    expect(sql).toContain("|| COALESCE");
  });
});

describe("source post-processing repository (real Postgres)", () => {
  it("creates, lists, updates, and archives source-level rules", async () => {
    if (!available) return;
    const created = await repo().createRule({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: PROJECT,
      name: "Daily digest",
      triggerType: "items_materialized",
      triggerConfig: normalizeTriggerConfig({ min_new_items: 2, cooldown_seconds: 60 }, "items_materialized"),
      inputConfig: normalizeInputConfig({ item_limit: 10, include_evidence: false }),
      actions: normalizeActions({ batch_digest: true }),
      createdByUserId: OWNER,
    });

    expect(created).toMatchObject({
      source_connection_id: CONNECTION,
      agent_id: AGENT,
      project_id: PROJECT,
      status: "active",
      trigger_type: "items_materialized",
      actions_json: { batch_digest: true, create_proposals: false },
    });

    const listed = await repo().listRules(SPACE, CONNECTION);
    expect(listed.map((rule) => rule.id)).toEqual([created.id]);

    const updated = await repo().updateRule(SPACE, created.id, {
      status: "paused",
      projectId: null,
      actions: normalizeActions({ batch_digest: true, create_proposals: true }),
    });
    expect(updated.status).toBe("paused");
    expect(updated.project_id).toBeNull();
    expect(updated.actions_json.create_proposals).toBe(true);
  });

  it("collects source input by rule cursor and includes item evidence", async () => {
    if (!available) return;
    const first = await seedItem("Paper A", "2026-07-01T00:00:00.000Z");
    const second = await seedItem("Paper B", "2026-07-02T00:00:00.000Z");
    await seedEvidence(first, "Evidence A");

    const inputConfig = normalizeInputConfig({ item_limit: 10, include_evidence: true });
    const initial = await repo().collectInputBatch({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      inputConfig,
      cursor: null,
    });
    expect(initial.items.map((item) => item.id)).toEqual([first, second]);
    expect(initial.evidence.map((row) => row.intake_item_id)).toEqual([first]);
    expect(initial.cursorAfter).toMatchObject({ id: second, created_at: "2026-07-02T00:00:00.000Z" });

    const next = await repo().collectInputBatch({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      inputConfig,
      cursor: { id: first, created_at: "2026-07-01T00:00:00.000Z" },
    });
    expect(next.items.map((item) => item.id)).toEqual([second]);
    expect(next.evidence).toHaveLength(0);
  });

  it("records runs and advances per-rule cursor explicitly", async () => {
    if (!available) return;
    const itemId = await seedItem("Paper A", "2026-07-01T00:00:00.000Z");
    const rule = await repo().createRule({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: null,
      name: "Digest",
      triggerType: "manual",
      triggerConfig: normalizeTriggerConfig(null, "manual"),
      inputConfig: normalizeInputConfig(null),
      actions: normalizeActions(null),
      createdByUserId: OWNER,
    });
    const cursorAfter = { id: itemId, created_at: "2026-07-01T00:00:00.000Z" };
    const run = await repo().createRun({
      spaceId: SPACE,
      ruleId: rule.id,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: null,
      triggeredByUserId: OWNER,
      triggerType: "manual",
      inputItemIds: [itemId],
      inputEvidenceIds: [],
      cursorBefore: null,
      cursorAfter,
    });
    const finished = await repo().markRunFinished({
      runId: run.id,
      spaceId: SPACE,
      status: "succeeded",
      outputArtifactIds: ["artifact-1"],
      summary: "Digest complete",
    });
    expect(finished).toMatchObject({
      status: "succeeded",
      input_item_ids: [itemId],
      output_artifact_ids: ["artifact-1"],
      summary: "Digest complete",
    });

    await repo().advanceRuleCursor({ spaceId: SPACE, ruleId: rule.id, cursor: cursorAfter });
    const reloaded = await repo().getRule(SPACE, rule.id);
    expect(reloaded?.cursor_json).toMatchObject({ intake_watermark: cursorAfter });
  });

  it("refreshes intake retrieval projections after applying item decisions", async () => {
    if (!available) return;
    const selected = await seedItem("Relevant paper", "2026-07-01T00:00:00.000Z");
    const ignored = await seedItem("Skipped paper", "2026-07-02T00:00:00.000Z");

    await repo().applyItemDecisions(SPACE, [
      {
        intake_item_id: selected,
        relevance: "relevant",
        confidence: 0.9,
        reason: "Strong match.",
        matched_context_refs: [],
      },
      {
        intake_item_id: ignored,
        relevance: "not_relevant",
        confidence: 0.8,
        reason: "No clear match.",
        matched_context_refs: [],
      },
    ]);

    const statuses = await pool!.query<{ id: string; status: string }>(
      `SELECT id, status FROM intake_items WHERE id = ANY($1::varchar[]) ORDER BY id`,
      [[selected, ignored]],
    );
    expect(Object.fromEntries(statuses.rows.map((row) => [row.id, row.status]))).toMatchObject({
      [selected]: "selected",
      [ignored]: "ignored",
    });

    const projections = await pool!.query<{ object_id: string; status: string }>(
      `SELECT object_id, status
         FROM retrieval_objects
        WHERE space_id = $1 AND object_type = 'intake_item'
        ORDER BY object_id`,
      [SPACE],
    );
    expect(projections.rows).toEqual([{ object_id: selected, status: "selected" }]);
  });

  it("reports backlog counts from the rule cursor", async () => {
    if (!available) return;
    const first = await seedItem("Paper A", "2026-07-01T00:00:00.000Z");
    const second = await seedItem("Paper B", "2026-07-02T00:00:00.000Z");
    const rule = await repo().createRule({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: null,
      name: "Backlog digest",
      triggerType: "items_materialized",
      triggerConfig: normalizeTriggerConfig(null, "items_materialized"),
      inputConfig: normalizeInputConfig({ item_limit: 1, max_batches_per_event: 3 }),
      actions: normalizeActions(null),
      createdByUserId: OWNER,
    });

    const before = await repo().backlog(SPACE, CONNECTION);
    expect(before.rules.find((row) => row.rule_id === rule.id)).toMatchObject({
      pending_item_count: 2,
      batch_size: 1,
      max_batches_per_event: 3,
    });

    await repo().advanceRuleCursor({
      spaceId: SPACE,
      ruleId: rule.id,
      cursor: { id: first, created_at: "2026-07-01T00:00:00.000Z" },
    });
    const after = await repo().backlog(SPACE, CONNECTION);
    expect(after.rules.find((row) => row.rule_id === rule.id)?.pending_item_count).toBe(1);
    await repo().advanceRuleCursor({
      spaceId: SPACE,
      ruleId: rule.id,
      cursor: { id: second, created_at: "2026-07-02T00:00:00.000Z" },
    });
    const drained = await repo().backlog(SPACE, CONNECTION);
    expect(drained.rules.find((row) => row.rule_id === rule.id)?.pending_item_count).toBe(0);
  });

  it("persists item decisions as a review read model", async () => {
    if (!available) return;
    const itemId = await seedItem("Relevant paper", "2026-07-01T00:00:00.000Z");
    const rule = await repo().createRule({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: PROJECT,
      name: "Screening",
      triggerType: "manual",
      triggerConfig: normalizeTriggerConfig(null, "manual"),
      inputConfig: normalizeInputConfig({
        relevance_profile: { enabled: true, objective: "Find relevant papers" },
      }),
      actions: normalizeActions({ batch_digest: true, mark_items: true }),
      createdByUserId: OWNER,
    });
    const run = await repo().createRun({
      spaceId: SPACE,
      ruleId: rule.id,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: PROJECT,
      triggeredByUserId: OWNER,
      triggerType: "manual",
      inputItemIds: [itemId],
      inputEvidenceIds: [],
      cursorBefore: null,
      cursorAfter: { id: itemId, created_at: "2026-07-01T00:00:00.000Z" },
    });
    await repo().persistItemDecisions({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      ruleId: rule.id,
      runId: run.id,
      projectId: PROJECT,
      appliedByMarkItems: true,
      decisions: [{
        intake_item_id: itemId,
        relevance: "relevant",
        confidence: 0.91,
        reason: "Matches project context.",
        matched_context_refs: [{ ref: "project:project_public_summary:project-1" }],
      }],
    });

    const listed = await repo().listDecisions({
      spaceId: SPACE,
      connectionId: CONNECTION,
      reviewStatus: "accepted",
      limit: 10,
      offset: 0,
    });
    expect(listed.items).toHaveLength(1);
    expect(listed.items[0]).toMatchObject({
      source_connection_id: CONNECTION,
      project_id: PROJECT,
      intake_item_id: itemId,
      relevance: "relevant",
      applied_item_status: "selected",
      review_status: "accepted",
      item: { title: "Relevant paper" },
    });

    const updated = await repo().updateDecisionReview({
      spaceId: SPACE,
      decisionId: listed.items[0]!.id,
      reviewStatus: "queued",
      action: { queue_content: { job_ids: ["job-1"] } },
    });
    expect(updated.review_status).toBe("queued");
    expect(updated.action_json).toMatchObject({ queue_content: { job_ids: ["job-1"] } });
  });

  it("indexes scheduled active rules through scheduler tasks", async () => {
    if (!available) return;
    const rule = await repo().createRule({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      agentId: AGENT,
      projectId: null,
      name: "Scheduled digest",
      triggerType: "schedule",
      triggerConfig: normalizeTriggerConfig({ cron: "0 9 * * *", timezone: "UTC" }, "schedule"),
      inputConfig: normalizeInputConfig(null),
      actions: normalizeActions(null),
      createdByUserId: OWNER,
    });
    await pool!.query(
      `UPDATE scheduler_tasks
          SET next_run_at = '2026-07-01T09:00:00.000Z'
        WHERE task_type = $1 AND task_key = $2`,
      [SOURCE_POST_PROCESSING_TASK_TYPE, rule.id],
    );

    const due = await repo().listDueRules("2026-07-01T09:00:01.000Z", 10);
    expect(due.map((row) => row.id)).toEqual([rule.id]);

    await repo().updateRule(SPACE, rule.id, { status: "paused" });
    const pausedDue = await repo().listDueRules("2026-07-01T09:00:02.000Z", 10);
    expect(pausedDue).toHaveLength(0);
  });
});
