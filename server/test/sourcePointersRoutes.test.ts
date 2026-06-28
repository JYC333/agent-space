import type { FastifyInstance } from "fastify";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { getDbPool } from "../src/db/pool";
import { buildServer } from "../src/server";
import { __setAuthIdentityForTests } from "../src/modules/auth";

vi.mock("../src/db/pool", () => ({
  getDbPool: vi.fn(),
}));

let app: FastifyInstance | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
});

afterEach(async () => {
  __setAuthIdentityForTests(null);
  await app?.close();
  app = undefined;
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
  });
}

function json(payload: Record<string, unknown>) {
  return {
    headers: { "content-type": "application/json" },
    payload: JSON.stringify(payload),
  };
}

describe("SourcePointer routes", () => {
  it("creates metadata-only pointers after dual membership and source object checks", async () => {
    const query = vi.fn(async (sql: string) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM space_memberships")) {
        return { rows: [{ role: "member" }], rowCount: 1 };
      }
      if (norm.includes("FROM memory_entries")) {
        return { rows: [{ "?column?": 1 }], rowCount: 1 };
      }
      if (norm.includes("INSERT INTO source_pointers")) {
        return {
          rows: [{
            id: "pointer-1",
            owner_space_id: "space-1",
            source_space_id: "source-space",
            source_object_type: "memory_entry",
            source_object_id: "memory-1",
            access_mode: "read",
            granted_by_user_id: "user-1",
            expires_at: null,
            metadata_json: { label: "citation" },
            created_at: "2026-06-12T10:00:00.000Z",
          }],
          rowCount: 1,
        };
      }
      return { rows: [], rowCount: 0 };
    });
    vi.mocked(getDbPool).mockReturnValue({ query } as never);
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/source-pointers",
      ...json({
        source_space_id: "source-space",
        source_object_type: "memory_entry",
        source_object_id: "memory-1",
        metadata_json: { label: "citation" },
      }),
    });

    expect(res.statusCode).toBe(201);
    expect(res.json()).toMatchObject({
      id: "pointer-1",
      owner_space_id: "space-1",
      granted_by_user_id: "user-1",
      metadata_json: { label: "citation" },
    });
    expect(query.mock.calls.some(([sql]) => String(sql).includes("INSERT INTO source_pointers"))).toBe(true);
  });

  it("rejects content-bearing metadata keys recursively", async () => {
    const query = vi.fn(async (sql: string) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM space_memberships")) return { rows: [{ role: "member" }], rowCount: 1 };
      if (norm.includes("FROM artifacts")) return { rows: [{ "?column?": 1 }], rowCount: 1 };
      return { rows: [], rowCount: 0 };
    });
    vi.mocked(getDbPool).mockReturnValue({ query } as never);
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/source-pointers",
      ...json({
        source_space_id: "source-space",
        source_object_type: "artifact",
        source_object_id: "artifact-1",
        metadata_json: { nested: { raw_text: "do not store this" } },
      }),
    });

    expect(res.statusCode).toBe(422);
    expect(res.json().detail).toContain("forbidden key");
    expect(query.mock.calls.some(([sql]) => String(sql).includes("INSERT INTO source_pointers"))).toBe(false);
  });

  it("requires owner/admin role to delete", async () => {
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM space_memberships")) {
        return { rows: [{ role: "member" }], rowCount: 1 };
      }
      return { rows: [], rowCount: 0 };
    });
    vi.mocked(getDbPool).mockReturnValue({ query } as never);
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "DELETE",
      url: "/api/v1/source-pointers/pointer-1",
    });

    expect(res.statusCode).toBe(403);
    expect(res.json().detail).toContain("Only owner/admin");
    expect(query.mock.calls.some(([sql]) => String(sql).includes("DELETE FROM source_pointers"))).toBe(false);
  });
});
