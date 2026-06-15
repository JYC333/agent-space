import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { PgMemoryReadRepository, MemoryReadValidationError } from "../src/modules/memory/repository";

// Real-PostgreSQL integration tests for the TS memory read model (Stage 6 slice
// 5). The route/parity unit suites use fakes, so they cannot catch the defects
// that only surface on the real stack: the scoped WHERE + post-filter
// pagination, jsonb selected_user_ids/tags parsing, ILIKE search, summary-only
// redaction, cross-user/cross-space visibility, and the project_id membership
// check. These run the actual SQL against a throwaway Postgres (testcontainers)
// loaded with test/fixtures/memorySchema.sql.
//
// Skips gracefully when Docker is unavailable so `npm test` runs everywhere.

const SCHEMA = readFileSync(
  join(process.cwd(), "test/fixtures/memorySchema.sql"),
  "utf8",
);

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let repo: PgMemoryReadRepository | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("postgres:18").start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    await pool.query(SCHEMA);
    repo = new PgMemoryReadRepository(pool);
    available = true;
  } catch (err) {
    console.warn(
      `[memory-read-integration] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}, 120_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

const SPACE = "space-1";
const USER = "user-1";

async function insertMemory(over: Record<string, unknown>): Promise<void> {
  const cols: Record<string, unknown> = {
    id: over.id,
    space_id: SPACE,
    scope_type: "user",
    memory_type: "fact",
    status: "active",
    visibility: "private",
    sensitivity_level: "normal",
    confidence: 1,
    importance: 0.5,
    version: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...over,
  };
  const names = Object.keys(cols);
  const placeholders = names.map((n, i) =>
    n === "selected_user_ids" || n === "tags" ? `$${i + 1}::jsonb` : `$${i + 1}`,
  );
  const values = names.map((n) =>
    n === "selected_user_ids" || n === "tags"
      ? cols[n] === undefined
        ? null
        : JSON.stringify(cols[n])
      : cols[n],
  );
  await pool!.query(
    `INSERT INTO memory_entries (${names.join(", ")}) VALUES (${placeholders.join(", ")})`,
    values,
  );
}

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query("TRUNCATE memory_entries, projects, memory_access_logs");
});

async function accessLogs(memoryId: string): Promise<Array<Record<string, unknown>>> {
  const res = await pool!.query(
    "SELECT * FROM memory_access_logs WHERE memory_id = $1 ORDER BY accessed_at",
    [memoryId],
  );
  return res.rows;
}

async function counters(memoryId: string): Promise<{ access_count: number; last_accessed_at: unknown }> {
  const res = await pool!.query(
    "SELECT access_count, last_accessed_at FROM memory_entries WHERE id = $1",
    [memoryId],
  );
  return res.rows[0] as { access_count: number; last_accessed_at: unknown };
}

describe("PgMemoryReadRepository against real Postgres", () => {
  it("lists only readable rows and paginates the filtered set", async () => {
    if (!available || !repo) return;
    // Readable: own private, space_shared. Hidden: another user's private,
    // soft-deleted, system scope.
    await insertMemory({ id: "m-own", owner_user_id: USER, importance: 0.9 });
    await insertMemory({ id: "m-shared", owner_user_id: "other", visibility: "space_shared", importance: 0.8 });
    await insertMemory({ id: "m-private-other", owner_user_id: "other", visibility: "private", importance: 0.7 });
    await insertMemory({ id: "m-deleted", owner_user_id: USER, deleted_at: new Date().toISOString() });
    await insertMemory({ id: "m-system", scope_type: "system", owner_user_id: null, visibility: "space_shared" });

    const page = await repo.list(SPACE, USER, { limit: 50, offset: 0 });
    expect(page.items.map((m) => m.id).sort()).toEqual(["m-own", "m-shared"]);
    expect(page.total).toBe(2);

    // Pagination applies to the readable set.
    const paged = await repo.list(SPACE, USER, { limit: 1, offset: 1 });
    expect(paged.total).toBe(2);
    expect(paged.items).toHaveLength(1);
    expect(paged.items[0]?.id).toBe("m-shared"); // importance DESC → m-own first
  });

  it("redacts summary_only content for a non-owner but not the owner", async () => {
    if (!available || !repo) return;
    await insertMemory({
      id: "m-sum",
      owner_user_id: "other",
      visibility: "summary_only",
      content: "secret body",
    });
    const asViewer = await repo.list(SPACE, USER, { limit: 50, offset: 0 });
    expect(asViewer.items[0]?.content).toBeNull();

    const asOwner = await repo.list(SPACE, "other", { limit: 50, offset: 0 });
    expect(asOwner.items[0]?.content).toBe("secret body");
  });

  it("get returns null across users/spaces and parses jsonb fields", async () => {
    if (!available || !repo) return;
    await insertMemory({
      id: "m-1",
      owner_user_id: USER,
      tags: ["a", "b"],
      selected_user_ids: ["x"],
    });
    const out = await repo.get(SPACE, USER, "m-1", null);
    expect(out?.tags).toEqual(["a", "b"]);
    expect(out?.selected_user_ids).toEqual(["x"]);
    // Another user cannot read a private memory.
    expect(await repo.get(SPACE, "other", "m-1", null)).toBeNull();
    // Wrong space.
    expect(await repo.get("space-2", USER, "m-1", null)).toBeNull();
  });

  it("searches active rows by title/content ILIKE with visibility applied", async () => {
    if (!available || !repo) return;
    await insertMemory({ id: "m-hit", owner_user_id: USER, content: "the TS migration plan" });
    await insertMemory({ id: "m-miss", owner_user_id: USER, content: "unrelated" });
    await insertMemory({ id: "m-hidden", owner_user_id: "other", visibility: "private", content: "TS secret" });

    const rows = await repo.search(SPACE, USER, { query: "TS", limit: 10 });
    expect(rows.map((m) => m.id).sort()).toEqual(["m-hit"]);
  });

  it("hides scope=system seed memories from search unless opted in", async () => {
    if (!available || !repo) return;
    await insertMemory({ id: "m-user", owner_user_id: USER, content: "system ted note" });
    await insertMemory({
      id: "m-sys",
      scope_type: "system",
      owner_user_id: null,
      visibility: "space_shared",
      namespace: "system.memory_policy",
      title: "Memory Policy",
      content: "Core memory rules: system policy",
    });

    // Default: the system seed is hidden.
    const def = await repo.search(SPACE, USER, { query: "system", limit: 10 });
    expect(def.map((m) => m.id)).toEqual(["m-user"]);

    // Opt-in flag includes it.
    const opted = await repo.search(SPACE, USER, { query: "system", limit: 10, includeSystem: true });
    expect(opted.map((m) => m.id).sort()).toEqual(["m-sys", "m-user"]);

    // Explicit scope=system also returns it (and only it).
    const scoped = await repo.search(SPACE, USER, { query: "system", limit: 10, scope: "system" });
    expect(scoped.map((m) => m.id)).toEqual(["m-sys"]);
  });

  it("hides scope=system from list unless opted in", async () => {
    if (!available || !repo) return;
    await insertMemory({ id: "m-user", owner_user_id: USER });
    await insertMemory({
      id: "m-sys",
      scope_type: "system",
      owner_user_id: null,
      visibility: "space_shared",
      namespace: "system.memory_policy",
    });

    const def = await repo.list(SPACE, USER, { limit: 50, offset: 0 });
    expect(def.items.map((m) => m.id)).toEqual(["m-user"]);

    const opted = await repo.list(SPACE, USER, { limit: 50, offset: 0, includeSystem: true });
    expect(opted.items.map((m) => m.id).sort()).toEqual(["m-sys", "m-user"]);
  });

  it("get writes one explicit_read trace and bumps the read counters", async () => {
    if (!available || !repo || !pool) return;
    await insertMemory({ id: "m-1", owner_user_id: USER });

    await repo.get(SPACE, USER, "m-1", null);

    const logs = await accessLogs("m-1");
    expect(logs).toHaveLength(1);
    expect(logs[0]).toMatchObject({
      space_id: SPACE,
      memory_id: "m-1",
      user_id: USER,
      agent_id: null,
      run_id: null,
      access_type: "explicit_read",
      reason: null,
    });
    const c = await counters("m-1");
    expect(c.access_count).toBe(1);
    expect(c.last_accessed_at).not.toBeNull();

    // A second read increments again.
    await repo.get(SPACE, USER, "m-1", null);
    expect(await accessLogs("m-1")).toHaveLength(2);
    expect((await counters("m-1")).access_count).toBe(2);
  });

  it("does not log when get is not visible to the viewer", async () => {
    if (!available || !repo || !pool) return;
    await insertMemory({ id: "m-priv", owner_user_id: "other", visibility: "private" });

    expect(await repo.get(SPACE, USER, "m-priv", null)).toBeNull();
    expect(await accessLogs("m-priv")).toHaveLength(0);
    expect((await counters("m-priv")).access_count).toBe(0);
  });

  it("search writes a search_hit trace per returned row; list logs nothing", async () => {
    if (!available || !repo || !pool) return;
    await insertMemory({ id: "m-a", owner_user_id: USER, content: "TS alpha" });
    await insertMemory({ id: "m-b", owner_user_id: USER, content: "TS beta" });
    await insertMemory({ id: "m-hidden", owner_user_id: "other", visibility: "private", content: "TS secret" });

    const rows = await repo.search(SPACE, USER, { query: "TS", limit: 10 });
    expect(rows.map((m) => m.id).sort()).toEqual(["m-a", "m-b"]);

    for (const id of ["m-a", "m-b"]) {
      const logs = await accessLogs(id);
      expect(logs).toHaveLength(1);
      expect(logs[0]).toMatchObject({ access_type: "search_hit", reason: "memory search", user_id: USER });
      expect((await counters(id)).access_count).toBe(1);
    }
    // The non-visible row is neither returned nor logged.
    expect(await accessLogs("m-hidden")).toHaveLength(0);

    // list() reads are never logged.
    await repo.list(SPACE, USER, { limit: 50, offset: 0 });
    expect(await accessLogs("m-a")).toHaveLength(1);
    expect((await counters("m-a")).access_count).toBe(1);
  });

  it("raises on a project filter that is not in the space", async () => {
    if (!available || !repo || !pool) return;
    await insertMemory({ id: "m-1", owner_user_id: USER, project_id: "proj-1" });
    await pool.query(
      "INSERT INTO projects (id, space_id) VALUES ('proj-1', $1)",
      [SPACE],
    );
    // Valid project filter returns rows.
    const ok = await repo.list(SPACE, USER, { limit: 50, offset: 0, projectId: "proj-1" });
    expect(ok.items).toHaveLength(1);
    // Unknown project → validation error (→ 422 at the route).
    await expect(
      repo.list(SPACE, USER, { limit: 50, offset: 0, projectId: "missing" }),
    ).rejects.toBeInstanceOf(MemoryReadValidationError);
  });
});
