import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import type { ServerConfig } from "../src/config";

// Real-PostgreSQL tests for automation × project binding: automations.project_id
// persistence (create/update/clear), the composite (space_id, project_id) FK,
// the project-writer authorization on bind, the 422 for non-agent_run targets,
// and the fire path carrying project_id onto the created run row. Skips when
// Docker is unavailable.

const dbPoolMock: { current: Pool | undefined } = { current: undefined };

vi.mock("../src/db/pool", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/db/pool")>();
  return {
    ...actual,
    getDbPool: vi.fn((databaseUrl: string) => dbPoolMock.current ?? actual.getDbPool(databaseUrl)),
  };
});

vi.mock("../src/modules/policy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/modules/policy")>();
  return {
    ...actual,
    enforce: vi.fn(async () => ({ status: "allow" as const })),
  };
});

vi.mock("../src/modules/policy/gateway", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/modules/policy/gateway")>();
  return {
    ...actual,
    computeDecision: vi.fn(() => ({
      decision: { decision: "allow", message: null, reason_code: null, policy_rule_id: null, audit_code: null },
    })),
  };
});

import { AutomationService } from "../src/modules/automations/service";
import { PgAutomationRepository } from "../src/modules/automations/repository";
import { PgRunRepository } from "../src/modules/runs/repository";
import { PostRunFinalizationService } from "../src/modules/runs/finalizationService";

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OTHER_SPACE = "22222222-2222-4222-8222-222222222222";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"; // space owner + project owner
const MEMBER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"; // plain space member, not a project member
const PROJECT = "55555555-5555-4555-8555-555555555555";
const PROJECT_B = "56565656-5656-4556-8556-565656565656"; // second project in SPACE
const OTHER_PROJECT = "66666666-6666-4666-8666-666666666666"; // lives in OTHER_SPACE
const AGENT = "77777777-7777-4777-8777-777777777777";
const AGENT_VERSION = "88888888-8888-4888-8888-888888888888";
const WORKSPACE = "99999999-9999-4999-8999-999999999999";
const CONNECTOR = "33333333-3333-4333-8333-333333333333";
const CONNECTION = "44444444-4444-4444-8444-444444444444";

const config = {
  databaseUrl: "postgresql://test@test:5432/test",
} as unknown as ServerConfig;

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    dbPoolMock.current = pool;
    available = true;
  } catch (err) {
    console.warn(
      `[automations-project-db] skipped — Docker/Postgres unavailable: ${
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
    `TRUNCATE automation_runs, automation_credential_grants, automations, scheduler_tasks,
       jobs, context_snapshots, runs, agent_runtime_profiles, agent_versions, agents,
       intake_items, workspace_source_bindings, source_connections, source_connectors,
       workspaces, project_members, projects, space_memberships, users, spaces CASCADE`,
  );
  const now = new Date().toISOString();
  for (const [spaceId, name] of [[SPACE, "Main"], [OTHER_SPACE, "Other"]] as const) {
    await pool.query(
      `INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,$2,'personal',$3,$3)`,
      [spaceId, name, now],
    );
  }
  for (const userId of [OWNER, MEMBER]) {
    await pool.query(
      `INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,$1,'active',$2,$2)`,
      [userId, now],
    );
  }
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,'owner','active',$4,$4), ($5,$2,$6,'member','active',$4,$4)`,
    [randomUUID(), SPACE, OWNER, now, randomUUID(), MEMBER],
  );
  await pool.query(
    `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at)
     VALUES ($1,$2,$3,'Research','active',$4,$4), ($5,$2,$3,'Research B','active',$4,$4),
            ($6,$7,NULL,'Elsewhere','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now, PROJECT_B, OTHER_PROJECT, OTHER_SPACE],
  );
  await pool.query(
    `INSERT INTO agents (id, space_id, owner_user_id, name, status, current_version_id, created_at, updated_at, visibility)
     VALUES ($1,$2,$3,'Agent','active',NULL,$4,$4,'space_shared')`,
    [AGENT, SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO agent_versions (
       id, agent_id, space_id, version_label, system_prompt, model_config_json,
       runtime_config_json, context_policy_json, memory_policy_json,
       capabilities_json, tool_permissions_json, runtime_policy_json, created_at
     ) VALUES ($1,$2,$3,'v1','Test agent','{}'::jsonb,'{"adapter_type":"model_api"}'::jsonb,
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
    `INSERT INTO model_providers (
       id, space_id, owner_user_id, name, provider_type, enabled,
       capabilities_json, config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,'Provider','anthropic',true,'{}'::jsonb,'{"is_default":true}'::jsonb,$4,$4)`,
    [randomUUID(), SPACE, OWNER, now],
  );
});

function service(): AutomationService {
  return new AutomationService(config, new PgAutomationRepository(pool!));
}

async function seedIntakeSourceWithBinding(): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO workspaces (
       id, space_id, name, status, workspace_type, kind, visibility, protected, system_managed,
       created_at, updated_at
     ) VALUES ($1,$2,'ws','active','project','standard','space_shared',false,false,$3,$3)`,
    [WORKSPACE, SPACE, now],
  );
  await pool!.query(
    `INSERT INTO project_workspaces (id, space_id, project_id, workspace_id, role, created_at, updated_at)
     VALUES ($1,$2,$3,$5,'reference',$6,$6), ($4,$2,$7,$5,'reference',$6,$6)
     ON CONFLICT (space_id, project_id, workspace_id, role) DO NOTHING`,
    [randomUUID(), SPACE, PROJECT, randomUUID(), WORKSPACE, now, PROJECT_B],
  );
  await pool!.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES ($1,'rss','RSS','external_feed','pull','active','{}'::jsonb,$2,$2)`,
    [CONNECTOR, now],
  );
  await pool!.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status,
       fetch_frequency, capture_policy, trust_level, consent_json, policy_json,
       config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'arXiv','https://example.org/rss','active',
       'daily','reference_only','normal','{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$5,$5)`,
    [CONNECTION, SPACE, CONNECTOR, OWNER, now],
  );
  await pool!.query(
    `INSERT INTO workspace_source_bindings (
       id, space_id, workspace_id, project_id, source_connection_id, binding_key,
       status, priority, filters_json, routing_policy_json, extraction_policy_json,
       created_at, updated_at
     ) VALUES ($1,$2,$3,$4,$5,'default','active',0,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$6,$6)`,
    [randomUUID(), SPACE, WORKSPACE, PROJECT, CONNECTION, now],
  );
}

async function seedIntakeItem(title: string, createdAt: string): Promise<string> {
  const id = randomUUID();
  await pool!.query(
    `INSERT INTO intake_items (
       id, space_id, connection_id, item_type, title, source_uri, excerpt,
       first_seen_at, last_seen_at, status, read_status, content_state,
       retention_policy, created_at, updated_at
     ) VALUES ($1,$2,$3,'external_url',$4,$6,'Paper abstract',
       $5,$5,'new','unread','excerpt_saved','summary_only',$5,$5)`,
    [id, SPACE, CONNECTION, title, createdAt, `https://example.org/paper/${id}`],
  );
  return id;
}

async function createBoundAutomation(configJson: Record<string, unknown> = {}): Promise<string> {
  const created = await service().create({
    spaceId: SPACE,
    ownerUserId: OWNER,
    body: {
      name: "Paper digest",
      agent_id: AGENT,
      project_id: PROJECT,
      trigger_type: "manual",
      config_json: { target_type: "agent_run", ...configJson },
    },
  });
  return created.id;
}

describe("Automation × Project binding (real Postgres)", () => {
  it("creates a project-bound automation, exposes project_id, and clears it on update", async () => {
    if (!available) return;
    const created = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Paper digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "manual",
        config_json: { target_type: "agent_run" },
      },
    });
    expect(created.project_id).toBe(PROJECT);

    const fetched = await new PgAutomationRepository(pool!).get(SPACE, created.id);
    expect(fetched?.project_id).toBe(PROJECT);

    const cleared = await service().update({
      spaceId: SPACE,
      automationId: created.id,
      actorUserId: OWNER,
      body: { project_id: null },
    });
    expect(cleared.project_id).toBeNull();

    const rebound = await service().update({
      spaceId: SPACE,
      automationId: created.id,
      actorUserId: OWNER,
      body: { project_id: PROJECT },
    });
    expect(rebound.project_id).toBe(PROJECT);
  });

  it("rejects project binding for non-agent_run targets with 422", async () => {
    if (!available) return;
    await expect(
      service().create({
        spaceId: SPACE,
        ownerUserId: OWNER,
        body: {
          name: "Maintenance",
          agent_id: AGENT,
          project_id: PROJECT,
          trigger_type: "manual",
          config_json: { target_type: "knowledge_retrieval_maintenance" },
        },
      }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("requires project writer authority to bind: plain space member gets 403", async () => {
    if (!available) return;
    await expect(
      service().create({
        spaceId: SPACE,
        ownerUserId: MEMBER,
        body: {
          name: "Paper digest",
          agent_id: AGENT,
          project_id: PROJECT,
          trigger_type: "manual",
        },
      }),
    ).rejects.toMatchObject({ statusCode: 403 });

    // Becoming an active project member grants bind authority.
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO project_members (id, space_id, project_id, user_id, role, status, created_at, updated_at)
       VALUES ($1,$2,$3,$4,'member','active',$5,$5)`,
      [randomUUID(), SPACE, PROJECT, MEMBER, now],
    );
    const created = await service().create({
      spaceId: SPACE,
      ownerUserId: MEMBER,
      body: {
        name: "Paper digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "manual",
      },
    });
    expect(created.project_id).toBe(PROJECT);
  });

  it("rejects binding a project from another space (404 from writer check)", async () => {
    if (!available) return;
    await expect(
      service().create({
        spaceId: SPACE,
        ownerUserId: OWNER,
        body: {
          name: "Cross-space",
          agent_id: AGENT,
          project_id: OTHER_PROJECT,
          trigger_type: "manual",
        },
      }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("database composite FK rejects a cross-space project even on direct insert", async () => {
    if (!available) return;
    const now = new Date().toISOString();
    await expect(
      pool!.query(
        `INSERT INTO automations (
           id, space_id, owner_user_id, agent_id, project_id, name,
           trigger_type, status, created_at, updated_at
         ) VALUES ($1,$2,$3,$4,$5,'x','manual','active',$6,$6)`,
        [randomUUID(), SPACE, OWNER, AGENT, OTHER_PROJECT, now],
      ),
    ).rejects.toMatchObject({ code: "23503" });
  });

  it("fire creates the run with the automation's project_id", async () => {
    if (!available) return;
    const created = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Paper digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "manual",
        config_json: { target_type: "agent_run" },
      },
    });
    const result = await service().fire({
      spaceId: SPACE,
      automationId: created.id,
      actorUserId: OWNER,
      prompt: "Analyze new papers",
    });
    const run = await pool!.query<{ project_id: string | null; trigger_origin: string }>(
      `SELECT project_id, trigger_origin FROM runs WHERE id = $1`,
      [String(result.run_id)],
    );
    expect(run.rows[0]?.project_id).toBe(PROJECT);
    expect(run.rows[0]?.trigger_origin).toBe("automation");
  });

  it("injects the intake delta, advances the cursor only on run success, and re-reads on failure", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    const automationId = await createBoundAutomation();
    await seedIntakeItem("Paper A", "2026-07-01T00:00:00.000Z");
    await seedIntakeItem("Paper B", "2026-07-02T00:00:00.000Z");
    const runs = new PgRunRepository(pool!);
    const finalizer = new PostRunFinalizationService(runs);

    // First fire sees both items and injects them into the run instruction.
    const first = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(first.intake_delta_count).toBe(2);
    const firstRun = await pool!.query<{ instruction: string | null }>(
      `SELECT instruction FROM runs WHERE id = $1`,
      [String(first.run_id)],
    );
    expect(firstRun.rows[0]?.instruction).toContain("Paper A");
    expect(firstRun.rows[0]?.instruction).toContain("Paper B");
    const automationRun = await pool!.query<{ trigger_context_json: Record<string, unknown> }>(
      `SELECT trigger_context_json FROM automation_runs WHERE run_id = $1`,
      [String(first.run_id)],
    );
    expect(automationRun.rows[0]?.trigger_context_json).toMatchObject({ intake_delta_count: 2 });

    // A failed run must not advance the cursor: the next fire re-reads the same delta.
    await runs.markRunTerminal({
      run_id: String(first.run_id),
      space_id: SPACE,
      status: "failed",
      output_text: "boom",
      exit_code: 1,
      completed_at: new Date().toISOString(),
    });
    await finalizer.finalize(String(first.run_id), SPACE);
    const afterFailure = await new PgAutomationRepository(pool!).get(SPACE, automationId);
    expect(afterFailure?.cursor_json).toBeNull();

    const second = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(second.intake_delta_count).toBe(2);

    // Success commits the watermark; the next fire sees only newer items.
    await runs.markRunTerminal({
      run_id: String(second.run_id),
      space_id: SPACE,
      status: "succeeded",
      output_text: "ok",
      exit_code: 0,
      completed_at: new Date().toISOString(),
    });
    await finalizer.finalize(String(second.run_id), SPACE);
    const afterSuccess = await new PgAutomationRepository(pool!).get(SPACE, automationId);
    expect(afterSuccess?.cursor_json).toMatchObject({
      intake_watermark: { created_at: "2026-07-02T00:00:00.000Z" },
    });

    await seedIntakeItem("Paper C", "2026-07-03T00:00:00.000Z");
    const third = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(third.intake_delta_count).toBe(1);
    const thirdRun = await pool!.query<{ instruction: string | null }>(
      `SELECT instruction FROM runs WHERE id = $1`,
      [String(third.run_id)],
    );
    expect(thirdRun.rows[0]?.instruction).toContain("Paper C");
    expect(thirdRun.rows[0]?.instruction).not.toContain("Paper A");
  });

  it("does not replay historical backlog: items existing at bind time start below the cursor", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    await seedIntakeItem("Old paper", "2026-06-01T00:00:00.000Z");
    const automationId = await createBoundAutomation();

    const auto = await new PgAutomationRepository(pool!).get(SPACE, automationId);
    expect(auto?.cursor_json).toMatchObject({
      intake_watermark: { created_at: "2026-06-01T00:00:00.000Z" },
    });

    const result = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(result.intake_delta_count).toBe(0);
    const run = await pool!.query<{ instruction: string | null }>(
      `SELECT instruction FROM runs WHERE id = $1`,
      [String(result.run_id)],
    );
    expect(run.rows[0]?.instruction ?? "").not.toContain("Old paper");

    await seedIntakeItem("New paper", "2026-07-01T00:00:00.000Z");
    const next = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(next.intake_delta_count).toBe(1);
  });

  it("re-initializes the cursor when the bound project changes", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    const automationId = await createBoundAutomation();
    await seedIntakeItem("Paper A", "2026-07-01T00:00:00.000Z");

    // Bind the same connection to PROJECT_B as well, then rebind the automation.
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO workspace_source_bindings (
         id, space_id, workspace_id, project_id, source_connection_id, binding_key,
         status, priority, filters_json, routing_policy_json, extraction_policy_json,
         created_at, updated_at
       ) VALUES ($1,$2,$3,$4,$5,'project-b','active',0,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$6,$6)`,
      [randomUUID(), SPACE, WORKSPACE, PROJECT_B, CONNECTION, now],
    );
    const rebound = await service().update({
      spaceId: SPACE,
      automationId,
      actorUserId: OWNER,
      body: { project_id: PROJECT_B },
    });
    // The new scope's current watermark covers Paper A: it is not replayed
    // into project B, but items materialized afterwards are delivered.
    expect(rebound.cursor_json).toMatchObject({
      intake_watermark: { created_at: "2026-07-01T00:00:00.000Z" },
    });
    const first = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(first.intake_delta_count).toBe(0);
    await seedIntakeItem("Paper B", "2026-07-02T00:00:00.000Z");
    const second = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(second.intake_delta_count).toBe(1);
  });

  it("event fires are skipped while a previous automation run is still in flight", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    const automation = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Event digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "event",
        config_json: {
          target_type: "agent_run",
          event: { type: "intake.items_materialized", cooldown_seconds: 0 },
        },
      },
    });
    await seedIntakeItem("Paper A", "2026-07-01T00:00:00.000Z");
    const first = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 1,
    });
    expect(first.fired).toBe(1);

    // The queued run has not settled, so its watermark is uncommitted; a new
    // fire would re-deliver the same delta and is skipped instead.
    await seedIntakeItem("Paper B", "2026-07-02T00:00:00.000Z");
    const second = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 1,
    });
    expect(second.fired).toBe(0);
    expect(second.skipped).toEqual([{ automation_id: automation.id, reason: "run_in_flight" }]);
  });

  it("skips the fire without creating a run when configured and no new items exist", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    const automationId = await createBoundAutomation({ skip_when_no_new_items: true });

    const result = await service().fire({ spaceId: SPACE, automationId, actorUserId: OWNER });
    expect(result).toMatchObject({ skipped: true, skip_reason: "no_new_intake_items" });
    const runCount = await pool!.query<{ n: string }>(`SELECT count(*) AS n FROM runs`);
    expect(Number(runCount.rows[0]?.n)).toBe(0);
  });

  it("event automations: shape validation, project-binding match, cooldown, and empty-delta skip", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();

    // Shape validation: event trigger requires an event object and a scope.
    await expect(
      service().create({
        spaceId: SPACE,
        ownerUserId: OWNER,
        body: {
          name: "Bad event",
          agent_id: AGENT,
          project_id: PROJECT,
          trigger_type: "event",
          config_json: { target_type: "agent_run" },
        },
      }),
    ).rejects.toMatchObject({ statusCode: 422 });
    await expect(
      service().create({
        spaceId: SPACE,
        ownerUserId: OWNER,
        body: {
          name: "Unscoped event",
          agent_id: AGENT,
          trigger_type: "event",
          config_json: {
            target_type: "agent_run",
            event: { type: "intake.items_materialized" },
          },
        },
      }),
    ).rejects.toMatchObject({ statusCode: 422 });

    const automation = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Event digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "event",
        config_json: {
          target_type: "agent_run",
          event: { type: "intake.items_materialized", cooldown_seconds: 900 },
        },
      },
    });
    // Event automations are pre-authorized like scheduled ones.
    const grants = await pool!.query(
      `SELECT id FROM automation_credential_grants WHERE automation_id = $1 AND status = 'active'`,
      [automation.id],
    );
    expect(grants.rows).toHaveLength(1);

    // New items materialized → the event fires the automation once.
    await seedIntakeItem("Paper A", "2026-07-01T00:00:00.000Z");
    const first = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 1,
    });
    expect(first).toMatchObject({ matched: 1, fired: 1 });
    const automationRuns = await pool!.query<{ trigger_type: string }>(
      `SELECT trigger_type FROM automation_runs WHERE automation_id = $1`,
      [automation.id],
    );
    expect(automationRuns.rows).toEqual([{ trigger_type: "event" }]);

    // Immediate duplicate delivery is suppressed by the cooldown.
    const second = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 1,
    });
    expect(second.fired).toBe(0);
    expect(second.skipped).toEqual([{ automation_id: automation.id, reason: "cooldown" }]);

    // Below min_new_items is filtered before any fire attempt.
    const below = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 0,
    });
    expect(below.skipped).toEqual([{ automation_id: automation.id, reason: "below_min_new_items" }]);

    // An unrelated connection matches nothing.
    const unrelated = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: randomUUID(),
      newItemCount: 5,
    });
    expect(unrelated.matched).toBe(0);
  });

  it("event fire with no new intake items skips run creation by default", async () => {
    if (!available) return;
    await seedIntakeSourceWithBinding();
    const automation = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Event digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "event",
        config_json: {
          target_type: "agent_run",
          event: { type: "intake.items_materialized", cooldown_seconds: 0 },
        },
      },
    });
    // No intake items exist, so the event fire has an empty delta and skips.
    const result = await service().fireIntakeEventAutomations({
      spaceId: SPACE,
      sourceConnectionId: CONNECTION,
      newItemCount: 3,
    });
    expect(result.fired).toBe(0);
    expect(result.skipped).toEqual([
      { automation_id: automation.id, reason: "no_new_intake_items" },
    ]);
    const runCount = await pool!.query<{ n: string }>(`SELECT count(*) AS n FROM runs`);
    expect(Number(runCount.rows[0]?.n)).toBe(0);
  });

  it("fire preflight fails when the bound project was soft-deleted after binding", async () => {
    if (!available) return;
    const created = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Paper digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "manual",
      },
    });
    await pool!.query(`UPDATE projects SET deleted_at = NOW(), status = 'deleted' WHERE id = $1`, [PROJECT]);
    await expect(
      service().fire({
        spaceId: SPACE,
        automationId: created.id,
        actorUserId: OWNER,
      }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });
});
