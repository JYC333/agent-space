import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
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

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OTHER_SPACE = "22222222-2222-4222-8222-222222222222";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"; // space owner + project owner
const MEMBER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"; // plain space member, not a project member
const PROJECT = "55555555-5555-4555-8555-555555555555";
const OTHER_PROJECT = "66666666-6666-4666-8666-666666666666"; // lives in OTHER_SPACE
const AGENT = "77777777-7777-4777-8777-777777777777";
const AGENT_VERSION = "88888888-8888-4888-8888-888888888888";

const config = {
  databaseUrl: "postgresql://test@test:5432/test",
} as unknown as ServerConfig;

let container: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await getTestPostgres(__filename);
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
       source_items, project_source_item_links, project_source_bindings, source_connections, source_connectors,
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
     VALUES ($1,$2,$3,'Research','active',$4,$4), ($5,$6,NULL,'Elsewhere','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now, OTHER_PROJECT, OTHER_SPACE],
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

  it("lists automations filtered by project_id", async () => {
    if (!available) return;
    const bound = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "Project digest",
        agent_id: AGENT,
        project_id: PROJECT,
        trigger_type: "manual",
        config_json: { target_type: "agent_run" },
      },
    });
    const unbound = await service().create({
      spaceId: SPACE,
      ownerUserId: OWNER,
      body: {
        name: "General digest",
        agent_id: AGENT,
        trigger_type: "manual",
        config_json: { target_type: "agent_run" },
      },
    });

    const repo = new PgAutomationRepository(pool!);
    await expect(repo.list(SPACE, { projectId: PROJECT })).resolves.toMatchObject([
      { id: bound.id, project_id: PROJECT },
    ]);
    await expect(repo.list(SPACE, { projectId: null })).resolves.toMatchObject([
      { id: unbound.id, project_id: null },
    ]);
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

  it("rejects source event automations", async () => {
    if (!available) return;
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
    ).rejects.toMatchObject({ statusCode: 404 });
  });
});
