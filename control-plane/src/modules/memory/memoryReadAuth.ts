/**
 * Memory read authorization — faithful TS port of the Python memory
 * `read_auth` module (`can_read_memory`, `summary_only_redact_content`,
 * `user_in_selected_ids`).
 *
 * This is the security boundary for the TS memory read model (Stage 6 slice 5):
 * visibility, sensitivity, owner/subject separation, scope (system /
 * public_template), and workspace/selected-user gating must stay byte-identical
 * to Python or reads leak across users/spaces. A cross-language parity fixture
 * (`control-plane/test/fixtures/memory_read_auth_parity.json`) locks this.
 *
 * Owner is never inferred from subject_user_id.
 */

/** The subset of memory columns the authorization decision reads. */
export interface MemoryAuthFields {
  space_id: string;
  deleted_at: unknown;
  sensitivity_level: string | null;
  visibility: string | null;
  owner_user_id: string | null;
  scope_type: string | null;
  workspace_id: string | null;
  selected_user_ids: unknown;
}

export interface MemoryReadContext {
  userId: string;
  spaceId: string;
  workspaceId?: string | null;
  includeSystemScope?: boolean;
  includePublicTemplates?: boolean;
}

export function userInSelectedIds(selected: unknown, userId: string): boolean {
  if (selected === null || selected === undefined) return false;
  if (Array.isArray(selected)) return selected.includes(userId);
  if (typeof selected === "string") return userId === selected;
  return false;
}

/**
 * Return true if this reader may see the memory in any form (full or
 * summary-only redacted). Mirrors `can_read_memory` exactly, branch for branch.
 */
export function canReadMemory(
  memory: MemoryAuthFields,
  ctx: MemoryReadContext,
): boolean {
  const includeSystemScope = ctx.includeSystemScope ?? false;
  const includePublicTemplates = ctx.includePublicTemplates ?? false;

  if (memory.space_id !== ctx.spaceId || memory.deleted_at !== null) return false;

  const sens = (memory.sensitivity_level || "normal").toLowerCase();
  const vis = (memory.visibility || "private").toLowerCase();
  const owner = memory.owner_user_id;
  const scopeT = memory.scope_type;

  if (!includePublicTemplates && vis === "public_template") return false;
  if (!includeSystemScope && scopeT === "system") return false;

  if (sens === "highly_restricted") {
    return Boolean(owner && owner === ctx.userId);
  }

  if (owner && owner === ctx.userId) return true;

  if (vis === "private") return false;
  if (vis === "restricted") return userInSelectedIds(memory.selected_user_ids, ctx.userId);
  if (vis === "selected_users") return userInSelectedIds(memory.selected_user_ids, ctx.userId);
  if (vis === "summary_only") return true;
  if (vis === "workspace_shared") {
    if (ctx.workspaceId === null || ctx.workspaceId === undefined) return false;
    if (memory.workspace_id === null || memory.workspace_id === undefined) return false;
    return memory.workspace_id === ctx.workspaceId;
  }
  if (vis === "space_shared") return true;
  if (vis === "public_template" && includePublicTemplates) return true;

  return false;
}

/** True if full `content` must be withheld (summary_only visibility, non-owner). */
export function summaryOnlyRedactContent(
  memory: Pick<MemoryAuthFields, "visibility" | "owner_user_id">,
  viewerUserId: string,
): boolean {
  if ((memory.visibility || "").toLowerCase() !== "summary_only") return false;
  if (memory.owner_user_id && memory.owner_user_id === viewerUserId) return false;
  return true;
}
