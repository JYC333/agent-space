import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { PgWorkspaceRepository } from "../src/modules/workspaces/repository";

type Captured = { sql: string; params: readonly unknown[] };

class FakeDb {
  readonly queries: Captured[] = [];
  constructor(private readonly workspaceRowCount: number) {}

  async query(sql: string, params: readonly unknown[] = []) {
    this.queries.push({ sql, params });
    const norm = sql.replace(/\s+/g, " ").trim();
    if (norm.startsWith("UPDATE workspaces")) {
      return { rows: [], rowCount: this.workspaceRowCount };
    }
    if (norm.startsWith("UPDATE context_digests")) {
      return { rows: [], rowCount: 1 };
    }
    return { rows: [], rowCount: 0 };
  }
}

const identity = { spaceId: "space-1", userId: "user-1" };

function repoWith(db: FakeDb): PgWorkspaceRepository {
  return new PgWorkspaceRepository(db as never, loadConfig({}));
}

describe("PgWorkspaceRepository.archive — digest lifecycle", () => {
  it("disables the workspace's active/dirty digests when the workspace is archived", async () => {
    const db = new FakeDb(1);
    const ok = await repoWith(db).archive(identity, "ws-1");

    expect(ok).toBe(true);
    const disable = db.queries.find((q) => q.sql.includes("UPDATE context_digests"));
    expect(disable).toBeDefined();
    expect(disable?.sql).toContain("status = 'disabled'");
    expect(disable?.sql).toContain("status IN ('active', 'dirty')");
    // params: [now, spaceId, scopeType, scopeId]
    expect(disable?.params).toContain("space-1");
    expect(disable?.params).toContain("workspace");
    expect(disable?.params).toContain("ws-1");
  });

  it("does not touch digests when the workspace was not found (no-op archive)", async () => {
    const db = new FakeDb(0);
    const ok = await repoWith(db).archive(identity, "missing-ws");

    expect(ok).toBe(false);
    expect(db.queries.some((q) => q.sql.includes("UPDATE context_digests"))).toBe(false);
  });

  it("rolls back the archive when disabling digests fails (atomic)", async () => {
    const client = {
      queries: [] as string[],
      released: false,
      async query(sql: string) {
        const norm = sql.replace(/\s+/g, " ").trim();
        this.queries.push(norm);
        if (norm.startsWith("UPDATE workspaces")) return { rows: [], rowCount: 1 };
        if (norm.startsWith("UPDATE context_digests")) throw new Error("disable failed");
        return { rows: [], rowCount: 0 };
      },
      release() {
        this.released = true;
      },
    };
    const pool = {
      async connect() {
        return client;
      },
    };

    await expect(
      new PgWorkspaceRepository(pool as never, loadConfig({})).archive(identity, "ws-1"),
    ).rejects.toThrow(/disable failed/);

    expect(client.queries).toContain("BEGIN");
    expect(client.queries).toContain("ROLLBACK");
    expect(client.queries).not.toContain("COMMIT");
    expect(client.released).toBe(true);
  });
});
