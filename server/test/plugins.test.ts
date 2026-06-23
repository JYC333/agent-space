/**
 * Tests for the official optional modules (plugins) framework.
 *
 * Covers:
 *   - Registry: descriptor uniqueness, dairy exists and is disabled by default
 *   - Service: list, effective map, enable, disable, settings patch
 *   - Guards: disabled guard fails closed, enabled guard passes
 *   - Cross-space leakage prevention
 *   - DB integration tests using testcontainers
 */

import { randomUUID } from "node:crypto";
import Fastify from "fastify";
import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import {
  listOfficialPlugins,
  getOfficialPlugin,
  assertPluginRegistryIntegrity,
} from "../src/modules/plugins/registry";
import { pluginService } from "../src/modules/plugins/service";
import { installOfficialPlugin } from "../src/modules/plugins/installer";
import { BUILT_IN_PLUGINS } from "../src/modules/plugins/builtInPlugins";
import { DAIRY_PLUGIN_ID } from "../src/modules/plugins/official/dairy";
import type {
  AgentSpacePlugin,
  PluginHostContext,
  PluginJobHandler,
  PluginScheduledTask,
  Queryable,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

// ── Registry unit tests (no DB needed) ────────────────────────────────────────

describe("OfficialPluginRegistry", () => {
  it("has no duplicate plugin ids", () => {
    const ids = listOfficialPlugins().map((d) => d.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(ids.length);
  });

  it("assertPluginRegistryIntegrity does not throw for valid registry", () => {
    expect(() => assertPluginRegistryIntegrity()).not.toThrow();
  });

  it("contains dairy", () => {
    const descriptor = getOfficialPlugin(DAIRY_PLUGIN_ID);
    expect(descriptor).toBeDefined();
    expect(descriptor!.id).toBe(DAIRY_PLUGIN_ID);
    expect(descriptor!.name).toBe("Dairy");
  });

  it("dairy is disabled by default", () => {
    const descriptor = getOfficialPlugin(DAIRY_PLUGIN_ID);
    expect(descriptor!.default_enabled).toBe(false);
  });

  it("dairy scope is user (personal, cross-space)", () => {
    const descriptor = getOfficialPlugin(DAIRY_PLUGIN_ID);
    expect(descriptor!.scope).toBe("user");
  });

  it("all descriptors are serializable (no functions)", () => {
    for (const descriptor of listOfficialPlugins()) {
      expect(() => JSON.stringify(descriptor)).not.toThrow();
      const roundTripped = JSON.parse(JSON.stringify(descriptor));
      expect(roundTripped.id).toBe(descriptor.id);
    }
  });

  it("all descriptors have non-empty id and name", () => {
    for (const descriptor of listOfficialPlugins()) {
      expect(descriptor.id.trim()).toBeTruthy();
      expect(descriptor.name.trim()).toBeTruthy();
    }
  });

  it("returns undefined for unknown plugin id", () => {
    expect(getOfficialPlugin("nonexistent_plugin")).toBeUndefined();
  });
});

// ── DB integration tests ──────────────────────────────────────────────────────

const SCHEMA = `
CREATE TABLE official_plugin_enablements (
  id                  VARCHAR(36)   NOT NULL PRIMARY KEY,
  space_id            VARCHAR(36),
  user_id             VARCHAR(36),
  plugin_id           VARCHAR(128)  NOT NULL,
  enabled             BOOLEAN       NOT NULL,
  visible             BOOLEAN       NOT NULL DEFAULT TRUE,
  settings_json       JSONB         NOT NULL DEFAULT '{}'::JSONB,
  enabled_at          TIMESTAMPTZ,
  enabled_by_user_id  VARCHAR(36),
  disabled_at         TIMESTAMPTZ,
  disabled_by_user_id VARCHAR(36),
  created_at          TIMESTAMPTZ   NOT NULL,
  updated_at          TIMESTAMPTZ   NOT NULL,
  CONSTRAINT official_plugin_enablements_plugin_id_non_empty
    CHECK (plugin_id <> ''),
  CONSTRAINT official_plugin_enablements_settings_is_object
    CHECK (jsonb_typeof(settings_json) = 'object'),
  CONSTRAINT official_plugin_enablements_scope_check
    CHECK (
      (space_id IS NOT NULL AND user_id IS NULL) OR
      (space_id IS NULL AND user_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX official_plugin_enablements_space_unique
  ON official_plugin_enablements (plugin_id, space_id)
  WHERE (space_id IS NOT NULL AND user_id IS NULL);

CREATE UNIQUE INDEX official_plugin_enablements_user_unique
  ON official_plugin_enablements (plugin_id, user_id)
  WHERE (space_id IS NULL AND user_id IS NOT NULL);

CREATE INDEX official_plugin_enablements_space_idx
  ON official_plugin_enablements (space_id)
  WHERE (space_id IS NOT NULL);

CREATE TABLE official_plugin_events (
  id              VARCHAR(36)   NOT NULL PRIMARY KEY,
  space_id        VARCHAR(36),
  plugin_id       VARCHAR(128)  NOT NULL,
  event_type      VARCHAR(64)   NOT NULL,
  actor_user_id   VARCHAR(36),
  target_user_id  VARCHAR(36),
  metadata_json   JSONB         NOT NULL DEFAULT '{}'::JSONB,
  created_at      TIMESTAMPTZ   NOT NULL,
  CONSTRAINT official_plugin_events_plugin_id_non_empty
    CHECK (plugin_id <> ''),
  CONSTRAINT official_plugin_events_event_type_non_empty
    CHECK (event_type <> ''),
  CONSTRAINT official_plugin_events_metadata_is_object
    CHECK (jsonb_typeof(metadata_json) = 'object')
);

CREATE TABLE plugin_installs (
  id                   VARCHAR(36)  NOT NULL PRIMARY KEY,
  plugin_id            VARCHAR(64)  NOT NULL,
  installed_version    VARCHAR(32)  NOT NULL,
  status               VARCHAR(16)  NOT NULL DEFAULT 'active',
  source               VARCHAR(16)  NOT NULL DEFAULT 'official',
  installed_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  installed_by_user_id VARCHAR(36),
  package_hash         TEXT,
  manifest_json        JSONB        NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT plugin_installs_plugin_id_unique UNIQUE (plugin_id),
  CONSTRAINT plugin_installs_status_valid CHECK (status IN ('active', 'disabled', 'removed'))
);

CREATE TABLE plugin_migrations (
  id               VARCHAR(36)  NOT NULL PRIMARY KEY,
  plugin_id        VARCHAR(64)  NOT NULL,
  plugin_version   VARCHAR(32)  NOT NULL,
  migration_id     VARCHAR(128) NOT NULL,
  checksum         TEXT,
  applied_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  status           VARCHAR(16)  NOT NULL DEFAULT 'applied',
  error_message    TEXT,
  CONSTRAINT plugin_migrations_unique UNIQUE (plugin_id, migration_id),
  CONSTRAINT plugin_migrations_status_valid CHECK (status IN ('applied', 'failed'))
);
`;

interface DbQueryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<{ rows: Row[]; rowCount: number | null }>;
}

let container: StartedPostgreSqlContainer | null = null;
let pool: Pool | null = null;
let db: DbQueryable;

const SPACE_A = "space-a-test";
const SPACE_B = "space-b-test";
const USER_1 = "user-1-test";
const USER_2 = "user-2-test";

beforeAll(async () => {
  container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  db = pool;
  await pool.query(SCHEMA);
}, 60_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  await pool!.query("DROP TABLE IF EXISTS dairy_reflections");
  await pool!.query("DROP TABLE IF EXISTS dairy_entries");
  await pool!.query("DELETE FROM plugin_migrations");
  await pool!.query("DELETE FROM plugin_installs");
  await pool!.query("DELETE FROM official_plugin_events");
  await pool!.query("DELETE FROM official_plugin_enablements");
});

async function installDairy(): Promise<void> {
  await installOfficialPlugin(db, DAIRY_PLUGIN_ID, BUILT_IN_PLUGINS, {
    actorUserId: USER_1,
    source: "official",
  });
}

async function insertDairyEntry(
  userId: string,
  date: string,
  content: string,
): Promise<string> {
  const id = randomUUID();
  const result = await pool!.query<{ id: string }>(
    `INSERT INTO dairy_entries (id, user_id, entry_date, content)
     VALUES ($1, $2, $3::date, $4)
     RETURNING id`,
    [id, userId, date, content],
  );
  return result.rows[0]!.id;
}

async function buildDairyJobHandler(jobType: string): Promise<PluginJobHandler> {
  const plugin = BUILT_IN_PLUGINS.find((candidate) => candidate.id === DAIRY_PLUGIN_ID);
  if (!plugin) throw new Error("dairy plugin runtime not loaded");

  const app = Fastify({ logger: false });
  const handlers = new Map<string, PluginJobHandler>();
  const ctx = testPluginHostContext(plugin, app, pool!, handlers);
  plugin.activate(ctx);
  await app.close();

  const handler = handlers.get(jobType);
  if (!handler) throw new Error(`plugin job handler not registered: ${jobType}`);
  return handler;
}

function testPluginHostContext(
  plugin: AgentSpacePlugin,
  fastify: unknown,
  db: Queryable,
  handlers: Map<string, PluginJobHandler>,
): PluginHostContext {
  return {
    pluginId: plugin.id,
    fastify,
    db,
    isEnabled: async () => true,
    http: {
      resolveIdentity: async () => null,
      pluginGuard: async () => null,
      sendError: () => undefined,
      parseJsonBody: () => ({}),
    },
    jobs: {
      register: (registeredJobType, handler) => {
        handlers.set(registeredJobType, handler);
      },
      enqueue: async () => ({ jobId: randomUUID() }),
    },
    scheduler: {
      register: (_task: PluginScheduledTask) => undefined,
    },
    proposals: {
      register: () => undefined,
    },
  };
}

describe("pluginService.listPlugins", () => {
  it("returns dairy as disabled when no row exists", async () => {
    const items = await pluginService.listPlugins(db, SPACE_A, USER_1);
    const dairy = items.find((i) => i.descriptor.id === DAIRY_PLUGIN_ID);
    expect(dairy).toBeDefined();
    expect(dairy!.effective.installed).toBe(false);
    expect(dairy!.effective.enabled).toBe(false);
    expect(dairy!.effective.has_row).toBe(false);
  });

  it("returns all descriptors", async () => {
    const items = await pluginService.listPlugins(db, SPACE_A, USER_1);
    const allIds = listOfficialPlugins().map((d) => d.id);
    for (const id of allIds) {
      expect(items.some((i) => i.descriptor.id === id)).toBe(true);
    }
  });
});

describe("pluginService.installPlugin", () => {
  it("installs dairy and creates plugin-owned tables through plugin migrations", async () => {
    await installDairy();

    const install = await pool!.query(
      "SELECT * FROM plugin_installs WHERE plugin_id = $1 AND status = 'active'",
      [DAIRY_PLUGIN_ID],
    );
    expect(install.rowCount).toBe(1);

    const migrations = await pool!.query(
      "SELECT * FROM plugin_migrations WHERE plugin_id = $1 AND migration_id = $2",
      [DAIRY_PLUGIN_ID, "0001_create_dairy_tables"],
    );
    expect(migrations.rowCount).toBe(1);

    await pool!.query("INSERT INTO dairy_entries (user_id, entry_date, content) VALUES ($1, $2::date, $3)", [
      USER_1,
      "2026-06-19",
      "Installed table works",
    ]);
  });

  it("fails when an already-applied plugin migration checksum changes", async () => {
    await installDairy();
    const dairyPlugin = BUILT_IN_PLUGINS.find((plugin) => plugin.id === DAIRY_PLUGIN_ID)!;
    const migration = dairyPlugin.migrations![0]!;

    await expect(
      installOfficialPlugin(
        db,
        DAIRY_PLUGIN_ID,
        [
          {
            ...dairyPlugin,
            migrations: [
              {
                ...migration,
                sql: `${migration.sql}\n-- changed after install\n`,
              },
            ],
          },
        ],
        {
          actorUserId: USER_1,
          source: "official",
        },
      ),
    ).rejects.toThrow("Plugin migration checksum mismatch: dairy/0001_create_dairy_tables");
  });
});

describe("pluginService.enablePlugin", () => {
  it("fails closed when the plugin is not installed", async () => {
    await expect(
      pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {}),
    ).rejects.toThrow("Plugin is not installed: dairy");
  });

  it("persists enablement state", async () => {
    await installDairy();
    const result = await pluginService.enablePlugin(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
      {},
    );
    expect(result.effective.enabled).toBe(true);
    expect(result.effective.has_row).toBe(true);
  });

  it("can be re-read after enable", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const item = await pluginService.getPlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1);
    expect(item.effective.enabled).toBe(true);
  });

  it("stores initial settings merged with defaults", async () => {
    await installDairy();
    const result = await pluginService.enablePlugin(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
      { settings: { daily_reminder_enabled: true } },
    );
    expect(result.effective.settings.daily_reminder_enabled).toBe(true);
    // Defaults still present
    expect(result.effective.settings.ai_reflection_enabled).toBe(false);
  });

  it("listPlugins uses the descriptor scope when duplicate-scope rows exist", async () => {
    await installDairy();
    await pluginService.enablePlugin(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
      { settings: { daily_reminder_enabled: true } },
    );
    await pool!.query(
      `INSERT INTO official_plugin_enablements
         (id, space_id, user_id, plugin_id, enabled, visible, settings_json, created_at, updated_at)
       VALUES ($1, $2, NULL, $3, false, true, '{}'::jsonb, now(), now())`,
      ["wrong-scope-row", SPACE_A, DAIRY_PLUGIN_ID],
    );

    const items = await pluginService.listPlugins(db, SPACE_A, USER_1);
    const dairy = items.find((i) => i.descriptor.id === DAIRY_PLUGIN_ID);
    expect(dairy?.effective.enabled).toBe(true);
    expect(dairy?.effective.settings.daily_reminder_enabled).toBe(true);
  });
});

describe("pluginService.disablePlugin", () => {
  it("persists disabled state after enable", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const result = await pluginService.disablePlugin(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
    );
    expect(result.effective.enabled).toBe(false);
    expect(result.effective.has_row).toBe(true);
  });

  it("does not delete data — row still exists after disable", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    await pluginService.disablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1);
    const rows = await pool!.query(
      "SELECT * FROM official_plugin_enablements WHERE plugin_id = $1",
      [DAIRY_PLUGIN_ID],
    );
    expect(rows.rowCount).toBeGreaterThan(0);
  });

  it("preserves settings when disabling without a settings body", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {
      settings: { daily_reminder_enabled: true },
    });
    const result = await pluginService.disablePlugin(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
    );
    expect(result.effective.enabled).toBe(false);
    expect(result.effective.settings.daily_reminder_enabled).toBe(true);
  });
});

describe("pluginService.patchSettings", () => {
  it("patches settings_json", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const result = await pluginService.patchSettings(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
      { daily_reminder_enabled: true, ai_reflection_enabled: true },
    );
    expect(result.effective.settings.daily_reminder_enabled).toBe(true);
    expect(result.effective.settings.ai_reflection_enabled).toBe(true);
  });

  it("creates row if not exists when patching settings", async () => {
    const result = await pluginService.patchSettings(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
      { include_in_context: true },
    );
    expect(result.effective.settings.include_in_context).toBe(true);
    expect(result.effective.has_row).toBe(true);
  });
});

describe("pluginService.isEnabled (guard helper)", () => {
  it("returns enabled=false for unknown plugin", async () => {
    const result = await pluginService.isEnabled(db, "nonexistent", SPACE_A, USER_1);
    expect(result.exists).toBe(false);
    expect(result.installed).toBe(false);
    expect(result.enabled).toBe(false);
  });

  it("returns enabled=false for dairy before any row", async () => {
    const result = await pluginService.isEnabled(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
    );
    expect(result.exists).toBe(true);
    expect(result.installed).toBe(false);
    expect(result.enabled).toBe(false);
  });

  it("returns enabled=true after enabling", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const result = await pluginService.isEnabled(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
    );
    expect(result.exists).toBe(true);
    expect(result.installed).toBe(true);
    expect(result.enabled).toBe(true);
  });

  it("returns enabled=false after disabling", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    await pluginService.disablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1);
    const result = await pluginService.isEnabled(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_1,
    );
    expect(result.exists).toBe(true);
    expect(result.enabled).toBe(false);
  });
});

describe("user-scope cross-space behaviour", () => {
  it("enabling (user-scope) is visible from any space for the same user", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    // user-scope: enabled for USER_1 regardless of which space we check from
    const resultB = await pluginService.isEnabled(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_B,
      USER_1,
    );
    expect(resultB.enabled).toBe(true);
  });

  it("enabling for user 1 does not affect user 2", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const result2 = await pluginService.isEnabled(
      db,
      DAIRY_PLUGIN_ID,
      SPACE_A,
      USER_2,
    );
    expect(result2.enabled).toBe(false);
  });

  it("getEffectiveMap reflects user-scope enablement across spaces", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    // same user, different space context — should see enabled because it's user-scoped
    const mapB = await pluginService.getEffectiveMap(db, SPACE_B, USER_1);
    expect(mapB[DAIRY_PLUGIN_ID]?.enabled).toBe(true);
  });

  it("getEffectiveMap returns disabled for a different user", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const mapUser2 = await pluginService.getEffectiveMap(db, SPACE_A, USER_2);
    expect(mapUser2[DAIRY_PLUGIN_ID]?.enabled).toBe(false);
  });
});

describe("plugin events audit log", () => {
  it("inserts an enabled event when enabling", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const result = await pool!.query(
      "SELECT * FROM official_plugin_events WHERE plugin_id = $1 AND event_type = 'enabled'",
      [DAIRY_PLUGIN_ID],
    );
    expect(result.rowCount).toBeGreaterThan(0);
  });

  it("inserts a disabled event when disabling", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    await pluginService.disablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1);
    const result = await pool!.query(
      "SELECT * FROM official_plugin_events WHERE plugin_id = $1 AND event_type = 'disabled'",
      [DAIRY_PLUGIN_ID],
    );
    expect(result.rowCount).toBeGreaterThan(0);
  });

  it("inserts a settings_updated event when patching settings", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    await pluginService.patchSettings(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {
      daily_reminder_enabled: true,
    });
    const result = await pool!.query(
      "SELECT * FROM official_plugin_events WHERE plugin_id = $1 AND event_type = 'settings_updated'",
      [DAIRY_PLUGIN_ID],
    );
    expect(result.rowCount).toBeGreaterThan(0);
  });
});

describe("dairy reflection job settings", () => {
  it("skips reflection generation when ai_reflection_enabled is not set", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {});
    const currentEntryId = await insertDairyEntry(USER_1, "2026-06-19", "Today");
    await insertDairyEntry(USER_1, "2025-06-19", "Past entry");

    const handler = await buildDairyJobHandler("dairy_reflection");
    const result = await handler({
      job_id: "job-1",
      job_type: "dairy_reflection",
      payload: {
        user_id: USER_1,
        entry_id: currentEntryId,
        entry_date: "2026-06-19",
      },
      attempt_number: 1,
    });

    expect(result).toEqual({ skipped: true, reason: "reflection_disabled" });
    const reflections = await pool!.query("SELECT * FROM dairy_reflections");
    expect(reflections.rowCount).toBe(0);
  });

  it("writes a reflection only when ai_reflection_enabled is true", async () => {
    await installDairy();
    await pluginService.enablePlugin(db, DAIRY_PLUGIN_ID, SPACE_A, USER_1, {
      settings: { ai_reflection_enabled: true },
    });
    const currentEntryId = await insertDairyEntry(USER_1, "2026-06-19", "Today");
    await insertDairyEntry(USER_1, "2025-06-19", "Past entry");

    const handler = await buildDairyJobHandler("dairy_reflection");
    const result = await handler({
      job_id: "job-2",
      job_type: "dairy_reflection",
      payload: {
        user_id: USER_1,
        entry_id: currentEntryId,
        entry_date: "2026-06-19",
      },
      attempt_number: 1,
    });

    expect((result as Record<string, unknown>)["past_entries_count"]).toBe(1);
    const reflections = await pool!.query<{ content: string; ai_model: string | null }>(
      "SELECT content, ai_model FROM dairy_reflections",
    );
    expect(reflections.rowCount).toBe(1);
    expect(reflections.rows[0]?.content).toContain("Past entry");
    expect(reflections.rows[0]?.ai_model).toBe("stub");
  });
});
