import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce } from "../policy/service";
import { proposalToOut } from "../proposals/repository";
import { insertProposalRow } from "../proposals/reviewPackets";
import { canReadMemory, type MemoryAuthFields } from "./memoryReadAuth";
import { canAccessProject } from "./projectAccess";

import type {
  MemoryProposalArchiveCommand,
  MemoryProposalCreateCommand,
  MemoryProposalUpdateCommand,
  ProposalOut,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { PolicyCheckRequest } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};

export interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

export interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

export class MemoryProposalValidationError extends Error {
  readonly statusCode = 422;
}

export class MemoryProposalForbiddenError extends Error {
  readonly statusCode = 403;
}

export class MemoryProposalNotFoundError extends Error {
  readonly statusCode = 404;
}

export class MemoryProposalPolicyError extends Error {
  readonly statusCode: number;
  readonly body: Record<string, unknown>;

  constructor(statusCode: number, body: Record<string, unknown>) {
    super(String(body.message ?? body.detail ?? "Policy gate blocked"));
    this.statusCode = statusCode;
    this.body = body;
  }
}

interface TargetMemoryRow extends MemoryAuthFields {
  id: string;
  workspace_id: string | null;
  scope_type: string;
  namespace: string | null;
  memory_type: string;
  title: string | null;
  content: string | null;
  project_id: string | null;
}

const TARGET_MEMORY_COLUMNS = `id, space_id, owner_user_id, workspace_id,
  scope_type, namespace, memory_type, title, content, visibility,
  sensitivity_level, selected_user_ids, deleted_at, project_id`;

const SENSITIVITY_LEVELS = new Set([
  "normal",
  "sensitive",
  "restricted",
  "highly_restricted",
]);

const VISIBILITY_VALUES = new Set([
  "private",
  "space_shared",
  "workspace_shared",
  "selected_users",
  "summary_only",
  "restricted",
  "public_template",
]);

/**
 * server-owned public memory proposal creation. This repository writes pending
 * `proposals` rows only. It reads target memories for
 * update/archive authorization, but never mutates `memory_entries`; active
 * memory writes remain proposal-apply authority.
 */
export class PgMemoryProposalRepository {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  static fromConfig(config: ServerConfig): PgMemoryProposalRepository {
    if (!config.databaseUrl) {
      throw new Error("Memory proposal repository requires SERVER_DATABASE_URL");
    }
    return new PgMemoryProposalRepository(getDbPool(config.databaseUrl), config);
  }

  async createMemoryProposal(
    identitySpaceId: string,
    userId: string,
    command: MemoryProposalCreateCommand,
  ): Promise<ProposalOut> {
    const effectiveSpaceId = command.space_id ?? identitySpaceId;
    if (effectiveSpaceId !== identitySpaceId) {
      throw new MemoryProposalForbiddenError(
        "Cannot create memory proposal in another space",
      );
    }

    const scope = command.scope ?? "user";
    // When the caller does not specify visibility, default by space type so the
    // proposal is coherent with the apply-time placement invariant: a personal
    // space gets `private`, a multi-member space gets owner-only `restricted`
    // (never `private`, which the applier bars outside personal spaces).
    const visibility = normalizeVisibility(
      command.visibility ?? (await this.defaultCreateVisibility(effectiveSpaceId)),
    );
    const sensitivity = normalizeSensitivity(command.sensitivity_level ?? "normal");
    validateCreateCommand(command, visibility, sensitivity);

    const subjectUserId =
      scope === "system"
        ? null
        : command.subject_user_id ?? (scope === "user" ? userId : null);
    const ownerUserId = scope === "system" ? null : command.owner_user_id ?? null;
    const payload: Record<string, unknown> = {
      operation: "create",
      proposed_content: command.content,
      memory_type: command.type,
      target_scope: scope,
      target_namespace: command.namespace ?? "user.default",
      target_visibility: visibility,
      sensitivity_level: sensitivity,
      provenance_entries: mergeDistinctProvenanceEntries([
        userConfirmationEntry(userId, { method: "POST", path: "/memory" }),
      ]),
    };
    if (subjectUserId !== null) payload.subject_user_id = subjectUserId;
    if (ownerUserId !== null) payload.owner_user_id = ownerUserId;
    if (command.selected_user_ids !== null && command.selected_user_ids !== undefined) {
      payload.selected_user_ids = command.selected_user_ids;
    }
    if (command.source_id !== null && command.source_id !== undefined) {
      payload.source_id = command.source_id;
    }

    await this.enforceProposalCreate({
      spaceId: effectiveSpaceId,
      userId,
      proposalType: "memory_create",
      workspaceId: command.workspace_id ?? null,
      targetScope: scope,
      targetVisibility: visibility,
      targetMemoryId: null,
      sensitivityLevel: sensitivity,
    });

    return this.insertProposal({
      spaceId: effectiveSpaceId,
      userId,
      proposalType: "memory_create",
      title: command.title,
      payload,
      rationale: "Memory creation requested via public API.",
      workspaceId: command.workspace_id ?? null,
      targetMemoryId: null,
      targetScope: scope,
      targetVisibility: visibility,
      sensitivityLevel: sensitivity,
    });
  }

  async updateMemoryProposal(
    spaceId: string,
    userId: string,
    memoryId: string,
    workspaceId: string | null,
    command: MemoryProposalUpdateCommand,
  ): Promise<ProposalOut> {
    const target = await this.getVisibleTargetMemory(
      spaceId,
      userId,
      memoryId,
      workspaceId,
    );
    if (!target) throw new MemoryProposalNotFoundError("Memory not found");

    const changeData = compactCommand(command, [
      "operation",
      "actor_user_id",
      "target_memory_id",
      "provenance_entries",
      "workspace_id",
      "memory_layer",
    ]);
    const payload: Record<string, unknown> = {
      operation: "update",
      target_memory_id: memoryId,
      target_scope: target.scope_type,
      target_namespace: target.namespace ?? "user.default",
      memory_type: target.memory_type,
      provenance_entries: mergeDistinctProvenanceEntries([
        userConfirmationEntry(userId, {
          method: "PATCH",
          path: `/memory/${memoryId}`,
        }),
      ]),
    };

    if (changeData.content !== undefined) {
      payload.proposed_content = changeData.content;
      payload.content = changeData.content;
    }
    if (changeData.title !== undefined) {
      payload.proposed_title = changeData.title;
      payload.title = changeData.title;
    }
    if (changeData.visibility !== undefined) {
      const visibility = normalizeVisibility(String(changeData.visibility));
      payload.visibility = visibility;
      payload.target_visibility = visibility;
    }
    if (changeData.sensitivity_level !== undefined) {
      payload.sensitivity_level = normalizeSensitivity(
        String(changeData.sensitivity_level),
      );
    }
    if (changeData.subject_user_id !== undefined) {
      payload.subject_user_id = changeData.subject_user_id;
    }
    if (changeData.owner_user_id !== undefined) {
      payload.owner_user_id = changeData.owner_user_id;
    }
    if (changeData.selected_user_ids !== undefined) {
      payload.selected_user_ids = changeData.selected_user_ids;
    }
    if (changeData.scope !== undefined) {
      payload.target_scope = changeData.scope;
    }
    if (changeData.namespace !== undefined) {
      payload.target_namespace = changeData.namespace;
    }
    if (changeData.type !== undefined) {
      payload.memory_type = changeData.type;
    }
    validateUpdatePayload(payload);

    const title =
      typeof changeData.title === "string" && changeData.title.length > 0
        ? changeData.title
        : target.title || `Update: ${memoryId.slice(0, 8)}`;
    const targetScope = stringValue(payload.target_scope);
    const targetVisibility =
      stringValue(payload.target_visibility) ?? stringValue(payload.visibility);
    const sensitivityLevel = stringValue(payload.sensitivity_level);

    await this.enforceProposalCreate({
      spaceId,
      userId,
      proposalType: "memory_update",
      workspaceId: workspaceId ?? target.workspace_id,
      targetScope,
      targetVisibility,
      targetMemoryId: memoryId,
      sensitivityLevel,
    });

    return this.insertProposal({
      spaceId,
      userId,
      proposalType: "memory_update",
      title,
      payload,
      rationale: "Memory update requested via public API.",
      workspaceId: workspaceId ?? target.workspace_id,
      targetMemoryId: memoryId,
      targetScope,
      targetVisibility,
      sensitivityLevel,
    });
  }

  async archiveMemoryProposal(
    spaceId: string,
    userId: string,
    memoryId: string,
    workspaceId: string | null,
    command: MemoryProposalArchiveCommand,
  ): Promise<ProposalOut> {
    const target = await this.getVisibleTargetMemory(
      spaceId,
      userId,
      memoryId,
      workspaceId,
    );
    if (!target) throw new MemoryProposalNotFoundError("Memory not found");

    const payload: Record<string, unknown> = {
      operation: "archive",
      target_memory_id: memoryId,
      target_scope: target.scope_type,
      target_namespace: target.namespace ?? "user.default",
      memory_type: target.memory_type,
      proposed_content: target.content ?? "",
      provenance_entries: mergeDistinctProvenanceEntries([
        userConfirmationEntry(userId, {
          method: "DELETE",
          path: `/memory/${memoryId}`,
        }),
      ]),
    };

    await this.enforceProposalCreate({
      spaceId,
      userId,
      proposalType: "memory_archive",
      workspaceId: workspaceId ?? target.workspace_id,
      targetScope: target.scope_type,
      targetVisibility: target.visibility,
      targetMemoryId: memoryId,
      sensitivityLevel: null,
    });

    return this.insertProposal({
      spaceId,
      userId,
      proposalType: "memory_archive",
      title: `Archive: ${target.title || memoryId.slice(0, 8)}`,
      payload,
      rationale: "Memory archive requested via public API.",
      workspaceId: workspaceId ?? target.workspace_id,
      targetMemoryId: memoryId,
      targetScope: target.scope_type,
      targetVisibility: target.visibility,
      sensitivityLevel: null,
    });
  }

  /** Space-type-aware default visibility for a create with no explicit value. */
  private async defaultCreateVisibility(spaceId: string): Promise<string> {
    const res = await this.db.query<{ type: string }>(
      `SELECT type FROM spaces WHERE id = $1`,
      [spaceId],
    );
    return (res.rows[0]?.type ?? "unknown") === "personal" ? "private" : "restricted";
  }

  private async getVisibleTargetMemory(
    spaceId: string,
    userId: string,
    memoryId: string,
    workspaceId: string | null,
  ): Promise<TargetMemoryRow | null> {
    const result = await this.db.query<TargetMemoryRow>(
      `SELECT ${TARGET_MEMORY_COLUMNS}
         FROM memory_entries
        WHERE id = $1
          AND space_id = $2
          AND deleted_at IS NULL`,
      [memoryId, spaceId],
    );
    const row = result.rows[0];
    if (!row) return null;
    const includeSystemScope = row.scope_type === "system";
    if (!canReadMemory(row, { userId, spaceId, workspaceId, includeSystemScope })) return null;
    if (row.project_id && !(await canAccessProject(this.db, spaceId, row.project_id, userId))) return null;
    return row;
  }

  private async enforceProposalCreate(input: {
    spaceId: string;
    userId: string;
    proposalType: "memory_create" | "memory_update" | "memory_archive";
    workspaceId: string | null;
    targetScope: string | null;
    targetVisibility: string | null;
    targetMemoryId: string | null;
    sensitivityLevel: string | null;
  }): Promise<void> {
    const registry = await loadActionRegistry();
    const req: PolicyCheckRequest = {
      action: "proposal.create",
      actor_type: "user",
      actor_id: input.userId,
      space_id: input.spaceId,
      resource_type: "proposal",
      resource_id: null,
      resource_space_id: input.spaceId,
      run_id: null,
      proposal_id: null,
      actor_ref: null,
      payload: null,
      force_record: false,
      context: {
        target_visibility: input.targetVisibility,
        target_scope: input.targetScope,
      },
      metadata_json: {
        proposal_type: input.proposalType,
        workspace_id: input.workspaceId,
        target_memory_id: input.targetMemoryId,
        sensitivity_level: input.sensitivityLevel,
        urgency: "normal",
      },
    };
    const result = await enforce(this.config, registry, req);
    if (result.status === "allow") return;
    if (result.status === "error") {
      throw new MemoryProposalPolicyError(500, {
        error: result.error_code ?? "policy_audit_persist_failed",
        message:
          result.message ??
          "Policy decision audit could not be persisted; sensitive action was blocked.",
        audit_code: "policy_decision_record_persist_failed",
      });
    }
    const decision = result.decision;
    throw new MemoryProposalPolicyError(403, {
      error: result.error_code ?? "policy_denied",
      message: result.message ?? decision?.message ?? "Policy gate blocked",
      reason_code: decision?.reason_code,
      audit_code: decision?.audit_code,
      action: "proposal.create",
      risk_level: decision?.risk_level,
    });
  }

  private async insertProposal(input: {
    spaceId: string;
    userId: string;
    proposalType: "memory_create" | "memory_update" | "memory_archive";
    title: string;
    payload: Record<string, unknown>;
    rationale: string;
    workspaceId: string | null;
    targetMemoryId: string | null;
    targetScope: string | null;
    targetVisibility: string | null;
    sensitivityLevel: string | null;
  }): Promise<ProposalOut> {
    const now = new Date();
    const row = await insertProposalRow(this.db, {
      spaceId: input.spaceId,
      proposalType: input.proposalType,
      title: input.title,
      payload: input.payload,
      rationale: input.rationale,
      workspaceId: input.workspaceId,
      createdByUserId: input.userId,
      visibility: "space_shared",
      riskLevel: "low",
    });
    return proposalToOut(row, now);
  }
}

function normalizeSensitivity(value: string): string {
  const normalized = value.toLowerCase();
  if (!SENSITIVITY_LEVELS.has(normalized)) {
    throw new MemoryProposalValidationError(`invalid sensitivity_level: ${JSON.stringify(value)}`);
  }
  return normalized;
}

function normalizeVisibility(value: string): string {
  const normalized = value.toLowerCase();
  if (!VISIBILITY_VALUES.has(normalized)) {
    throw new MemoryProposalValidationError(`invalid visibility: ${JSON.stringify(value)}`);
  }
  return normalized;
}

function validateCreateCommand(
  command: MemoryProposalCreateCommand,
  visibility: string,
  sensitivity: string,
): void {
  const layer = command.memory_layer?.toLowerCase();
  if (layer !== undefined && layer !== null && layer !== "episodic" && layer !== "semantic") {
    throw new MemoryProposalValidationError(
      `invalid memory_layer: ${JSON.stringify(command.memory_layer)}`,
    );
  }
  if (sensitivity === "highly_restricted" && visibility === "space_shared") {
    throw new MemoryProposalValidationError(
      "highly_restricted memories cannot use space_shared visibility for MVP",
    );
  }
  validateSelectedUsers(command.selected_user_ids, visibility);
  if (sensitivity === "highly_restricted" && !command.owner_user_id) {
    throw new MemoryProposalValidationError(
      "owner_user_id is required when sensitivity_level is highly_restricted",
    );
  }
}

function validateUpdatePayload(payload: Record<string, unknown>): void {
  const sensitivity = stringValue(payload.sensitivity_level);
  const visibility =
    stringValue(payload.target_visibility) ?? stringValue(payload.visibility);
  if (sensitivity === "highly_restricted" && visibility === "space_shared") {
    throw new MemoryProposalValidationError(
      "highly_restricted memories cannot use space_shared visibility for MVP",
    );
  }
  const selected = Array.isArray(payload.selected_user_ids)
    ? payload.selected_user_ids
    : null;
  if (selected !== null && visibility !== null) {
    validateSelectedUsers(selected, visibility);
  }
}

function validateSelectedUsers(
  selectedUserIds: readonly unknown[] | null | undefined,
  visibility: string,
): void {
  if (
    selectedUserIds !== null &&
    selectedUserIds !== undefined &&
    visibility !== "selected_users" &&
    visibility !== "restricted"
  ) {
    throw new MemoryProposalValidationError(
      "selected_user_ids is only valid when visibility is selected_users or restricted",
    );
  }
}

function userConfirmationEntry(
  userId: string,
  evidence: Record<string, unknown>,
): Record<string, unknown> {
  return {
    source_type: "user_confirmation",
    source_id: userId,
    source_trust: "user_confirmed",
    evidence_json: { ...evidence, channel: "explicit_user_action" },
  };
}

function mergeDistinctProvenanceEntries(
  rawEntries: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const merged: Array<Record<string, unknown>> = [];
  const seen = new Set<string>();
  for (const entry of rawEntries) {
    const sourceType = stringValue(entry.source_type);
    const sourceId = stringValue(entry.source_id);
    if (!sourceType || !sourceId) continue;
    const sourceTrust = stringValue(entry.source_trust);
    const key = `${sourceType}:${sourceId}:${sourceTrust ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(entry);
  }
  return merged;
}

function compactCommand(
  command: Record<string, unknown>,
  skip: readonly string[],
): Record<string, unknown> {
  const skipSet = new Set(skip);
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(command)) {
    if (skipSet.has(key)) continue;
    if (value === null || value === undefined) continue;
    out[key] = value;
  }
  return out;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
