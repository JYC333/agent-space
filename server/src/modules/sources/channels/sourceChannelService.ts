import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../../config";
import { HttpError, objectValue, optionalString, requiredString, type Queryable, type SpaceUserIdentity } from "../../routeUtils/common";
import { normalizeSourceConnectionCreateGovernance } from "../sourceConsent";
import { SourceProviderCatalogService, type ResolvedSourceProviderConnector } from "../catalog/sourceProviderCatalogService";
import { SourceChannelQueryCompiler } from "../catalog/sourceChannelQueryCompiler";
import { upsertSourceChannelScanTask } from "../sourceConnectionScheduler";
import { computeNextRunAtFromScheduleRule, type SourceScheduleRule } from "../sourceScheduleInput";
import { insertProposalRow } from "../../proposals/reviewPackets";
import { PgProposalApplyService } from "../../proposals/applyService";
import { CustomSourceCredentialService } from "../customSources/customSourceCredentialService";

interface SourceChannelProposalActor {
  agentId?: string | null;
  runId?: string | null;
  idempotencyKey?: string | null;
  projectId?: string | null;
}

export interface SourceChannelRow {
  id: string;
  space_id: string;
  source_connection_id: string;
  source_name?: string;
  created_by_user_id: string;
  name: string;
  channel_type: string;
  endpoint_url: string | null;
  query_json: unknown;
  provider_query_json: unknown;
  query_fingerprint: string;
  status: string;
  fetch_frequency: string;
  schedule_rule_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  provider_key?: string;
  provider_display_name?: string;
  connector_key?: string;
  connector_mapping_id?: string;
  connection_status?: string;
  capture_policy?: string;
  scan_status?: string | null;
  scan_metadata_json?: unknown;
  scan_next_run_at?: unknown;
  scan_last_run_at?: unknown;
}

export class SourceChannelService {
  private readonly catalog: SourceProviderCatalogService;
  private readonly compiler = new SourceChannelQueryCompiler();

  constructor(private readonly db: Queryable, private readonly config: ServerConfig) {
    this.catalog = new SourceProviderCatalogService(db);
  }

  async list(identity: SpaceUserIdentity, filters: { status?: string | null; providerKey?: string | null }) {
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = ["ch.space_id = $1", "ch.created_by_user_id = $2"];
    if (filters.status) { params.push(filters.status); clauses.push(`ch.status = $${params.length}`); }
    if (filters.providerKey) { params.push(filters.providerKey); clauses.push(`p.provider_key = $${params.length}`); }
    const result = await this.db.query<SourceChannelRow>(
      `${this.selectSql()} WHERE ${clauses.join(" AND ")} ORDER BY ch.updated_at DESC, ch.id DESC`,
      params,
    );
    return result.rows.map((row) => this.channelOut(row));
  }

  /**
   * Return canonical channel DTOs for a trusted project/workflow response.
   * Project bindings can reference channels created by another member, so this
   * intentionally scopes by space and exact ids rather than the user-owned
   * listing above.
   */
  async listForSpaceByIds(identity: SpaceUserIdentity, channelIds: string[]) {
    const ids = [...new Set(channelIds.filter((id) => id.trim().length > 0))];
    if (ids.length === 0) return [];
    const result = await this.db.query<SourceChannelRow>(
      `${this.selectSql()}
        WHERE ch.space_id=$1 AND ch.id=ANY($2::text[])
        ORDER BY array_position($2::text[], ch.id)`,
      [identity.spaceId, ids],
    );
    return result.rows.map((row) => this.channelOut(row));
  }

  async get(identity: SpaceUserIdentity, channelId: string) {
    const result = await this.db.query<SourceChannelRow>(
      `${this.selectSql()} WHERE ch.space_id = $1 AND ch.id = $2 AND ch.created_by_user_id = $3 LIMIT 1`,
      [identity.spaceId, channelId, identity.userId],
    );
    return result.rows[0] ? this.channelOut(result.rows[0]) : null;
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const providerKey = requiredString(body.provider_key, "provider_key");
    const provider = await this.catalog.resolve(providerKey);
    const credentialId = optionalString(body.credential_id);
    if (credentialId) {
      await new CustomSourceCredentialService(this.db, this.config).requireOwnCredential(identity, credentialId);
    }
    const query = objectValue(body.query);
    const input = {
      ...query,
      endpoint_url: optionalString(body.endpoint_url) ?? optionalString(query.endpoint_url),
      query,
    };
    const compiled = this.compiler.compile(provider.connector_key, input);
    const fingerprint = this.compiler.fingerprint({ providerKey, connectorKey: provider.connector_key, compiled });
    const sourceName = optionalString(body.source_name) ?? provider.provider_display_name;
    const name = optionalString(body.name) ?? this.defaultName(providerKey, compiled.providerQuery);
    const frequency = optionalString(body.fetch_frequency) ?? "daily";
    if (!["manual", "hourly", "daily", "weekly"].includes(frequency)) {
      throw new HttpError(422, "fetch_frequency must be manual, hourly, daily, or weekly");
    }
    const status = body.status === "paused" ? "paused" : "active";
    const schedule = resolveChannelSchedule(body, frequency, status);
    const existing = body._force_create === true
      ? { rows: [] as SourceChannelRow[] }
      : await this.db.query<SourceChannelRow>(
      `${this.selectSql()} WHERE ch.space_id = $1 AND ch.created_by_user_id = $2 AND ch.query_fingerprint = $3 AND ch.status <> 'archived' LIMIT 1`,
      [identity.spaceId, identity.userId, fingerprint],
    );
    if (existing.rows[0]) return this.channelOut(existing.rows[0]);

    const now = new Date().toISOString();
    const governance = normalizeSourceConnectionCreateGovernance(identity, {
      ...body,
      connector_type: provider.connector_type,
      policy: body.policy ?? {},
      consent: body.consent ?? {},
      capture_policy: body.capture_policy ?? "reference_only",
    });
    const connection = await this.ensureConnection(identity, provider, sourceName, governance, body);
    const channelResult = await this.db.query<SourceChannelRow>(
      `INSERT INTO source_channels (
         id, space_id, source_connection_id, created_by_user_id, name, channel_type,
         endpoint_url, query_json, provider_query_json, query_fingerprint, status,
         fetch_frequency, schedule_rule_json, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12,$13::jsonb,$14,$14)
       RETURNING *`,
      [
        randomUUID(), identity.spaceId, connection.id, identity.userId, name.slice(0, 512),
        channelType(provider.connector_key), compiled.endpointUrl,
        JSON.stringify(compiled.query), JSON.stringify(compiled.providerQuery), fingerprint,
        status, frequency, JSON.stringify(schedule.rule), now,
      ],
    );
    const channel = channelResult.rows[0]!;
    await this.db.query(
      `INSERT INTO source_channel_user_subscriptions (
         id, space_id, source_channel_id, user_id, status, library_enabled, digest_enabled, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,'subscribed',true,true,$5,$5)
       ON CONFLICT (space_id, source_channel_id, user_id) DO UPDATE SET status='subscribed', updated_at=EXCLUDED.updated_at`,
      [randomUUID(), identity.spaceId, channel.id, identity.userId, now],
    );
    await upsertSourceChannelScanTask(this.db, {
      channel: { id: channel.id, space_id: identity.spaceId, owner_user_id: identity.userId, status, fetch_frequency: frequency },
      nextRunAt: schedule.nextRunAt,
      updatedAt: now,
    });
    return this.channelOut({ ...channel, source_name: sourceName, provider_key: provider.provider_key, provider_display_name: provider.provider_display_name, connector_key: provider.connector_key, connector_mapping_id: provider.mapping_id, connection_status: connection.status, capture_policy: governance.capturePolicy });
  }

  async proposeActivation(identity: SpaceUserIdentity, body: Record<string, unknown>, actor: SourceChannelProposalActor = {}) {
    const channel = await this.create(identity, { ...body, status: "paused", _initial_status: "paused" });
    const channelId = requiredString(channel.id, "source_channel_id");
    const existing = actor.runId && actor.idempotencyKey
      ? await this.db.query<{ id: string; status: string }>(
        `SELECT id, status FROM proposals
          WHERE space_id=$1 AND created_by_run_id=$2
            AND proposal_type='source_channel_activation'
            AND action_idempotency_key=$3`,
        [identity.spaceId, actor.runId, actor.idempotencyKey],
      )
      : { rows: [] as Array<{ id: string; status: string }> };
    if (existing.rows[0]) {
      return { channel, proposal: existing.rows[0], auto_applied: existing.rows[0].status === "accepted" };
    }
    const proposal = await insertProposalRow(this.db, {
      spaceId: identity.spaceId,
      proposalType: "source_channel_activation",
      title: `Activate Source Channel: ${String(channel.name ?? "channel")}`,
      payload: {
        proposal_type: "source_channel_activation",
        action_id: "source.channel.propose_activation",
        source_channel_id: channelId,
        draft_updated_at: requiredString(channel.updated_at, "draft_updated_at"),
        ...(actor.idempotencyKey ? { idempotency_key: actor.idempotencyKey } : {}),
      },
      rationale: "Activate a reviewed Source Channel and its underlying governed connection.",
      createdByUserId: actor.agentId ? null : identity.userId,
      createdByAgentId: actor.agentId ?? null,
      createdByRunId: actor.runId ?? null,
      actionIdempotencyKey: actor.idempotencyKey ?? null,
      projectId: actor.projectId ?? null,
      visibility: "space_shared",
      riskLevel: "medium",
      requiredApproverRole: "owner",
    });
    const autoApplied = actor.agentId
      ? await PgProposalApplyService.fromConfig(this.config).acceptAgentProposalIfGranted(proposal.id, {
        actionId: "source.channel.propose_activation",
        resourceKind: "source_channel",
        resourceId: channelId,
      })
      : null;
    return { channel, proposal: autoApplied?.proposal ?? proposal, auto_applied: Boolean(autoApplied) };
  }

  async update(identity: SpaceUserIdentity, channelId: string, body: Record<string, unknown>) {
    const current = await this.getRaw(identity, channelId);
    if (!current) throw new HttpError(404, "Source channel not found");
    const frequency = optionalString(body.fetch_frequency) ?? current.fetch_frequency;
    if (!["manual", "hourly", "daily", "weekly"].includes(frequency)) throw new HttpError(422, "Invalid fetch_frequency");
    const status = optionalString(body.status) ?? current.status;
    if (!["active", "paused", "archived"].includes(status)) throw new HttpError(422, "Invalid channel status");
    const schedule = resolveChannelSchedule(body, frequency, status, current.schedule_rule_json);
    let queryJson = current.query_json;
    let providerQueryJson = current.provider_query_json;
    let endpointUrl = current.endpoint_url;
    let fingerprint = current.query_fingerprint;
    if (body.query !== undefined || body.endpoint_url !== undefined) {
      if (!current.connector_key || !current.provider_key) throw new HttpError(409, "Source channel provider mapping is unavailable");
      const query = objectValue(body.query ?? current.query_json);
      const compiled = this.compiler.compile(current.connector_key, {
        ...query,
        endpoint_url: optionalString(body.endpoint_url) ?? current.endpoint_url ?? optionalString(query.endpoint_url),
        query,
      });
      queryJson = compiled.query;
      providerQueryJson = compiled.providerQuery;
      endpointUrl = compiled.endpointUrl;
      fingerprint = this.compiler.fingerprint({ providerKey: current.provider_key, connectorKey: current.connector_key, compiled });
    }
    const result = await this.db.query<SourceChannelRow>(
      `UPDATE source_channels SET name=COALESCE($3,name), endpoint_url=$4, query_json=$5::jsonb, provider_query_json=$6::jsonb, query_fingerprint=$7, status=$8, fetch_frequency=$9, schedule_rule_json=$10::jsonb, updated_at=$11
        WHERE space_id=$1 AND id=$2 RETURNING *`,
      [identity.spaceId, channelId, optionalString(body.name), endpointUrl, JSON.stringify(queryJson), JSON.stringify(providerQueryJson), fingerprint, status, frequency, JSON.stringify(schedule.rule), new Date().toISOString()],
    );
    const row = result.rows[0]!;
    const sourceName = optionalString(body.source_name);
    if (sourceName) {
      await this.db.query(
        `UPDATE source_connections SET name=$3, updated_at=$4
           WHERE space_id=$1 AND id=(SELECT source_connection_id FROM source_channels WHERE space_id=$1 AND id=$2)`,
        [identity.spaceId, channelId, sourceName, new Date().toISOString()],
      );
    }
    await upsertSourceChannelScanTask(this.db, { channel: { id: row.id, space_id: row.space_id, owner_user_id: identity.userId, status: row.status, fetch_frequency: row.fetch_frequency }, nextRunAt: schedule.nextRunAt, updatedAt: row.updated_at as string });
    return this.get(identity, channelId);
  }

  async scan(identity: SpaceUserIdentity, channelId: string) {
    const channel = await this.getRaw(identity, channelId);
    if (!channel) throw new HttpError(404, "Source channel not found");
    const result = await this.db.query(
      `INSERT INTO extraction_jobs (id, space_id, connection_id, source_item_id, job_type, status, metadata_json, created_at)
       VALUES ($1,$2,$3,NULL,'connection_scan','pending',$4::jsonb,$5)
       RETURNING id, space_id, connection_id, job_type, status, metadata_json, created_at`,
      [randomUUID(), identity.spaceId, channel.source_connection_id, JSON.stringify({ source_channel_id: channelId, created_by: "manual_scan" }), new Date().toISOString()],
    );
    return result.rows[0];
  }

  private async ensureConnection(identity: SpaceUserIdentity, provider: ResolvedSourceProviderConnector, name: string, governance: ReturnType<typeof normalizeSourceConnectionCreateGovernance>, body: Record<string, unknown>) {
    const existing = body._force_create === true
      ? { rows: [] as Array<{ id: string; status: string }> }
      : await this.db.query<{ id: string; status: string }>(
      `SELECT id, status FROM source_connections
        WHERE space_id=$1 AND owner_user_id=$2 AND provider_connector_id=$3
          AND deleted_at IS NULL AND status <> 'archived'
        ORDER BY updated_at DESC LIMIT 1`,
      [identity.spaceId, identity.userId, provider.mapping_id],
    );
    if (existing.rows[0]) return existing.rows[0];
    const now = new Date().toISOString();
    const result = await this.db.query<{ id: string; status: string }>(
      `INSERT INTO source_connections (
         id, space_id, provider_connector_id, owner_user_id, credential_id, visibility, access_level, name,
         status, capture_policy, trust_level, topic_hints_json, consent_json, policy_json, config_json,
         created_at, updated_at
       ) VALUES ($1,$2,$3,$4,$5,'private','full',$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12::jsonb,$13::jsonb,$14,$14)
       ON CONFLICT (space_id, owner_user_id, provider_connector_id, name)
         WHERE deleted_at IS NULL AND status <> 'archived'
       DO NOTHING
       RETURNING id, status`,
      [
        randomUUID(), identity.spaceId, provider.mapping_id, identity.userId, optionalString(body.credential_id), name,
        body._initial_status === "paused" ? "paused" : "active", governance.capturePolicy, governance.trustLevel,
        JSON.stringify(Array.isArray(body.topic_hints) ? body.topic_hints : []), JSON.stringify(governance.consent), JSON.stringify(governance.policy), JSON.stringify(objectValue(body.transport_config ?? body.config)), now,
      ],
    );
    if (result.rows[0]) return result.rows[0];
    const concurrent = await this.db.query<{ id: string; status: string }>(
      `SELECT id, status FROM source_connections
        WHERE space_id=$1 AND owner_user_id=$2 AND provider_connector_id=$3
          AND deleted_at IS NULL AND status <> 'archived'
        ORDER BY updated_at DESC LIMIT 1`,
      [identity.spaceId, identity.userId, provider.mapping_id],
    );
    if (!concurrent.rows[0]) throw new HttpError(409, "Source connection could not be created");
    return concurrent.rows[0];
  }

  private async getRaw(identity: SpaceUserIdentity, channelId: string) {
    const result = await this.db.query<SourceChannelRow>(`${this.selectSql()} WHERE ch.space_id=$1 AND ch.id=$2 AND ch.created_by_user_id=$3 LIMIT 1`, [identity.spaceId, channelId, identity.userId]);
    return result.rows[0] ?? null;
  }

  private selectSql() {
    return `SELECT ch.*, p.provider_key, p.display_name AS provider_display_name, c.connector_key,
                   spc.id AS connector_mapping_id, sc.name AS source_name, sc.status AS connection_status, sc.capture_policy,
                   st.status AS scan_status, st.metadata_json AS scan_metadata_json,
                   st.next_run_at AS scan_next_run_at, st.last_run_at AS scan_last_run_at
              FROM source_channels ch
              JOIN source_connections sc ON sc.id=ch.source_connection_id
              JOIN source_provider_connectors spc ON spc.id=sc.provider_connector_id
              JOIN source_providers p ON p.id=spc.provider_id
              JOIN source_connectors c ON c.id=spc.connector_id
              LEFT JOIN scheduler_tasks st
                ON st.task_type='source_channel_scan' AND st.task_key=ch.id AND st.space_id=ch.space_id`;
  }

  private channelOut(row: SourceChannelRow) {
    return {
      id: row.id,
      space_id: row.space_id,
      source_connection_id: row.source_connection_id,
      source_name: row.source_name ?? row.provider_display_name ?? "Source",
      name: row.name,
      channel_type: row.channel_type,
      endpoint_url: row.endpoint_url,
      query: row.query_json ?? {},
      provider_query: row.provider_query_json ?? {},
      query_fingerprint: row.query_fingerprint,
      status: row.status,
      fetch_frequency: row.fetch_frequency,
      schedule_rule: row.schedule_rule_json ?? null,
      provider: { key: row.provider_key ?? null, display_name: row.provider_display_name ?? null },
      connection_status: row.connection_status ?? null,
      capture_policy: row.capture_policy ?? null,
      scan_state: {
        status: row.scan_status ?? null,
        cursor: objectValue(objectValue(row.scan_metadata_json).cursor),
        watermark: objectValue(objectValue(row.scan_metadata_json).watermark),
        next_run_at: row.scan_next_run_at ?? null,
        last_run_at: row.scan_last_run_at ?? null,
      },
      created_by_user_id: row.created_by_user_id,
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }

  private defaultName(providerKey: string, query: Record<string, unknown>) {
    if (providerKey === "arxiv") {
      if (query.mode === "all") return "All arXiv papers";
      return String(query.search_query ?? query.categories ?? "search").slice(0, 180);
    }
    if (providerKey === "openalex") return String(query.search ?? "OpenAlex search").slice(0, 180);
    if (providerKey === "semantic_scholar") return String(query.query ?? "Semantic Scholar search").slice(0, 180);
    if (providerKey === "web_search") return String(query.q ?? "Web search").slice(0, 180);
    return "channel";
  }
}

function channelType(connectorKey: string): string {
  if (["arxiv_api", "openalex_api", "semantic_scholar_api", "brave_web_search_api"].includes(connectorKey)) return "search";
  if (connectorKey === "rss" || connectorKey === "atom") return "feed";
  if (connectorKey === "web_page") return "web_page";
  return "custom_source";
}

function resolveChannelSchedule(body: Record<string, unknown>, frequency: string, status: string, existingRule?: unknown): { nextRunAt: string | null; rule: SourceScheduleRule | null } {
  if (frequency === "manual" || status !== "active") return { nextRunAt: null, rule: null };
  const raw = body.schedule_rule && typeof body.schedule_rule === "object" ? body.schedule_rule as Record<string, unknown> : null;
  const now = new Date();
  if (raw) {
    const rule = normalizeRule(raw, frequency);
    return { nextRunAt: computeNextRunAtFromScheduleRule(rule, now), rule };
  }
  if (existingRule && typeof existingRule === "object") {
    const rule = normalizeRule(existingRule as Record<string, unknown>, frequency);
    return { nextRunAt: computeNextRunAtFromScheduleRule(rule, now), rule };
  }
  const rule = frequency === "hourly"
    ? { frequency: "hourly", minute: 0 } as const
    : frequency === "weekly"
      ? { frequency: "weekly", weekday: 1, hour: 3, minute: 0 } as const
      : { frequency: "daily", hour: 3, minute: 0 } as const;
  return { nextRunAt: computeNextRunAtFromScheduleRule(rule, now), rule };
}

function normalizeRule(raw: Record<string, unknown>, frequency: string): SourceScheduleRule {
  if (raw.frequency !== frequency) throw new HttpError(422, "schedule_rule.frequency must match fetch_frequency");
  const number = (key: string, min: number, max: number) => {
    const value = Number(raw[key]);
    if (!Number.isInteger(value) || value < min || value > max) throw new HttpError(422, `schedule_rule.${key} is invalid`);
    return value;
  };
  if (frequency === "hourly") return { frequency: "hourly", minute: number("minute", 0, 59) };
  if (frequency === "daily") return { frequency: "daily", hour: number("hour", 0, 23), minute: number("minute", 0, 59) };
  return { frequency: "weekly", weekday: number("weekday", 1, 7), hour: number("hour", 0, 23), minute: number("minute", 0, 59) };
}
