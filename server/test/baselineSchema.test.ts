import { join } from "node:path";
import { readFileSync, readdirSync } from "node:fs";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { loadMigrations, migrate } from "../src/db/migrator";

// Empty-DB migration test. Applies the committed consolidated baseline
// (`server/migrations/0001_baseline.sql`) to a fresh Postgres via the server
// migration runner and asserts it applies cleanly and idempotently.
//
// Verifies the runner creates representative server-owned tables from the
// baseline. Skips gracefully without Docker.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const RUNNER_TABLE = "server_schema_migrations";

// A representative spread across domains; a missing one means an incomplete apply.
const REPRESENTATIVE_TABLES = [
  "spaces",
  "space_objects",
  "users",
  "memory_entries",
  "runs",
  "proposals",
  "settings",
  "scheduler_tasks",
  "knowledge_items",
  "claims",
  "claim_sources",
  "object_relations",
  "space_object_kinds",
  "space_object_kind_relation_hints",
  "retrieval_objects",
  "retrieval_aliases",
  "retrieval_chunks",
  "retrieval_edges",
  "retrieval_feedback_events",
  "model_providers",
  "source_recipe_versions",
  "policy_decision_records",
  "agent_run_groups",
  "agent_run_group_members",
  "agent_run_messages",
  "run_delegations",
  "evolution_strategy_assets",
  "evolution_experiences",
  "evolution_selector_decisions",
];

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    available = true;
  } catch (err) {
    console.warn(
      `[baseline-schema] skipped — Docker/Postgres unavailable: ${
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
  await pool.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; RESET search_path;");
});

async function baselineTableNames(p: Pool): Promise<string[]> {
  const res = await p.query<{ table_name: string }>(
    `SELECT table_name FROM information_schema.tables
       WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
         AND table_name <> $1
       ORDER BY table_name`,
    [RUNNER_TABLE],
  );
  return res.rows.map((r) => r.table_name);
}

function tableDefinition(sql: string, table: string): string {
  const match = new RegExp(`CREATE TABLE public\\.${table} \\(([\\s\\S]*?)\\n\\);`).exec(sql);
  return match?.[1] ?? "";
}

describe("server runner applies the baseline schema", () => {
  it("keeps 0001_baseline.sql as the consolidated baseline for a fresh database", () => {
    const migrationFiles = readdirSync(MIGRATIONS_DIR)
      .filter((name) => /^\d+_.+\.sql$/.test(name))
      .sort();
    expect(migrationFiles).toEqual(["0001_baseline.sql"]);
  });

  it("keeps space object statuses constrained by concrete object type", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("ck_space_objects_status_by_type");
    expect(baseline).toContain("WHEN 'note'::text THEN");
    expect(baseline).toContain("WHEN 'source'::text THEN");
    expect(baseline).toContain("WHEN 'knowledge_item'::text THEN");
    expect(baseline).toContain("WHEN 'claim'::text THEN");
  });

  it("keeps ClaimFact and object relation tables FK-backed and retrievable", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.claims");
    expect(baseline).toContain("CREATE TABLE public.claim_sources");
    expect(baseline).toContain("CREATE TABLE public.object_relations");
    expect(baseline).toContain("ck_claim_sources_source_ref_connection");
    expect(baseline).toContain("FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (claim_id, space_id) REFERENCES public.claims(object_id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (from_object_id, space_id) REFERENCES public.space_objects(id, space_id)");
    expect(baseline).toContain("'claim'::character varying, 'memory_entry'::character varying");
  });

  it("keeps object_relations as the canonical relation graph", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    const objectRelations = tableDefinition(baseline, "object_relations");
    expect(objectRelations).toContain("from_object_id character varying(36) NOT NULL");
    expect(objectRelations).toContain("to_object_id character varying(36) NOT NULL");
    expect(objectRelations).toContain("source_proposal_id character varying(36)");
    expect(baseline).toContain("object_relations_source_proposal_id_fkey");
    expect(baseline).toContain("FOREIGN KEY (from_object_id, space_id) REFERENCES public.space_objects(id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (to_object_id, space_id) REFERENCES public.space_objects(id, space_id)");
  });

  it("keeps KnowledgeItem and MemoryEntry on canonical source and proposal fields", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    const knowledgeItemSources = tableDefinition(baseline, "knowledge_item_sources");
    const knowledgeItems = tableDefinition(baseline, "knowledge_items");
    expect(knowledgeItemSources).toContain("knowledge_item_id character varying(36) NOT NULL");
    expect(knowledgeItemSources).toContain("source_id character varying(36) NOT NULL");
    expect(knowledgeItemSources).toContain("relation_type character varying(32) NOT NULL");
    expect(knowledgeItems).toContain("created_from_proposal_id character varying(36)");
    expect(baseline).toContain("knowledge_item_sources_source_id_fkey");
    expect(baseline).toContain("knowledge_item_sources_knowledge_item_id_fkey");
    expect(baseline).toContain("knowledge_items_created_from_proposal_id_fkey");

    const memoryEntries = tableDefinition(baseline, "memory_entries");
    expect(memoryEntries).toContain("memory_type character varying(32) NOT NULL");
    expect(memoryEntries).toContain("memory_layer character varying(32)");
    expect(memoryEntries).toContain("created_from_proposal_id character varying(36)");
    expect(baseline).toContain("ck_memory_entries_memory_layer");
    expect(baseline).toContain("ix_memory_entries_memory_type");
    expect(baseline).toContain("memory_entries_created_from_proposal_id_fkey");
  });

  it("keeps retrieval base object types centralized in a database domain", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE DOMAIN public.retrieval_object_type AS character varying(64)");
    expect(baseline).toContain("CONSTRAINT retrieval_object_type_allowed CHECK");
    expect(baseline).toContain("CREATE TABLE public.space_object_kinds");
    expect(baseline).toContain("CREATE TABLE public.space_object_kind_relation_hints");
    expect(baseline).toContain("base_object_type public.retrieval_object_type NOT NULL");
    expect(baseline).toContain("endpoint_object_type public.retrieval_object_type NOT NULL");
    expect(baseline).toContain("object_type public.retrieval_object_type NOT NULL");
    expect(baseline).toContain("from_object_type public.retrieval_object_type NOT NULL");
    expect(baseline).toContain("to_object_type public.retrieval_object_type NOT NULL");
    expect(baseline).not.toContain("ck_space_object_kinds_base_object_type");
    expect(baseline).not.toContain("ck_space_object_kind_relation_hints_endpoint_type");
    expect(baseline).not.toContain("ck_note_links_endpoint_type");
    expect(baseline).not.toContain("ck_retrieval_objects_object_type");
    expect(baseline).not.toContain("ck_retrieval_aliases_object_type");
    expect(baseline).not.toContain("ck_retrieval_chunks_object_type");
    expect(baseline).not.toContain("ck_retrieval_edges_from_object_type");
    expect(baseline).not.toContain("ck_retrieval_edges_to_object_type");
    expect(baseline).not.toContain("ck_retrieval_feedback_events_object_type");
    expect(baseline).toContain("ck_space_object_kind_relation_hints_relation_type");
    expect(baseline).toContain("'project_public_summary'::character varying");
    expect(baseline).toContain("'knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying, 'intake_item'::character varying, 'extracted_evidence'::character varying");
  });

  it("keeps note collection trees and memberships space-scoped in the baseline", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.note_collection_items");
    expect(baseline).toContain("space_id character varying(36) NOT NULL,\n    collection_id character varying(36) NOT NULL");
    expect(baseline).toContain("FOREIGN KEY (collection_id, space_id) REFERENCES public.note_collections(id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (note_id, space_id) REFERENCES public.notes(object_id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (parent_id, space_id) REFERENCES public.note_collections(id, space_id)");
  });

  it("keeps evolution core schema and built-in strategies in the baseline", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.evolution_strategy_assets");
    expect(baseline).toContain("CREATE TABLE public.evolution_experiences");
    expect(baseline).toContain("CREATE TABLE public.evolution_selector_decisions");
    expect(baseline).toContain("ck_evolution_strategy_assets_target_type");
    expect(baseline).toContain("ck_evolution_strategy_assets_risk_level");
    expect(baseline).toContain("ck_evolution_experiences_outcome_status");
    expect(baseline).toContain("uq_evolution_strategy_assets_system_key");
    expect(baseline).toContain("uq_evolution_strategy_assets_space_key");
    expect(baseline).toContain("ix_evolution_selector_decisions_space_target_created");
    expect(baseline).toContain("evolution_selector_decisions_selected_strategy_asset_id_fkey");

    // Built-in strategy keys are seed data, not schema — they're upserted at
    // runtime by runBuiltInSeeds (server/src/db/seeds.ts), not embedded in
    // the migration. Check the seed source instead of the baseline SQL.
    const seedsSource = readFileSync(join(process.cwd(), "src/db/seeds.ts"), "utf8");
    for (const key of [
      "repair.runtime_failure",
      "repair.validation_failure",
      "optimize.prompt_asset",
      "optimize.tool_usage",
      "harden.policy_boundary",
      "improve.capability_gap",
      "review.open_skill_import",
      "maintain.memory_health",
      "maintain.knowledge_retrieval",
      "solidifyExperience.successful_run",
    ]) {
      expect(seedsSource).toContain(key);
    }
  });

  it("keeps Source Recipe schema in the consolidated baseline", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    const sourceConnections = tableDefinition(baseline, "source_connections");
    const sourceHandlerVersions = tableDefinition(baseline, "source_handler_versions");
    expect(baseline).toContain("CREATE TABLE public.source_recipe_versions");
    expect(sourceConnections).toContain("active_recipe_version_id character varying(36)");
    expect(sourceConnections).toContain("'recipe'::character varying");
    expect(sourceHandlerVersions).toContain("'declarative_pipeline_v1'::character varying");
    expect(baseline).toContain("source_connections_active_recipe_version_id_fkey");
    expect(baseline).toContain("'source_recipe'::character varying");
  });

  it("keeps Agent Room delegation schema in the consolidated baseline", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    const runs = tableDefinition(baseline, "runs");
    const groups = tableDefinition(baseline, "agent_run_groups");
    const members = tableDefinition(baseline, "agent_run_group_members");
    const messages = tableDefinition(baseline, "agent_run_messages");
    const delegations = tableDefinition(baseline, "run_delegations");

    expect(baseline).toContain("CREATE TABLE public.agent_run_groups");
    expect(baseline).toContain("CREATE TABLE public.agent_run_group_members");
    expect(baseline).toContain("CREATE TABLE public.agent_run_messages");
    expect(baseline).toContain("CREATE TABLE public.run_delegations");
    expect(runs).toContain("root_run_id character varying(36)");
    expect(runs).toContain("run_group_id character varying(36)");
    expect(runs).toContain("delegation_id character varying(36)");
    expect(runs).toContain("instructed_by_agent_id character varying(36)");
    expect(runs).toContain("'delegation'::character varying");
    expect(groups).toContain("manager_user_id character varying(36) NOT NULL");
    expect(members).toContain("CONSTRAINT ck_agent_run_group_members_role");
    expect(messages).toContain("sender_actor_ref_json jsonb NOT NULL");
    expect(delegations).toContain("policy_decision_record_id character varying(36)");
    expect(delegations).toContain("CONSTRAINT ck_run_delegations_status");
    expect(baseline).toContain("uq_agent_run_group_members_group_agent");
    expect(baseline).toContain("uq_agents_space_id_id");
    expect(baseline).toContain("uq_runs_space_id_id");
    expect(baseline).toContain("uq_agent_run_groups_space_id_id");
    expect(baseline).toContain("uq_run_delegations_space_id_id");
    expect(baseline).toContain("ix_run_delegations_status_updated");
    expect(baseline).toContain("runs_delegation_id_fkey");
    expect(baseline).toContain("fk_runs_delegation_same_space");
    expect(baseline).toContain("fk_run_delegations_group_same_space");
    expect(baseline).toContain("fk_agent_run_group_members_agent_same_space");
    expect(baseline).toContain("run_delegations_policy_decision_record_id_fkey");
    expect(baseline).toContain("'delegation_policy_denied'::character varying");
  });

  it("applies the baseline and creates representative server-owned tables", async () => {
    if (!available || !pool) return;

    const expectedVersions = loadMigrations(MIGRATIONS_DIR).map((f) => f.version);
    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.all).toEqual(expectedVersions);
    expect(result.applied).toContain("0001");

    const recorded = await pool.query(
      `SELECT version FROM public.${RUNNER_TABLE} WHERE version = '0001'`,
    );
    expect(recorded.rowCount).toBe(1);

    const tables = await baselineTableNames(pool);
    for (const t of REPRESENTATIVE_TABLES) {
      expect(tables).toContain(t);
    }
  }, 15_000);

  it("enforces object kind registry constraints in Postgres", async () => {
    if (!available || !pool) return;

    await migrate(pool, MIGRATIONS_DIR);
    await pool.query(
      `INSERT INTO users (id, display_name, status, created_at, updated_at)
       VALUES ('user-1', 'User', 'active', now(), now())`,
    );
    await pool.query(
      `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
       VALUES
         ('space-1', 'Space 1', 'team', 'user-1', now(), now()),
         ('space-2', 'Space 2', 'team', 'user-1', now(), now())`,
    );
    await pool.query(
      `INSERT INTO proposals (
         id, space_id, proposal_type, status, risk_level, urgency, title,
         payload_json, created_by_user_id, created_at, updated_at
       ) VALUES
         ('proposal-1', 'space-1', 'object_kind_create', 'accepted', 'high', 'normal', 'Create kind', '{}'::jsonb, 'user-1', now(), now()),
         ('proposal-2', 'space-2', 'object_kind_create', 'accepted', 'high', 'normal', 'Create kind', '{}'::jsonb, 'user-1', now(), now())`,
    );

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-1', 'space-1', 'question', 'Question', 'knowledge_item', 'active',
         'user-1', 'proposal-1', 'proposal-1', now(), now()
       )`,
    );

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-dup', 'space-1', 'question', 'Duplicate', 'knowledge_item', 'active', now(), now()
       )`,
    )).rejects.toThrow();

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-other-space', 'space-2', 'question', 'Question', 'knowledge_item', 'active',
         'user-1', 'proposal-2', 'proposal-2', now(), now()
       )`,
    );
    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-other-base', 'space-1', 'question', 'Question claim', 'claim', 'active',
         'user-1', 'proposal-1', 'proposal-1', now(), now()
       )`,
    );

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-invalid-base', 'space-1', 'person', 'Person', 'person', 'active', now(), now()
       )`,
    )).rejects.toThrow();

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_from_proposal_id, created_at, updated_at
       ) VALUES (
         'kind-bad-fk', 'space-1', 'lesson', 'Bad FK', 'knowledge_item', 'active', 'missing-proposal', now(), now()
       )`,
    )).rejects.toThrow();

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-archived', 'space-1', 'email', 'Email', 'source', 'archived', now(), now()
       )`,
    );
    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-archived-reuse', 'space-1', 'email', 'Email replacement', 'source', 'active', now(), now()
       )`,
    )).rejects.toThrow();
  }, 15_000);

  it("is idempotent on an already-migrated database", async () => {
    if (!available || !pool) return;
    const first = await migrate(pool, MIGRATIONS_DIR);
    expect(first.applied).toContain("0001");

    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.applied).toEqual([]);
    const tables = await baselineTableNames(pool);
    for (const t of REPRESENTATIVE_TABLES) {
      expect(tables).toContain(t);
    }
  }, 15_000);
});
