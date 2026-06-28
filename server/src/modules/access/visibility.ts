import { workspaceProjectReadAccessSql } from "../workspaces/access";

export function canReadByVisibility(
  visibility: string | null | undefined,
  userId: string,
  candidates: readonly (string | null | undefined)[],
): boolean {
  const value = (visibility || "space_shared").toLowerCase();
  if (value === "space_shared" || value === "workspace_shared") return true;
  if (value === "private" || value === "restricted" || value === "selected_users") {
    return candidates.some((candidate) => candidate === userId);
  }
  return false;
}

export function spaceObjectVisibleSql(alias: string, userExpr: string): string {
  return ownerScopedVisibleSql({
    visibilityExpr: `${alias}.visibility`,
    userExpr,
    ownerExprs: [`${alias}.owner_user_id`, `${alias}.created_by_user_id`],
    sharedVisibilities: ["space_shared", "workspace_shared"],
  });
}

export function taskVisibleSql(input: {
  alias?: string;
  userExpr: string;
  includePublicTemplate?: boolean;
}): string {
  const alias = input.alias ?? "t";
  return ownerScopedVisibleSql({
    visibilityExpr: `${alias}.visibility`,
    userExpr: input.userExpr,
    ownerExprs: [`${alias}.created_by_user_id`, `${alias}.assigned_user_id`, `${alias}.claimed_by_user_id`],
    sharedVisibilities: input.includePublicTemplate
      ? ["space_shared", "workspace_shared", "public_template"]
      : ["space_shared", "workspace_shared"],
  });
}

export function artifactVisibleSql(input: {
  alias?: string;
  userExpr: string;
  workspaceMatchExpr?: string | null;
}): string {
  const alias = input.alias ?? "a";
  const workspaceVisible = input.workspaceMatchExpr
    ? `(${alias}.visibility = 'workspace_shared'
        AND ${alias}.workspace_id IS NOT NULL
        AND ${alias}.workspace_id = ${input.workspaceMatchExpr}
        AND ${workspaceProjectReadAccessSql({
          spaceExpr: `${alias}.space_id`,
          workspaceExpr: `${alias}.workspace_id`,
          userExpr: input.userExpr,
        })})`
    : "false";
  return `(
    ${alias}.visibility IN ('space_shared', 'public_template')
    OR ${workspaceVisible}
    OR (${alias}.owner_user_id IS NULL AND ${alias}.visibility NOT IN ('workspace_shared', 'restricted', 'selected_users'))
    OR ${alias}.owner_user_id = ${input.userExpr}
  )`;
}

function ownerScopedVisibleSql(input: {
  visibilityExpr: string;
  userExpr: string;
  ownerExprs: readonly string[];
  sharedVisibilities: readonly string[];
}): string {
  const shared = input.sharedVisibilities.map((value) => `'${value}'`).join(", ");
  const owners = input.ownerExprs.map((expr) => `${expr} = ${input.userExpr}`).join(" OR ");
  return `(${input.visibilityExpr} IN (${shared}) OR ${owners})`;
}
