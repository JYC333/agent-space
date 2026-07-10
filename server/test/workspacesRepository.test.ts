import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import type { QueryResult, Queryable } from "../src/modules/routeUtils/common";
import {
  PgWorkspaceRepository,
  type WorkspaceRow,
} from "../src/modules/workspaces/repository";

describe("workspace repository", () => {
  const tempRoots: string[] = [];

  afterEach(async () => {
    await Promise.all(tempRoots.map((path) => rm(path, { recursive: true, force: true })));
    tempRoots.length = 0;
  });

  it("does not mark system-managed workspaces stale during filesystem scan", async () => {
    const workspaceRoot = await mkdtemp(join(tmpdir(), "aspace-workspaces-"));
    tempRoots.push(workspaceRoot);
    const missingProjectPath = join(workspaceRoot, "space-1", "missing-project");
    const missingSystemPath = join(workspaceRoot, "space-1", "agent-space");
    const db = new WorkspaceScanFakeDb([
      workspaceRow({
        id: "system-core-workspace",
        name: "Agent Space",
        workspace_type: "system_core",
        kind: "repo",
        root_path: missingSystemPath,
        protected: true,
        system_managed: true,
      }),
      workspaceRow({
        id: "project-1",
        name: "Project",
        root_path: missingProjectPath,
      }),
    ]);
    const repo = new PgWorkspaceRepository(
      db,
      loadConfig({ WORKSPACE_ROOT: workspaceRoot }),
    );

    const result = await repo.scan({ spaceId: "space-1", userId: "user-1" });

    expect(result.marked_stale).toEqual(["Project"]);
    expect(db.markedStale).toEqual(["Project"]);
  });
});

class WorkspaceScanFakeDb implements Queryable {
  readonly markedStale: string[] = [];

  constructor(private readonly rows: WorkspaceRow[]) {}

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    if (sql.includes("SELECT id, space_id") && sql.includes("status = 'active'")) {
      const [spaceId] = params;
      return result(
        this.rows.filter((row) => row.space_id === spaceId && row.status === "active") as Row[],
      );
    }

    if (sql.includes("UPDATE workspaces") && sql.includes("status = 'stale'")) {
      const names = params[1] as string[];
      this.markedStale.push(...names);
      for (const row of this.rows) {
        if (names.includes(row.name)) row.status = "stale";
      }
      return result([]);
    }

    if (sql.includes("SELECT id FROM workspaces") && sql.includes("root_path = $2")) {
      const [spaceId, rootPath] = params;
      const row = this.rows.find(
        (candidate) =>
          candidate.space_id === spaceId &&
          candidate.root_path === rootPath &&
          candidate.status === "active",
      );
      return result(row ? [{ id: row.id }] as Row[] : []);
    }

    if (sql.includes("INSERT INTO workspaces")) {
      throw new Error("workspace scan should not create rows in this test");
    }

    throw new Error(`Unexpected SQL: ${sql}`);
  }
}

function workspaceRow(overrides: Partial<WorkspaceRow> = {}): WorkspaceRow {
  return {
    id: "workspace-1",
    space_id: "space-1",
    created_by_user_id: "user-1",
    owner_user_id: "user-1",
    name: "Workspace",
    slug: null,
    description: null,
    workspace_type: "project",
    kind: "project",
    repo_url: null,
    root_path: "/missing",
    default_branch: null,
    visibility: "private",
    access_level: "full",
    status: "active",
    protected: false,
    system_managed: false,
    registered_from: null,
    metadata_json: null,
    allow_external_root: false,
    snapshot_retention_days: null,
    snapshot_max_count: null,
    created_at: new Date(0),
    updated_at: new Date(0),
    ...overrides,
  };
}

function result<Row>(rows: Row[]): QueryResult<Row> {
  return { rows, rowCount: rows.length };
}
