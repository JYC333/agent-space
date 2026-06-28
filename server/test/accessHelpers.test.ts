import { describe, expect, it } from "vitest";
import { isKnownSpaceRole, isSpaceOwnerOrAdmin } from "../src/modules/access/roles";
import {
  artifactVisibleSql,
  canReadByVisibility,
  spaceObjectVisibleSql,
  taskVisibleSql,
} from "../src/modules/access/visibility";

describe("access helpers", () => {
  it("keeps scoped row visibility fail-closed", () => {
    expect(canReadByVisibility("space_shared", "u1", [])).toBe(true);
    expect(canReadByVisibility("workspace_shared", "u1", [])).toBe(true);
    expect(canReadByVisibility("private", "u1", ["u2", "u1"])).toBe(true);
    expect(canReadByVisibility("restricted", "u1", ["u2"])).toBe(false);
    expect(canReadByVisibility("unknown", "u1", ["u1"])).toBe(false);
  });

  it("centralizes space owner/admin role checks", () => {
    expect(isKnownSpaceRole("reviewer")).toBe(true);
    expect(isKnownSpaceRole("superuser")).toBe(false);
    expect(isSpaceOwnerOrAdmin("owner")).toBe(true);
    expect(isSpaceOwnerOrAdmin("admin")).toBe(true);
    expect(isSpaceOwnerOrAdmin("reviewer")).toBe(false);
    expect(isSpaceOwnerOrAdmin(null)).toBe(false);
  });

  it("builds the shared space-object predicate", () => {
    expect(spaceObjectVisibleSql("so", "$2")).toBe(
      "(so.visibility IN ('space_shared', 'workspace_shared') OR so.owner_user_id = $2 OR so.created_by_user_id = $2)",
    );
  });

  it("builds task predicates without broadening product task lists by default", () => {
    expect(taskVisibleSql({ userExpr: "$1" })).toBe(
      "(t.visibility IN ('space_shared', 'workspace_shared') OR t.created_by_user_id = $1 OR t.assigned_user_id = $1 OR t.claimed_by_user_id = $1)",
    );
    expect(taskVisibleSql({ userExpr: "$1", includePublicTemplate: true })).toContain(
      "'public_template'",
    );
  });

  it("builds artifact predicates with workspace inheritance only when supplied", () => {
    expect(artifactVisibleSql({ userExpr: "$2" })).toContain("OR false");
    const workspaceSql = artifactVisibleSql({
      userExpr: "$3",
      workspaceMatchExpr: "t.workspace_id",
    });
    expect(workspaceSql).toContain("a.workspace_id = t.workspace_id");
    expect(workspaceSql).toContain("project_workspaces");
    expect(workspaceSql).toContain("a.owner_user_id = $3");
  });
});
