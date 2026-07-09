import { describe, expect, it } from "vitest";
import { PgActivityRepository } from "../src/modules/activity/repository";
import { PgProjectRepository } from "../src/modules/projects/repository";
import { PgProposalRepository } from "../src/modules/proposals/repository";
import { PgRunRepository } from "../src/modules/runs/repository";
import type { QueryResult, Queryable, SpaceUserIdentity } from "../src/modules/routeUtils/common";

class FakeDb implements Queryable {
  constructor(private readonly handler: (sql: string, params: readonly unknown[]) => unknown[]) {}

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    return { rows: this.handler(sql, params) as Row[], rowCount: null };
  }
}

const identity: SpaceUserIdentity = { spaceId: "space-1", userId: "user-1" };

describe("Project association validation", () => {
  it("hides activity creation project targets outside the caller's project access", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM projects")) return [];
      if (sql.includes("INSERT INTO activity_records")) {
        throw new Error("activity insert should not run");
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(
      new PgActivityRepository(db).create(identity, {
        source_type: "user_capture",
        content: "cross-space project",
        project_id: "project-other",
      }),
    ).rejects.toMatchObject({ statusCode: 404, message: "Project not found" });
  });

  it("hides activity list project filters outside the caller's project access", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM projects")) return [];
      if (sql.includes("FROM activity_records")) {
        throw new Error("activity list should not run");
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(
      new PgActivityRepository(db).list(identity, {
        projectId: "project-other",
        limit: 10,
        offset: 0,
      }),
    ).rejects.toMatchObject({ statusCode: 404, message: "Project not found" });
  });

  it("rejects proposal list project filters outside the current space", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM projects")) return [];
      if (sql.includes("FROM proposals")) {
        throw new Error("proposal list should not run");
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(
      new PgProposalRepository(db).listVisible("space-1", "user-1", {
        status: "pending",
        projectId: "project-other",
        limit: 10,
        offset: 0,
      }),
    ).rejects.toMatchObject({ statusCode: 422, message: "Project not found" });
  });

  it("rejects run list project filters outside the current space", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM projects")) return [];
      if (sql.includes("FROM runs")) {
        throw new Error("run list should not run");
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(
      new PgRunRepository(db).listRuns({
        space_id: "space-1",
        user_id: "user-1",
        project_id: "project-other",
        limit: 10,
        offset: 0,
      }),
    ).rejects.toMatchObject({ statusCode: 422, message: "Project not found" });
  });

  it("removes project workspace links without mutating project source bindings", async () => {
    const calls: Array<{ sql: string; params: readonly unknown[] }> = [];
    const db = new FakeDb((sql, params) => {
      calls.push({ sql, params });
      if (sql.includes("FROM projects")) return [{ id: "project-1", owner_user_id: "user-1" }];
      if (sql.startsWith("DELETE FROM project_workspaces")) return [];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await new PgProjectRepository(db).unlinkWorkspace(identity, "project-1", "workspace-1", null);

    const deleteCall = calls.find((call) => call.sql.startsWith("DELETE FROM project_workspaces"));
    expect(deleteCall?.sql).toContain("space_id = $1");
    expect(deleteCall?.params).toEqual(["space-1", "project-1", "workspace-1"]);
    expect(calls.some((call) => call.sql.includes("project_source_bindings"))).toBe(false);
  });
});
