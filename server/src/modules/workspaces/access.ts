/**
 * Project-inherited workspace read access.
 *
 * Workspaces do not have their own membership table. A workspace becomes
 * readable to a non-owner through any active Project that links it via
 * `project_workspaces` and grants the user Project access.
 */
export function workspaceProjectReadAccessSql(input: {
  spaceExpr: string;
  workspaceExpr: string;
  userExpr: string;
}): string {
  const { spaceExpr, workspaceExpr, userExpr } = input;
  return `(
    EXISTS (
      SELECT 1
        FROM workspaces workspace_access_workspace
        JOIN spaces workspace_access_space
          ON workspace_access_space.id = workspace_access_workspace.space_id
       WHERE workspace_access_workspace.id = ${workspaceExpr}
         AND workspace_access_workspace.space_id = ${spaceExpr}
         AND workspace_access_space.type = 'personal'
    )
    OR EXISTS (
      SELECT 1
        FROM project_workspaces workspace_access_link
        JOIN projects workspace_access_project
          ON workspace_access_project.id = workspace_access_link.project_id
         AND workspace_access_project.space_id = ${spaceExpr}
         AND workspace_access_project.deleted_at IS NULL
        LEFT JOIN project_members workspace_access_member
          ON workspace_access_member.space_id = workspace_access_project.space_id
         AND workspace_access_member.project_id = workspace_access_project.id
         AND workspace_access_member.user_id = ${userExpr}
         AND workspace_access_member.status = 'active'
        JOIN workspaces workspace_access_workspace
          ON workspace_access_workspace.id = workspace_access_link.workspace_id
         AND workspace_access_workspace.space_id = workspace_access_project.space_id
       WHERE workspace_access_link.workspace_id = ${workspaceExpr}
         AND (
           workspace_access_project.owner_user_id = ${userExpr}
           OR workspace_access_member.user_id IS NOT NULL
         )
    )
  )`;
}
