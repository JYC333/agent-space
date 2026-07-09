import { join } from "node:path";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import { PgProjectRepository } from "../src/modules/projects/repository";
import { ProjectPresetsRepository } from "../src/modules/projectPresets/repository";
import { ProjectPresetsService } from "../src/modules/projectPresets/service";
import { __setProjectPresetRegistryForTests } from "../src/modules/projectPresets/registry";

// Real-Postgres coverage for Project preset infrastructure: descriptors are
// code-owned, and a Project's selected preset is stored at creation time in
// projects.settings_json.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

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
    console.warn(`[project-presets-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query("TRUNCATE projects, users, spaces CASCADE");
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at)
     VALUES ($1, 'User', 'active', now(), now())`,
    [USER],
  );
  await pool.query(
    `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
     VALUES ($1, 'Preset Space', 'household', $2, now(), now())`,
    [SPACE, USER],
  );
  __setProjectPresetRegistryForTests([
    {
      key: "test_preset",
      name: "Test Preset",
      description: "A test-only preset descriptor.",
      sections: ["overview"],
      source_preset_ids: [],
      extraction_profile_key: null,
      graph_lens_id: null,
    },
  ]);
});

afterEach(() => {
  __setProjectPresetRegistryForTests(null);
});

function service(): ProjectPresetsService {
  return new ProjectPresetsService(new ProjectPresetsRepository(pool as Pool));
}

const identity = { spaceId: SPACE, userId: USER };

describe("project presets module (real Postgres)", () => {
  it("lists code-owned Project preset descriptors", () => {
    if (!available) return;
    expect(service().listAvailablePresets()).toEqual([
      {
        key: "test_preset",
        name: "Test Preset",
        description: "A test-only preset descriptor.",
        sections: ["overview"],
        source_preset_ids: [],
        extraction_profile_key: null,
        graph_lens_id: null,
      },
    ]);
  });

  it("reads the preset selected at project creation time", async () => {
    if (!available) return;
    const projectRepo = new PgProjectRepository(pool as Pool);
    const project = await projectRepo.create(identity, {
      name: "Research Project",
      settings_json: { custom: "value", preset: "test_preset" },
    });
    expect(await service().getProjectPreset(identity, project.id as string)).toBe("test_preset");
  });

  it("returns null when a project has no selected preset", async () => {
    if (!available) return;
    const projectRepo = new PgProjectRepository(pool as Pool);
    const project = await projectRepo.create(identity, { name: "Research Project" });
    expect(await service().getProjectPreset(identity, project.id as string)).toBeNull();
  });
});
