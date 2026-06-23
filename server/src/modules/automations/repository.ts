import { randomUUID } from "node:crypto";
import type { Pool } from "../../db/pool";
import { withTransaction } from "../../db/tx";
import type { Queryable } from "../routeUtils/common";
import { HttpError } from "../routeUtils/common";
import { computeNextRunAt } from "./schedule";

export interface AutomationRow {
  id: string;
  space_id: string;
  owner_user_id: string;
  agent_id: string;
  workspace_id: string | null;
  name: string;
  description: string | null;
  trigger_type: string;
  status: string;
  preflight_snapshot_json: Record<string, unknown> | null;
  config_json: Record<string, unknown> | null;
  next_run_at: string | null;
  last_fired_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationRepositoryPort {
  get(spaceId: string, automationId: string): Promise<AutomationRow | null>;
  getMembershipRole(spaceId: string, userId: string): Promise<string | null>;
  getAgentPreflight(spaceId: string, agentId: string): Promise<{
    status: string;
    current_version_id: string | null;
    version_id: string | null;
  } | null>;
  create(input: {
    spaceId: string;
    ownerUserId: string;
    name: string;
    description?: string | null;
    agentId: string;
    workspaceId?: string | null;
    triggerType: string;
    configJson: Record<string, unknown>;
    preflightSnapshot: Record<string, unknown>;
  }): Promise<AutomationRow>;
  update(
    spaceId: string,
    automationId: string,
    patch: {
      name?: string;
      description?: string | null;
      status?: string;
      config_json?: Record<string, unknown>;
    },
  ): Promise<AutomationRow>;
  listDue(nowIso: string): Promise<AutomationRow[]>;
  advanceSchedule(automation: AutomationRow): Promise<void>;
  recordFire(spaceId: string, automationId: string): Promise<void>;
  hasActiveGrant(spaceId: string, automationId: string): Promise<boolean>;
  createAutomationRun(input: {
    automationId: string;
    runId: string;
    triggeredByUserId: string;
    triggerType: string;
    preflightSnapshot: Record<string, unknown>;
  }): Promise<string>;
}

const AUTOMATION_COLUMNS = `
  id, space_id, owner_user_id, agent_id, workspace_id, name, description,
  trigger_type, status, preflight_snapshot_json, config_json, next_run_at,
  last_fired_at, created_at, updated_at
`;

export class PgAutomationRepository implements AutomationRepositoryPort {
  constructor(private readonly db: Queryable) {}

  async list(spaceId: string): Promise<AutomationRow[]> {
    const result = await this.db.query<AutomationRow>(
      `SELECT ${AUTOMATION_COLUMNS}
         FROM automations
        WHERE space_id = $1
        ORDER BY created_at DESC`,
      [spaceId],
    );
    return result.rows;
  }

  async get(spaceId: string, automationId: string): Promise<AutomationRow | null> {
    const result = await this.db.query<AutomationRow>(
      `SELECT ${AUTOMATION_COLUMNS}
         FROM automations
        WHERE space_id = $1 AND id = $2`,
      [spaceId, automationId],
    );
    return result.rows[0] ?? null;
  }

  async getMembershipRole(spaceId: string, userId: string): Promise<string | null> {
    const result = await this.db.query<{ role: string }>(
      `SELECT role
         FROM space_memberships
        WHERE space_id = $1
          AND user_id = $2
          AND status = 'active'
        LIMIT 1`,
      [spaceId, userId],
    );
    return result.rows[0]?.role ?? null;
  }

  async getAgentPreflight(
    spaceId: string,
    agentId: string,
  ): Promise<{ status: string; current_version_id: string | null; version_id: string | null } | null> {
    const result = await this.db.query<{
      status: string;
      current_version_id: string | null;
      version_id: string | null;
    }>(
      `SELECT a.status,
              a.current_version_id,
              av.id AS version_id
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id AND av.space_id = a.space_id
        WHERE a.space_id = $1 AND a.id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }

  async create(input: {
    spaceId: string;
    ownerUserId: string;
    name: string;
    description?: string | null;
    agentId: string;
    workspaceId?: string | null;
    triggerType: string;
    configJson: Record<string, unknown>;
    preflightSnapshot: Record<string, unknown>;
  }): Promise<AutomationRow> {
    if (isTransactionCapable(this.db)) {
      return withTransaction(this.db, async (client) =>
        new PgAutomationRepository(client).create(input),
      );
    }
    return this.createInCurrentUnit(input);
  }

  private async createInCurrentUnit(input: {
    spaceId: string;
    ownerUserId: string;
    name: string;
    description?: string | null;
    agentId: string;
    workspaceId?: string | null;
    triggerType: string;
    configJson: Record<string, unknown>;
    preflightSnapshot: Record<string, unknown>;
  }): Promise<AutomationRow> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const nextRunAt =
      input.triggerType === "schedule"
        ? computeNextRunAt(input.configJson).toISOString()
        : null;
    const result = await this.db.query<AutomationRow>(
      `INSERT INTO automations (
         id, space_id, owner_user_id, agent_id, workspace_id, name, description,
         trigger_type, status, preflight_snapshot_json, config_json, next_run_at,
         created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7,
         $8, 'active', $9::jsonb, $10::jsonb, $11,
         $12, $12
       )
       RETURNING ${AUTOMATION_COLUMNS}`,
      [
        id,
        input.spaceId,
        input.ownerUserId,
        input.agentId,
        input.workspaceId ?? null,
        input.name,
        input.description ?? null,
        input.triggerType,
        JSON.stringify(input.preflightSnapshot),
        JSON.stringify(input.configJson),
        nextRunAt,
        now,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("Automation insert returned no row");
    if (input.triggerType === "schedule") {
      await this.db.query(
        `INSERT INTO automation_credential_grants (
           id, space_id, automation_id, granted_by_user_id, status, created_at
         ) VALUES ($1, $2, $3, $4, 'active', $5)`,
        [randomUUID(), input.spaceId, id, input.ownerUserId, now],
      );
    }
    return row;
  }

  async update(
    spaceId: string,
    automationId: string,
    patch: {
      name?: string;
      description?: string | null;
      status?: string;
      config_json?: Record<string, unknown>;
    },
  ): Promise<AutomationRow> {
    const existing = await this.get(spaceId, automationId);
    if (!existing) throw new HttpError(404, `Automation '${automationId}' not found`);
    const now = new Date().toISOString();
    const configJson = patch.config_json ?? existing.config_json;
    let nextRunAt = existing.next_run_at;
    if (existing.trigger_type === "schedule" && patch.config_json) {
      nextRunAt = computeNextRunAt(configJson).toISOString();
    }
    if (patch.status === "archived") {
      nextRunAt = null;
      await this.revokeGrants(spaceId, automationId, existing.owner_user_id);
    }
    const result = await this.db.query<AutomationRow>(
      `UPDATE automations
          SET name = COALESCE($3, name),
              description = COALESCE($4, description),
              status = COALESCE($5, status),
              config_json = COALESCE($6::jsonb, config_json),
              next_run_at = $7,
              updated_at = $8
        WHERE space_id = $1 AND id = $2
        RETURNING ${AUTOMATION_COLUMNS}`,
      [
        spaceId,
        automationId,
        patch.name ?? null,
        patch.description ?? null,
        patch.status ?? null,
        patch.config_json ? JSON.stringify(patch.config_json) : null,
        nextRunAt,
        now,
      ],
    );
    return result.rows[0]!;
  }

  async listDue(nowIso: string): Promise<AutomationRow[]> {
    const result = await this.db.query<AutomationRow>(
      `SELECT ${AUTOMATION_COLUMNS}
         FROM automations
        WHERE trigger_type = 'schedule'
          AND status = 'active'
          AND next_run_at IS NOT NULL
          AND next_run_at <= $1`,
      [nowIso],
    );
    return result.rows;
  }

  async advanceSchedule(automation: AutomationRow): Promise<void> {
    const now = new Date().toISOString();
    let nextRunAt: string | null = null;
    try {
      nextRunAt = computeNextRunAt(automation.config_json).toISOString();
    } catch {
      nextRunAt = null;
    }
    await this.db.query(
      `UPDATE automations
          SET last_fired_at = $3,
              next_run_at = $4,
              updated_at = $3
        WHERE id = $1 AND space_id = $2`,
      [automation.id, automation.space_id, now, nextRunAt],
    );
  }

  async recordFire(spaceId: string, automationId: string): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE automations
          SET last_fired_at = $3,
              updated_at = $3
        WHERE id = $1 AND space_id = $2`,
      [automationId, spaceId, now],
    );
  }

  async hasActiveGrant(spaceId: string, automationId: string): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM automation_credential_grants
        WHERE space_id = $1 AND automation_id = $2 AND status = 'active'
        LIMIT 1`,
      [spaceId, automationId],
    );
    return Boolean(result.rows[0]);
  }

  async createAutomationRun(input: {
    automationId: string;
    runId: string;
    triggeredByUserId: string;
    triggerType: string;
    preflightSnapshot: Record<string, unknown>;
  }): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO automation_runs (
         id, automation_id, run_id, triggered_by_user_id, trigger_type,
         preflight_snapshot_json, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)`,
      [
        id,
        input.automationId,
        input.runId,
        input.triggeredByUserId,
        input.triggerType,
        JSON.stringify(input.preflightSnapshot),
        now,
      ],
    );
    return id;
  }

  private async revokeGrants(spaceId: string, automationId: string, actorUserId: string): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE automation_credential_grants
          SET status = 'revoked',
              revoked_at = $3,
              revoked_by_user_id = $4
        WHERE space_id = $1
          AND automation_id = $2
          AND status = 'active'`,
      [spaceId, automationId, now, actorUserId],
    );
  }
}

function isTransactionCapable(db: Queryable): db is Queryable & Pool {
  return "connect" in db && typeof (db as { connect?: unknown }).connect === "function";
}

export function automationToOut(row: AutomationRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    owner_user_id: row.owner_user_id,
    agent_id: row.agent_id,
    workspace_id: row.workspace_id,
    name: row.name,
    description: row.description,
    trigger_type: row.trigger_type,
    status: row.status,
    preflight_snapshot_json: row.preflight_snapshot_json,
    config_json: row.config_json,
    next_run_at: row.next_run_at,
    last_fired_at: row.last_fired_at,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}
