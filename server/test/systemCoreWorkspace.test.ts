import { describe, expect, it } from "vitest";
import type { QueryResult } from "../src/modules/routeUtils/common";
import {
  SYSTEM_CORE_WORKSPACE_ID,
  upsertSystemCoreWorkspace,
} from "../src/modules/workspaces/systemCore";

describe("system core workspace registration", () => {
  it("reactivates an existing system core workspace record", async () => {
    const db = new SystemCoreFakeDb([
      {
        id: SYSTEM_CORE_WORKSPACE_ID,
        space_id: "space-1",
        created_by_user_id: null,
        root_path: "/old/path",
        default_branch: "master",
        workspace_type: "project",
        kind: "project",
        status: "stale",
        visibility: "private",
        protected: false,
        system_managed: false,
        registered_from: null,
      },
    ]);

    const action = await upsertSystemCoreWorkspace(db, {
      spaceId: "space-1",
      userId: "user-1",
      workspaceDir: "/aspace/workspaces/space-1/agent-space",
      baseBranch: "main",
    });

    expect(action).toBe("updated");
    expect(db.rows[0]).toMatchObject({
      root_path: "/aspace/workspaces/space-1/agent-space",
      default_branch: "main",
      workspace_type: "system_core",
      kind: "repo",
      status: "active",
      protected: true,
      system_managed: true,
      registered_from: "auto",
      created_by_user_id: "user-1",
    });
  });
});

interface SystemCoreWorkspaceRow {
  id: string;
  space_id: string;
  created_by_user_id: string | null;
  root_path: string;
  default_branch: string;
  workspace_type: string;
  kind: string;
  status: string;
  visibility: string;
  protected: boolean;
  system_managed: boolean;
  registered_from: string | null;
}

class SystemCoreFakeDb {
  constructor(readonly rows: SystemCoreWorkspaceRow[]) {}

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    if (sql.includes("SELECT id FROM workspaces")) {
      const [id, spaceId] = params;
      const row = this.rows.find((r) => r.id === id && r.space_id === spaceId);
      return result(row ? [{ id: row.id }] : []) as QueryResult<Row>;
    }

    if (sql.includes("UPDATE workspaces")) {
      const [workspaceDir, baseBranch, userId, id, spaceId] = params;
      const row = this.rows.find((r) => r.id === id && r.space_id === spaceId);
      if (!row) return result([]);
      row.root_path = String(workspaceDir);
      row.default_branch = String(baseBranch);
      row.workspace_type = "system_core";
      row.kind = "repo";
      row.status = "active";
      row.visibility = "private";
      row.protected = true;
      row.system_managed = true;
      row.registered_from ??= "auto";
      row.created_by_user_id ??= String(userId);
      return result([]);
    }

    if (sql.includes("INSERT INTO workspaces")) {
      const [id, spaceId, userId, , , workspaceDir, baseBranch] = params;
      this.rows.push({
        id: String(id),
        space_id: String(spaceId),
        created_by_user_id: String(userId),
        root_path: String(workspaceDir),
        default_branch: String(baseBranch),
        workspace_type: "system_core",
        kind: "repo",
        status: "active",
        visibility: "private",
        protected: true,
        system_managed: true,
        registered_from: "auto",
      });
      return result([]);
    }

    throw new Error(`Unexpected SQL: ${sql}`);
  }
}

function result<Row>(rows: Row[]): QueryResult<Row> {
  return { rows, rowCount: rows.length };
}
