import type { ServerConfig } from "../../config";
import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import { HttpError, requiredString, withQueryableTransaction } from "../routeUtils/common";
import { PgSourcesRepository } from "./repository";
import { insertProposalRow } from "../proposals/reviewPackets";
import { PgProposalApplyService } from "../proposals/applyService";

interface ProposeCreateActor {
  agentId?: string | null;
  runId?: string | null;
  idempotencyKey?: string | null;
  projectId?: string | null;
}

/** Application boundary for source-connection lifecycle operations. */
export class SourceConnectionService {
  private readonly repository: PgSourcesRepository;

  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {
    this.repository = new PgSourcesRepository(db, config);
  }

  listConnectors() {
    return this.repository.listConnectors();
  }

  listConnections(
    identity: SpaceUserIdentity,
    filters: { view: string | null; status: string | null; limit: number; offset: number },
  ) {
    return this.repository.listConnections(identity, filters);
  }

  createConnection(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
    options: { allowCustomSourceConnector?: boolean } = {},
  ) {
    const connectorKey = requiredString(body.connector_key, "connector_key");
    if (connectorKey === "custom_source" && !options.allowCustomSourceConnector) {
      throw new HttpError(422, "Custom Source connections must be created through the Custom Source draft flow");
    }
    return this.repository.createConnection(identity, body);
  }

  createDraft(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    return this.createConnection(identity, { ...body, _initial_status: "paused" });
  }

  async proposeCreate(identity: SpaceUserIdentity, body: Record<string, unknown>, actor: ProposeCreateActor = {}) {
    const reused = await this.reuseProposalByRunIdempotencyKey(identity.spaceId, actor);
    if (reused) return reused;

    let created: Awaited<ReturnType<SourceConnectionService["createProposalLocked"]>>;
    try {
      created = await withQueryableTransaction(this.db, (db) =>
        new SourceConnectionService(db, this.config).createProposalLocked(identity, body, actor),
      );
    } catch (error) {
      if (actor.runId && actor.idempotencyKey && (error as { code?: string }).code === "23505") {
        const reusedAfterConflict = await this.reuseProposalByRunIdempotencyKey(identity.spaceId, actor);
        if (reusedAfterConflict) return reusedAfterConflict;
      }
      throw error;
    }

    const { draft, proposal } = created;
    const connectionId = requiredString(draft.id, "source_connection_id");
    const autoApplied = actor.agentId
      ? await PgProposalApplyService.fromConfig(this.config).acceptAgentProposalIfGranted(proposal.id as string, {
          actionId: "source.connection.propose_create",
          resourceKind: "source_connection",
          resourceId: connectionId,
        })
      : null;
    return { draft, proposal: autoApplied?.proposal ?? proposal, auto_applied: Boolean(autoApplied) };
  }

  getConnection(identity: SpaceUserIdentity, connectionId: string) {
    return this.repository.getConnection(identity, connectionId);
  }

  recommendConnection(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    return this.repository.recommendConnection(identity, connectionId, body);
  }

  updateConnectionSubscription(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    return this.repository.updateConnectionSubscription(identity, connectionId, body);
  }

  updateConnection(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    return this.repository.updateConnection(identity, connectionId, body);
  }

  /** Activates a reviewed, paused Source connection draft. The only status transition proposal appliers may trigger. */
  activate(identity: SpaceUserIdentity, connectionId: string) {
    return this.updateConnection(identity, connectionId, { status: "active" });
  }

  archiveConnection(identity: SpaceUserIdentity, connectionId: string) {
    return this.repository.updateConnection(identity, connectionId, { status: "archived" });
  }

  scanConnection(identity: SpaceUserIdentity, connectionId: string) {
    return this.repository.scanConnection(identity, connectionId);
  }

  private async reuseProposalByRunIdempotencyKey(spaceId: string, actor: ProposeCreateActor) {
    if (!actor.runId || !actor.idempotencyKey) return null;
    const existing = await this.db.query<{ id: string; status: string; payload_json: Record<string, unknown> }>(
      `SELECT * FROM proposals WHERE space_id=$1 AND created_by_run_id=$2 AND proposal_type='source_connection_create' AND action_idempotency_key=$3`,
      [spaceId, actor.runId, actor.idempotencyKey],
    );
    if (!existing.rows[0]) return null;
    const draft = await this.db.query(
      `SELECT * FROM source_connections WHERE id=$1 AND space_id=$2`,
      [existing.rows[0].payload_json?.source_connection_id, spaceId],
    );
    return { draft: draft.rows[0], proposal: existing.rows[0], auto_applied: existing.rows[0].status === "accepted" };
  }

  private async createProposalLocked(identity: SpaceUserIdentity, body: Record<string, unknown>, actor: ProposeCreateActor) {
    const draft = (await this.createDraft(identity, body)) as Record<string, unknown>;
    const connectionId = requiredString(draft.id, "source_connection_id");
    const proposal = await insertProposalRow(this.db, {
      spaceId: identity.spaceId,
      proposalType: "source_connection_create",
      title: `Activate Source: ${String(draft.name ?? "draft")}`,
      payload: {
        proposal_type: "source_connection_create",
        action_id: "source.connection.propose_create",
        source_connection_id: connectionId,
        draft_updated_at: draft.updated_at,
        ...(actor.idempotencyKey ? { idempotency_key: actor.idempotencyKey } : {}),
      },
      rationale: "Activate a reviewed Source connection draft.",
      createdByUserId: actor.agentId ? null : identity.userId,
      createdByAgentId: actor.agentId ?? null,
      createdByRunId: actor.runId ?? null,
      actionIdempotencyKey: actor.idempotencyKey ?? null,
      projectId: actor.projectId ?? null,
      visibility: "space_shared",
      riskLevel: "medium",
      requiredApproverRole: "owner",
    });
    return { draft, proposal };
  }
}
