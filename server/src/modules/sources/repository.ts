import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import type { Queryable } from "../routeUtils/common";
import { canAccessProject } from "../memory/projectAccess";
import { assertProjectWriter } from "../projects/access";
import {
  HttpError,
  countFromRow,
  dateIso,
  numberValue,
  objectValue,
  optionalObject,
  optionalString,
  page,
  requiredString,
  toDbDate,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { SourceExtractionWorker } from "./extractionWorker";
import { CustomSourceCredentialService } from "./customSources/customSourceCredentialService";
import { runCustomSourceHandlerScanJob } from "./customSources/customSourceScanWorker";
import { RECIPE_SCAN_JOB_IMPLEMENTATION, runSourceRecipeScanJob } from "./sourceRecipes/recipeScanWorker";
import { insertProposalRow } from "../proposals/reviewPackets";
import {
  contentOwnerFilterSql,
  contentReadSql,
  contentVisibilityFilterSql,
} from "../access/contentAccessSql";
import { contentDecisionFromDb } from "../access/contentAccessQuery";
import { inheritContentAccessGrants } from "../access/contentAccessInheritance";
import {
  buildSummary,
  connectionOut,
  connectorOut,
  evidenceLinkOut,
  evidenceOut,
  itemOut,
  jobOut,
  normalizeUrl,
  projectSourceBindingOut,
  projectSourceItemOut,
  type ProjectSourceItemOutRow,
  sha256,
  sourceDomain,
  stringList,
} from "./sourceRepositoryMappers";
import {
  CONNECTION_COLUMNS,
  CONNECTOR_COLUMNS,
  EVIDENCE_COLUMNS,
  EVIDENCE_LINK_COLUMNS,
  ITEM_COLUMNS,
  JOB_COLUMNS,
  PROJECT_SOURCE_BINDING_COLUMNS,
  connectionColumnsWithConnectorForAlias,
  evidenceColumnsForAlias,
  itemColumnsForAlias,
  type EvidenceLinkRow,
  type EvidenceRow,
  type ExtractionJobRow,
  type ProjectSourceBindingRow,
  type SourceItemRow,
  type SourceConnectionRow,
  type SourceConnectorRow,
} from "./sourceRepositoryRows";
import {
  getSourceConnectionScanTask,
  sourceConnectionWithSchedule,
  upsertSourceConnectionScanTask,
} from "./sourceConnectionScheduler";
import { resolveRequestedSourceSchedule } from "./sourceScheduleInput";
import {
  enforceSourceDerivedImportTarget,
  enforceSourceRetentionPolicy,
  normalizeSourceConnectionCreateGovernance,
  normalizeSourceConnectionReadGovernance,
  normalizeSourceConnectionUpdateGovernance,
} from "./sourceConsent";
import {
  reindexExtractedEvidenceAndParentForRetrieval,
  reindexSourceItemAndEvidenceForRetrieval,
} from "./retrievalIndexing";
import {
  materializeProjectSourceItemLinks,
  recomputeProjectSourceBindingLinks,
} from "./evidenceProjectLinker";
import { sourceItemConnectionGateClause, sourceItemReadableClause } from "./sourceItemAccess";

const EVIDENCE_LINK_TYPES = new Set([
  "supports",
  "contradicts",
  "derived_from",
  "mentions",
  "context_candidate",
  "used_in_context",
]);
const EVIDENCE_STATUSES = new Set(["candidate", "active", "rejected", "archived"]);
const SOURCE_CONNECTION_VISIBILITIES = new Set(["private", "space_shared"]);
const SOURCE_CONNECTION_SUBSCRIPTION_STATUSES = new Set(["subscribed", "pending", "dismissed", "muted"]);
const SOURCE_ITEM_LIBRARY_STATUSES = new Set(["open", "new", "triaged", "selected", "ignored", "archived"]);
const SOURCE_ITEM_READ_STATUSES = new Set(["unread", "skimmed", "read", "discussed"]);
const PROJECT_SOURCE_DELIVERY_SCOPES = new Set(["project_members", "source_subscribers"]);

const CONNECTION_SUBSCRIPTION_SELECT = [
  "scus.status AS subscription_status",
  "scus.library_enabled",
  "scus.digest_enabled",
  "scus.recommended_by_user_id",
  "scus.recommendation_message",
  "scus.last_notified_at",
].join(", ");

function itemColumnsWithCurrentUserState(itemAlias: string): string {
  return [
    itemColumnsForAlias(itemAlias),
    "suis.library_status",
    "suis.read_status",
    "suis.first_opened_at",
    "suis.last_opened_at",
    "suis.progress_json",
  ].join(", ");
}

function sourceConnectionVisibility(body: Record<string, unknown>, connectorKey: string): string {
  const requested = optionalString(body.visibility);
  if (requested) {
    if (!SOURCE_CONNECTION_VISIBILITIES.has(requested)) {
      throw new HttpError(422, "visibility must be one of: private, space_shared");
    }
    return requested;
  }
  if (optionalString(body.credential_id) || connectorKey === "custom_source") return "private";
  return "space_shared";
}

function isManualUrlItem(item: SourceItemRow): boolean {
  return item.item_type === "external_url" && objectValue(item.metadata_json).created_by === "manual_url";
}

const URI_EXPR = "lower(coalesce(source_uri, canonical_uri, ''))";
const DOMAIN_EXPR = "lower(coalesce(source_domain, ''))";
const SOURCE_OBJECT_TYPE_EXPR = "lower(coalesce(source_object_type, ''))";
const CONTENT_TYPE_EXPR = "lower(coalesce(metadata_json->>'content_type', metadata_json->>'mime_type', metadata_json->>'mime', ''))";
const EXPLICIT_LIBRARY_TYPE_EXPR = "lower(coalesce(metadata_json->>'library_type', metadata_json->>'content_kind', metadata_json->>'media_type', ''))";

function metadataTypeIn(values: string[]): string {
  return `${EXPLICIT_LIBRARY_TYPE_EXPR} IN (${values.map((value) => `'${value}'`).join(", ")})`;
}

function libraryPdfClause(): string {
  return `(${metadataTypeIn(["pdf"])} OR ${CONTENT_TYPE_EXPR} = 'application/pdf' OR ${URI_EXPR} ~ '\\.pdf($|[?#])')`;
}

function libraryEmailClause(): string {
  return `(${metadataTypeIn(["email", "mail", "message"])} OR ${SOURCE_OBJECT_TYPE_EXPR} IN ('email', 'mail', 'mail_message', 'message') OR lower(coalesce(metadata_json->>'connector_kind', metadata_json->>'source_type', '')) IN ('email', 'gmail', 'imap'))`;
}

function libraryVideoClause(): string {
  return `(${metadataTypeIn(["video"])} OR ${CONTENT_TYPE_EXPR} LIKE 'video/%' OR ${URI_EXPR} ~ '\\.(mp4|mov|m4v|webm|mkv)($|[?#])' OR ${DOMAIN_EXPR} IN ('youtube.com', 'www.youtube.com', 'youtu.be', 'vimeo.com', 'www.vimeo.com') OR ${DOMAIN_EXPR} LIKE '%.youtube.com')`;
}

function libraryPodcastClause(): string {
  return `(${metadataTypeIn(["audio", "podcast"])} OR ${CONTENT_TYPE_EXPR} LIKE 'audio/%' OR ${URI_EXPR} ~ '\\.(mp3|m4a|aac|ogg|wav|flac)($|[?#])' OR ${DOMAIN_EXPR} IN ('podcasts.apple.com', 'overcast.fm', 'open.spotify.com', 'spotify.com'))`;
}

function libraryArticleClause(): string {
  const nonArticle = [libraryPdfClause(), libraryEmailClause(), libraryVideoClause(), libraryPodcastClause()].join(" OR ");
  return `((${metadataTypeIn(["article", "text", "webpage", "html"])} OR item_type IN ('feed_entry', 'external_url', 'document') OR ${CONTENT_TYPE_EXPR} LIKE 'text/%') AND NOT (${nonArticle}))`;
}

function libraryTypeClause(libraryType: string): string | null {
  switch (libraryType) {
    case "article":
      return libraryArticleClause();
    case "email":
      return libraryEmailClause();
    case "video":
      return libraryVideoClause();
    case "podcast":
    case "audio":
      return libraryPodcastClause();
    case "pdf":
      return libraryPdfClause();
    default:
      return null;
  }
}

function itemRetentionPolicy(item: SourceItemRow): "metadata_only" | "summary_only" | "full_text" | "full_snapshot" {
  if (
    item.retention_policy === "summary_only" ||
    item.retention_policy === "full_text" ||
    item.retention_policy === "full_snapshot"
  ) {
    return item.retention_policy;
  }
  return "metadata_only";
}

export class PgSourcesRepository {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  async listConnectors() {
    const rows = await this.db.query<SourceConnectorRow>(
      `SELECT ${CONNECTOR_COLUMNS} FROM source_connectors WHERE status = 'active' ORDER BY display_name, connector_key`,
    );
    return rows.rows.map(connectorOut);
  }

  async listConnections(identity: SpaceUserIdentity, filters: { view: string | null; status: string | null; limit: number; offset: number }) {
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = ["sc.space_id = $1", "sc.deleted_at IS NULL"];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`sc.status = $${params.length}`);
    }
    const view = filters.view ?? "subscribed";
    if (view === "subscribed") {
      clauses.push("scus.status = 'subscribed'");
    } else if (view === "pending") {
      clauses.push("scus.status = 'pending'");
    } else if (view === "owned") {
      clauses.push(contentOwnerFilterSql("source_connection", "sc", "$2"));
    } else if (view === "available") {
      clauses.push(contentVisibilityFilterSql("sc", ["space_shared"]));
      clauses.push(`NOT (${contentOwnerFilterSql("source_connection", "sc", "$2")})`);
      clauses.push("(scus.status IS NULL OR scus.status IN ('pending', 'dismissed'))");
    } else if (view === "manageable") {
      clauses.push(`(
        ${contentOwnerFilterSql("source_connection", "sc", "$2")}
        OR EXISTS (
          SELECT 1 FROM space_memberships sm
           WHERE sm.space_id = sc.space_id
             AND sm.user_id = $2
             AND sm.status = 'active'
             AND sm.role IN ('owner', 'admin')
        )
      )`);
    } else {
      throw new HttpError(422, "view must be one of: subscribed, pending, owned, available, manageable");
    }
    if (view !== "manageable") clauses.push(contentReadSql("source_connection", "sc", "$2"));
    const where = `WHERE ${clauses.join(" AND ")}`;
    const join = `LEFT JOIN source_connection_user_subscriptions scus
                    ON scus.space_id = sc.space_id
                   AND scus.source_connection_id = sc.id
                   AND scus.user_id = $2`;
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM source_connections sc ${join} ${where}`,
      params,
    );
    const rows = await this.db.query<SourceConnectionRow>(
      `SELECT ${connectionColumnsWithConnectorForAlias("sc", "c")}, ${CONNECTION_SUBSCRIPTION_SELECT}
         FROM source_connections sc
         JOIN source_connectors c ON c.id = sc.connector_id
         ${join}
       ${where}
       ORDER BY sc.updated_at DESC, sc.id DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    const rowsWithSchedule = await this.withConnectionSchedules(rows.rows);
    return page(rowsWithSchedule.map(connectionOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createConnection(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
    options: { allowCustomSourceConnector?: boolean } = {},
  ) {
    const connectorKey = requiredString(body.connector_key, "connector_key");
    if (connectorKey === "custom_source" && !options.allowCustomSourceConnector) {
      throw new HttpError(422, "Custom Source connections must be created through the Custom Source draft flow");
    }
    const connector = await this.db.query<{ id: string }>(
      `SELECT id FROM source_connectors WHERE connector_key = $1 AND status = 'active'`,
      [connectorKey],
    );
    if (!connector.rows[0]) throw new HttpError(404, "Source connector not found");
    const now = new Date().toISOString();
    const governance = normalizeSourceConnectionCreateGovernance(identity, body);
    const visibility = sourceConnectionVisibility(body, connectorKey);
    const fetchFrequency = optionalString(body.fetch_frequency) ?? "manual";
    const schedule = resolveRequestedSourceSchedule({
      body,
      status: "active",
      fetchFrequency,
    });
    const result = await this.db.query<SourceConnectionRow>(
      `INSERT INTO source_connections (
         id, space_id, connector_id, owner_user_id, credential_id, visibility, name, endpoint_url,
         status, fetch_frequency, capture_policy, trust_level, topic_hints_json,
         consent_json, policy_json, config_json, schedule_rule_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7, $8,
         'active', $9, $10, $11, $12::jsonb,
         $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb, $17, $17
       ) RETURNING ${CONNECTION_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        connector.rows[0].id,
        identity.userId,
        optionalString(body.credential_id),
        visibility,
        requiredString(body.name, "name"),
        optionalString(body.endpoint_url),
        fetchFrequency,
        governance.capturePolicy,
        governance.trustLevel,
        JSON.stringify(Array.isArray(body.topic_hints) ? body.topic_hints : null),
        JSON.stringify(governance.consent),
        JSON.stringify(governance.policy),
        JSON.stringify(objectValue(body.config)),
        JSON.stringify(schedule.scheduleRule),
        now,
      ],
    );
    const row = result.rows[0]!;
    await this.upsertConnectionSubscription({
      spaceId: identity.spaceId,
      connectionId: row.id,
      userId: identity.userId,
      status: "subscribed",
      libraryEnabled: true,
      digestEnabled: true,
      recommendedByUserId: null,
      recommendationMessage: null,
      notify: false,
      now,
    });
    await this.createDefaultPendingSubscriptions(identity, row, now);
    const task = await upsertSourceConnectionScanTask(this.db, {
      connection: row,
      nextRunAt: schedule.nextRunAt,
      updatedAt: now,
    });
    const out = await this.getConnection(identity, sourceConnectionWithSchedule(row, task).id);
    if (!out) throw new Error("Created source connection could not be reloaded");
    return out;
  }

  async getConnection(identity: SpaceUserIdentity, connectionId: string) {
    const row = await this.getConnectionRow(identity, connectionId);
    if (!row) return null;
    if (!(await this.canViewConnectionMetadata(identity, row))) return null;
    return connectionOut(await this.withConnectionSchedule(row));
  }

  async updateConnection(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    const existing = await this.getConnectionRow(identity, connectionId);
    if (!existing) throw new HttpError(404, "Source connection not found");
    if (body.visibility !== undefined || body.access_level !== undefined || body.grants !== undefined) {
      throw new HttpError(422, "Use the content-access API to update Source permissions");
    }
    if (Object.hasOwn(body, "credential_id") && body.credential_id != null) {
      if (existing.handler_kind !== "generated_custom") {
        throw new HttpError(422, "credential_id can only be set on a Custom Source connection");
      }
      // Mirrors createDraft's validation — without this, a generic
      // source.connection_manage caller (not necessarily a space admin)
      // could attach an arbitrary/cross-space/wrong-type credentials row id
      // that a Custom Source handler version would later carry into its
      // policy envelope's credential_ref.
      await new CustomSourceCredentialService(this.db, this.config).requireOwnCredential(
        identity,
        requiredString(body.credential_id, "credential_id"),
      );
    }
    const now = new Date().toISOString();
    const requestedStatus = optionalString(body.status) ?? existing.status;
    const requestedFrequency = optionalString(body.fetch_frequency) ?? existing.fetch_frequency;
    const schedule = resolveRequestedSourceSchedule({
      body,
      status: requestedStatus,
      fetchFrequency: requestedFrequency,
      existingNextCheckAt: existing.next_check_at,
      existingScheduleRule: existing.schedule_rule_json,
      now: new Date(now),
    });
    const governance = normalizeSourceConnectionUpdateGovernance(identity, existing, body);
    const result = await this.db.query<SourceConnectionRow>(
      `UPDATE source_connections SET
         name = COALESCE($3, name),
         status = COALESCE($4::varchar(32), status),
         credential_id = CASE WHEN $5::boolean THEN $6 ELSE credential_id END,
         fetch_frequency = COALESCE($7, fetch_frequency),
         capture_policy = COALESCE($8, capture_policy),
         trust_level = COALESCE($9, trust_level),
         topic_hints_json = CASE WHEN $10::boolean THEN $11::jsonb ELSE topic_hints_json END,
         consent_json = CASE WHEN $12::boolean THEN $13::jsonb ELSE consent_json END,
         policy_json = CASE WHEN $14::boolean THEN $15::jsonb ELSE policy_json END,
         config_json = CASE WHEN $16::boolean THEN $17::jsonb ELSE config_json END,
         schedule_rule_json = $18::jsonb,
         deleted_at = CASE WHEN $4::varchar(32) = 'archived' THEN $19::timestamptz ELSE deleted_at END,
         updated_at = $19
       WHERE space_id = $1 AND id = $2
       RETURNING ${CONNECTION_COLUMNS}`,
      [
        identity.spaceId,
        connectionId,
        optionalString(body.name),
        optionalString(body.status),
        Object.hasOwn(body, "credential_id"),
        optionalString(body.credential_id),
        optionalString(body.fetch_frequency),
        governance.capturePolicy,
        governance.trustLevel,
        Object.hasOwn(body, "topic_hints"),
        JSON.stringify(Array.isArray(body.topic_hints) ? body.topic_hints : null),
        governance.consent !== null,
        JSON.stringify(governance.consent),
        governance.policy !== null,
        JSON.stringify(governance.policy),
        Object.hasOwn(body, "config"),
        JSON.stringify(optionalObject(body.config)),
        JSON.stringify(schedule.scheduleRule),
        now,
      ],
    );
    const row = result.rows[0]!;
    await upsertSourceConnectionScanTask(this.db, {
      connection: row,
      nextRunAt: schedule.nextRunAt,
      updatedAt: now,
    });
    const out = await this.getConnection(identity, row.id);
    if (!out) throw new Error("Updated source connection could not be reloaded");
    return out;
  }

  async recommendConnection(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    const connection = await this.getConnectionRow(identity, connectionId);
    if (!connection) throw new HttpError(404, "Source connection not found");
    if (!(await this.canViewConnectionMetadata(identity, connection))) {
      throw new HttpError(404, "Source connection not found");
    }
    const targets = await this.resolveRecommendationTargets(identity, body);
    if (!targets.length) throw new HttpError(422, "No recommendation targets");
    const message = optionalString(body.message) ?? optionalString(body.recommendation_message);
    const now = new Date().toISOString();
    let notified = 0;
    for (const userId of targets) {
      if (userId === identity.userId) continue;
      const changed = await this.upsertConnectionSubscription({
        spaceId: identity.spaceId,
        connectionId,
        userId,
        status: "pending",
        libraryEnabled: true,
        digestEnabled: true,
        recommendedByUserId: identity.userId,
        recommendationMessage: message ?? null,
        notify: true,
        now,
      });
      if (!changed) continue;
      await this.upsertSourceRecommendationActivity({
        spaceId: identity.spaceId,
        targetUserId: userId,
        connection,
        recommendedByUserId: identity.userId,
        recommendationMessage: message ?? null,
        now,
      });
      notified += 1;
    }
    return { source_connection_id: connectionId, recommended: notified };
  }

  async updateConnectionSubscription(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    const connection = await this.getConnectionRow(identity, connectionId);
    if (!connection) throw new HttpError(404, "Source connection not found");
    if (!(await this.canViewConnectionMetadata(identity, connection))) throw new HttpError(404, "Source connection not found");
    const action = requiredString(body.action, "action");
    if (!["subscribe", "dismiss", "mute", "unsubscribe"].includes(action)) {
      throw new HttpError(422, "action must be one of: subscribe, dismiss, mute, unsubscribe");
    }
    const now = new Date().toISOString();
    const libraryEnabled = typeof body.library_enabled === "boolean" ? body.library_enabled : action === "unsubscribe" ? false : true;
    const digestEnabled = typeof body.digest_enabled === "boolean" ? body.digest_enabled : action === "unsubscribe" ? false : true;
    const status = action === "subscribe"
      ? "subscribed"
      : action === "dismiss"
        ? "dismissed"
        : action === "mute"
          ? "muted"
          : "dismissed";
    await this.upsertConnectionSubscription({
      spaceId: identity.spaceId,
      connectionId,
      userId: identity.userId,
      status,
      libraryEnabled,
      digestEnabled,
      recommendedByUserId: connection.recommended_by_user_id ?? null,
      recommendationMessage: connection.recommendation_message ?? null,
      notify: false,
      now,
    });
    return this.getConnection(identity, connectionId);
  }

  async scanConnection(identity: SpaceUserIdentity, connectionId: string) {
    const connection = await this.getConnection(identity, connectionId);
    if (!connection) throw new HttpError(404, "Source connection not found");
    if (connection.handler_kind === "generated_custom") {
      if (!connection.active_handler_version_id) {
        throw new HttpError(409, "Custom Source connection has no active handler version");
      }
      return this.createCustomSourceScanJob({
        identity,
        connectionId,
        handlerVersionId: connection.active_handler_version_id,
        metadata: { created_by: "manual_scan", handler_kind: "generated_custom" },
      });
    }
    if (connection.handler_kind === "recipe") {
      if (!connection.active_recipe_version_id) {
        throw new HttpError(409, "Recipe Source connection has no active recipe version");
      }
      return this.createJob({
        identity,
        connectionId,
        sourceItemId: null,
        jobType: "connection_scan",
        metadata: {
          created_by: "manual_scan",
          implementation: RECIPE_SCAN_JOB_IMPLEMENTATION,
          recipe_version_id: connection.active_recipe_version_id,
        },
      });
    }
    return this.createJob({ identity, connectionId, sourceItemId: null, jobType: "connection_scan", metadata: { created_by: "manual_scan" } });
  }

  async listItems(identity: SpaceUserIdentity, filters: {
    libraryStatus: string | null;
    readStatus: string | null;
    contentState: string | null;
    connectionId: string | null;
    itemType: string | null;
    libraryType: string | null;
    sourceDomain: string | null;
    createdAfter: string | null;
    occurredAfter: string | null;
    q: string | null;
    limit: number;
    offset: number;
  }) {
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = ["si.space_id = $1", "si.deleted_at IS NULL", sourceItemReadableClause("si", "$2", true)];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.libraryStatus) {
      if (!SOURCE_ITEM_LIBRARY_STATUSES.has(filters.libraryStatus)) {
        throw new HttpError(422, "library_status must be one of: open, new, triaged, selected, ignored, archived");
      }
      if (filters.libraryStatus === "open") {
        clauses.push("COALESCE(suis.library_status, 'new') NOT IN ('ignored', 'archived')");
      } else {
        clauses.push(`COALESCE(suis.library_status, 'new') = ${add(filters.libraryStatus)}`);
      }
    }
    if (filters.readStatus) {
      if (!SOURCE_ITEM_READ_STATUSES.has(filters.readStatus)) {
        throw new HttpError(422, "read_status must be one of: unread, skimmed, read, discussed");
      }
      clauses.push(`COALESCE(suis.read_status, 'unread') = ${add(filters.readStatus)}`);
    }
    if (filters.contentState) clauses.push(`si.content_state = ${add(filters.contentState)}`);
    if (filters.connectionId) clauses.push(`si.connection_id = ${add(filters.connectionId)}`);
    if (filters.itemType) clauses.push(`si.item_type = ${add(filters.itemType)}`);
    if (filters.libraryType) {
      const clause = libraryTypeClause(filters.libraryType);
      if (!clause) throw new HttpError(400, "Unsupported library_type");
      clauses.push(clause);
    }
    if (filters.sourceDomain) clauses.push(`si.source_domain = ${add(filters.sourceDomain)}`);
    if (filters.createdAfter) clauses.push(`si.created_at >= ${add(filters.createdAfter)}::timestamptz`);
    if (filters.occurredAfter) clauses.push(`si.occurred_at >= ${add(filters.occurredAfter)}::timestamptz`);
    if (filters.q) {
      clauses.push(`(si.title ILIKE ${add(`%${filters.q}%`)} OR si.excerpt ILIKE $${params.length} OR si.source_uri ILIKE $${params.length} OR si.source_domain ILIKE $${params.length})`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const stateJoin = `LEFT JOIN source_item_user_states suis
                         ON suis.space_id = si.space_id
                        AND suis.source_item_id = si.id
                        AND suis.user_id = $2`;
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM source_items si ${stateJoin} ${where}`,
      params,
    );
    const rows = await this.db.query<SourceItemRow>(
      `SELECT ${itemColumnsWithCurrentUserState("si")}
         FROM source_items si
         ${stateJoin}
       ${where}
       ORDER BY si.last_seen_at DESC, si.created_at DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(itemOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async getItem(identity: SpaceUserIdentity, itemId: string) {
    const row = await this.getItemRow(identity, itemId);
    return row ? itemOut(row) : null;
  }

  async createManualUrl(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const url = requiredString(body.url, "url");
    const canonical = normalizeUrl(url);
    const connectionId = optionalString(body.connection_id);
    const connection = connectionId ? await this.getConnectionRow(identity, connectionId) : null;
    if (connectionId && !connection) {
      throw new HttpError(404, "Source connection not found");
    }
    if (connectionId) await this.assertConnectionSubscribed(identity, connectionId, false);
    const retention = body.queue_content === true ? "full_text" : "metadata_only";
    if (connection) enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, retention);
    const existing = await this.db.query<SourceItemRow>(
      `SELECT ${itemColumnsWithCurrentUserState("si")}
         FROM source_items si
         LEFT JOIN source_item_user_states suis
           ON suis.space_id = si.space_id
          AND suis.source_item_id = si.id
          AND suis.user_id = $3
        WHERE si.space_id = $1
          AND si.deleted_at IS NULL
          AND (si.canonical_uri = $2 OR si.source_uri = $2)
          AND ${sourceItemReadableClause("si", "$3", false)}
        LIMIT 1`,
      [identity.spaceId, canonical, identity.userId],
    );
    const now = new Date().toISOString();
    let row = existing.rows[0];
    if (!row) {
      const inserted = await this.db.query<SourceItemRow>(
        `INSERT INTO source_items (
           id, space_id, connection_id, item_type, title, source_uri, canonical_uri,
           source_domain, created_by_user_id, content_state, retention_policy,
           metadata_json, first_seen_at, last_seen_at, created_at, updated_at,
           owner_user_id, visibility, access_level
         ) VALUES (
           $1, $2, $3, 'external_url', $4, $5, $6,
           $7, $8, $9, $10,
           $11::jsonb, $12, $12, $12, $12,
           $13, $14, $15
         ) RETURNING ${ITEM_COLUMNS}`,
        [
          randomUUID(),
          identity.spaceId,
          connectionId,
          optionalString(body.title) ?? canonical,
          url,
          canonical,
          sourceDomain(canonical),
          identity.userId,
          body.queue_content === true ? "content_queued" : "metadata_only",
          retention,
          JSON.stringify({ created_by: "manual_url" }),
          now,
          connection?.owner_user_id ?? identity.userId,
          connection?.visibility ?? "private",
          connection?.access_level ?? "full",
        ],
      );
      row = inserted.rows[0]!;
      if (connection?.visibility === "selected_users") {
        await inheritContentAccessGrants(this.db, {
          spaceId: identity.spaceId,
          sourceResourceType: "source_connection",
          sourceResourceId: connection.id,
          targetResourceType: "source_item",
          targetResourceId: row.id,
          inheritedAt: now,
        });
      }
    }
    if (body.queue_content === true) {
      await this.createJob({ identity, connectionId: row.connection_id, sourceItemId: row.id, jobType: "manual_url", metadata: { url: canonical } });
    }
    await materializeProjectSourceItemLinks(this.db, {
      spaceId: identity.spaceId,
      sourceItemId: row.id,
    });
    await this.reindexItemForRetrieval(identity.spaceId, row.id, "source_manual_url");
    return itemOut(row);
  }

  async itemAction(identity: SpaceUserIdentity, itemId: string, body: Record<string, unknown>) {
    const item = await this.getItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Source item not found");
    const action = requiredString(body.action, "action");
    if (action === "queue_content" || action === "archive_snapshot") {
      const contentState = action === "queue_content" ? "content_queued" : "snapshot_queued";
      const retention = action === "queue_content" ? "full_text" : "full_snapshot";
      const jobType = action === "queue_content" ? "extract_text" : "snapshot";
      await this.enforceItemRetentionPolicy(identity, item, retention);
      await this.db.query(
        `UPDATE source_items SET content_state = $3, retention_policy = $4, updated_at = $5 WHERE space_id = $1 AND id = $2`,
        [identity.spaceId, itemId, contentState, retention, new Date().toISOString()],
      );
      if (!(await this.hasActiveItemJob(identity, item.id, jobType))) {
        await this.createJob({ identity, connectionId: item.connection_id, sourceItemId: item.id, jobType, metadata: { action } });
      }
      return this.getItem(identity, itemId);
    }
    if (action === "mark_selected" || action === "mark_ignored" || action === "read_later" || action === "mark_discussed") {
      const libraryStatus = action === "mark_selected"
        ? "selected"
        : action === "mark_ignored"
          ? "ignored"
          : action === "read_later"
            ? "triaged"
            : null;
      const readStatus = action === "mark_discussed" ? "discussed" : null;
      await this.upsertItemUserState(identity, itemId, {
        libraryStatus,
        readStatus,
        firstOpenedAt: null,
        lastOpenedAt: null,
        progress: null,
      });
      return this.getItem(identity, itemId);
    }
    if (action === "extract_evidence") {
      await this.createEvidence(identity, {
        source_item_id: item.id,
        evidence_type: "excerpt",
        title: item.title,
        content_excerpt: item.excerpt ?? item.title,
        source_uri: item.source_uri,
        trust_level: "normal",
        extraction_method: "manual_action",
        confidence: 0.5,
        status: "candidate",
        metadata: { source: "source_item_action" },
      });
      return this.getItem(identity, itemId);
    }
    throw new HttpError(422, "Unsupported source action");
  }

  async updateItem(identity: SpaceUserIdentity, itemId: string, body: Record<string, unknown>) {
    const item = await this.getItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Source item not found");
    if (!Object.hasOwn(body, "connection_id")) throw new HttpError(422, "connection_id is required");
    if (!isManualUrlItem(item)) {
      throw new HttpError(422, "Only manually saved URL items can change source");
    }

    const connectionId = optionalString(body.connection_id);
    const connection = connectionId ? await this.getConnectionRow(identity, connectionId) : null;
    if (connectionId && !connection) throw new HttpError(404, "Source connection not found");
    if (connectionId) await this.assertConnectionSubscribed(identity, connectionId, false);
    if (connection) enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, itemRetentionPolicy(item));

    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE source_items
          SET connection_id = $3, updated_at = $4
        WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, itemId, connectionId, now],
    );
    await this.db.query(
      `UPDATE source_snapshots
          SET connection_id = $3
        WHERE space_id = $1 AND source_item_id = $2`,
      [identity.spaceId, itemId, connectionId],
    );
    await this.db.query(
      `UPDATE extraction_jobs
          SET connection_id = $3
        WHERE space_id = $1
          AND source_item_id = $2
          AND status IN ('pending', 'queued')`,
        [identity.spaceId, itemId, connectionId],
      );
    await this.reindexItemForRetrieval(identity.spaceId, itemId, "source_item_source_update");
    return this.getItem(identity, itemId);
  }

  async listJobs(identity: SpaceUserIdentity, filters: {
    status: string | null;
    sourceItemId: string | null;
    connectionId: string | null;
    jobType: string | null;
    limit: number;
    offset: number;
  }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`status = $${params.length}`);
    }
    if (filters.sourceItemId) {
      params.push(filters.sourceItemId);
      clauses.push(`source_item_id = $${params.length}`);
    }
    if (filters.connectionId) {
      params.push(filters.connectionId);
      clauses.push(`connection_id = $${params.length}`);
    }
    if (filters.jobType) {
      params.push(filters.jobType);
      clauses.push(`job_type = $${params.length}`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string }>(`SELECT count(*)::text AS total FROM extraction_jobs ${where}`, params);
    const rows = await this.db.query<ExtractionJobRow>(
      `SELECT ${JOB_COLUMNS} FROM extraction_jobs ${where} ORDER BY created_at DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(jobOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async runJob(identity: SpaceUserIdentity, jobId: string) {
    await runSourceRecipeScanJob(this.db, this.config, jobId, identity.spaceId);
    await runCustomSourceHandlerScanJob(this.db, this.config, jobId, identity.spaceId);
    const worker = new SourceExtractionWorker(this.db, this.config);
    await worker.runPendingJob(jobId, identity.spaceId);
    const result = await this.db.query<ExtractionJobRow>(
      `SELECT ${JOB_COLUMNS} FROM extraction_jobs WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, jobId],
    );
    if (!result.rows[0]) throw new HttpError(404, "Extraction job not found");
    return jobOut(result.rows[0]);
  }

  async listEvidence(identity: SpaceUserIdentity, filters: { status: string | null; evidenceType: string | null; sourceItemId: string | null; projectId: string | null; connectionId: string | null; limit: number; offset: number }) {
    if (filters.projectId && !(await canAccessProject(this.db, identity.spaceId, filters.projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    if (filters.connectionId && !(await this.getConnectionRow(identity, filters.connectionId))) {
      throw new HttpError(404, "Source connection not found");
    }
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = [
      "space_id = $1",
      "deleted_at IS NULL",
      contentReadSql("extracted_evidence", "extracted_evidence", "$2"),
    ];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    if (filters.evidenceType) clauses.push(`evidence_type = ${add(filters.evidenceType)}`);
    if (filters.sourceItemId) clauses.push(`source_item_id = ${add(filters.sourceItemId)}`);
    if (filters.connectionId) {
      const connectionParam = add(filters.connectionId);
      clauses.push(
        `(
          EXISTS (
            SELECT 1
              FROM source_items ii
             WHERE ii.space_id = extracted_evidence.space_id
               AND ii.id = extracted_evidence.source_item_id
               AND ii.connection_id = ${connectionParam}
          )
          OR EXISTS (
            SELECT 1
              FROM source_snapshots ss
             WHERE ss.space_id = extracted_evidence.space_id
               AND ss.id = extracted_evidence.source_snapshot_id
               AND ss.connection_id = ${connectionParam}
          )
          OR EXISTS (
            SELECT 1
              FROM source_snapshots ss
             WHERE ss.space_id = extracted_evidence.space_id
               AND ss.source_item_id = extracted_evidence.source_item_id
               AND ss.connection_id = ${connectionParam}
          )
        )`,
      );
    }
    if (filters.projectId) {
      const projectParam = add(filters.projectId);
      clauses.push(
        `(
          EXISTS (
            SELECT 1
              FROM project_source_item_links psil
              JOIN project_source_bindings psb
                ON psb.space_id = psil.space_id
               AND psb.id = psil.project_source_binding_id
               AND psb.status = 'active'
             WHERE psil.space_id = extracted_evidence.space_id
               AND psil.source_item_id = extracted_evidence.source_item_id
               AND psil.project_id = ${projectParam}
               AND psil.status = 'active'
          )
          OR EXISTS (
            SELECT 1
              FROM evidence_links el
             WHERE el.space_id = extracted_evidence.space_id
               AND el.evidence_id = extracted_evidence.id
               AND el.target_type = 'project'
               AND el.target_id = ${projectParam}
               AND el.status = 'active'
          )
        )`,
      );
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string }>(`SELECT count(*)::text AS total FROM extracted_evidence ${where}`, params);
    const rows = await this.db.query<EvidenceRow>(
      `SELECT ${EVIDENCE_COLUMNS} FROM extracted_evidence ${where} ORDER BY updated_at DESC, id DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(evidenceOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createEvidence(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const status = optionalString(body.status) ?? "candidate";
    if (status === "active") throw new HttpError(409, "Source evidence remains candidate-only");
    if (!EVIDENCE_STATUSES.has(status)) throw new HttpError(422, "invalid evidence status");
    const sourceItemId = optionalString(body.source_item_id);
    const item = sourceItemId ? await this.getItemRow(identity, sourceItemId) : null;
    if (sourceItemId && !item) throw new HttpError(404, "Source item not found");
    const artifactId = optionalString(body.artifact_id);
    if (artifactId) {
      const artifact = await this.db.query<{ id: string }>(
        `SELECT id FROM artifacts WHERE space_id = $1 AND id = $2`,
        [identity.spaceId, artifactId],
      );
      if (!artifact.rows[0]) throw new HttpError(404, "Artifact not found");
    }
    const content = optionalString(body.content_excerpt);
    const now = new Date().toISOString();
    const result = await this.db.query<EvidenceRow>(
      `INSERT INTO extracted_evidence (
         id, space_id, owner_user_id, visibility, access_level,
         source_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, content_hash, artifact_id,
         source_uri, source_title, source_author, occurred_at, trust_level,
         extraction_method, confidence, status, metadata_json, created_by_user_id,
         created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8,
         $9, $10, $11, $12, $13,
         $14, $15, $16, $17::timestamptz, $18,
         $19, $20::float, $21, $22::jsonb, $23,
         $24, $24
       ) RETURNING ${EVIDENCE_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        item?.owner_user_id ?? identity.userId,
        item?.visibility ?? "private",
        item?.access_level ?? "full",
        sourceItemId,
        optionalString(body.source_object_type) ?? item?.source_object_type ?? null,
        optionalString(body.source_object_id) ?? item?.source_object_id ?? null,
        optionalString(body.evidence_type) ?? "excerpt",
        requiredString(body.title, "title"),
        content,
        content ? sha256(content) : null,
        artifactId,
        optionalString(body.source_uri) ?? item?.source_uri ?? null,
        item?.title ?? null,
        item?.author ?? null,
        toDbDate(body.occurred_at) ?? dateIso(item?.occurred_at),
        optionalString(body.trust_level) ?? "normal",
        optionalString(body.extraction_method) ?? "manual",
        numberValue(body.confidence),
        status,
        JSON.stringify(optionalObject(body.metadata) ?? optionalObject(body.metadata_json)),
        identity.userId,
        now,
      ],
    );
    const row = result.rows[0]!;
    if (item?.visibility === "selected_users") {
      await inheritContentAccessGrants(this.db, {
        spaceId: identity.spaceId,
        sourceResourceType: "source_item",
        sourceResourceId: item.id,
        targetResourceType: "extracted_evidence",
        targetResourceId: row.id,
        inheritedAt: now,
      });
    }
    await this.reindexEvidenceForRetrieval(identity.spaceId, row.id, "source_evidence_create");
    return evidenceOut(row);
  }

  async getEvidence(identity: SpaceUserIdentity, evidenceId: string) {
    const row = await this.getEvidenceRow(identity, evidenceId);
    return row ? evidenceOut(row) : null;
  }

  async updateEvidence(identity: SpaceUserIdentity, evidenceId: string, body: Record<string, unknown>) {
    if (!(await this.getEvidenceRow(identity, evidenceId))) throw new HttpError(404, "Evidence not found");
    const status = optionalString(body.status);
    if (status && !EVIDENCE_STATUSES.has(status)) throw new HttpError(422, "invalid evidence status");
    const now = new Date().toISOString();
    const result = await this.db.query<EvidenceRow>(
      `UPDATE extracted_evidence SET
         status = COALESCE($3, status),
         confidence = COALESCE($4::float, confidence),
         metadata_json = CASE WHEN $5::boolean THEN $6::jsonb ELSE metadata_json END,
         updated_at = $7
       WHERE space_id = $1 AND id = $2
       RETURNING ${EVIDENCE_COLUMNS}`,
      [
        identity.spaceId,
        evidenceId,
        status,
        numberValue(body.confidence),
        Object.hasOwn(body, "metadata") || Object.hasOwn(body, "metadata_json"),
        JSON.stringify(optionalObject(body.metadata) ?? optionalObject(body.metadata_json)),
        now,
      ],
    );
    const row = result.rows[0]!;
    await this.reindexEvidenceForRetrieval(identity.spaceId, row.id, "source_evidence_update");
    return evidenceOut(row);
  }

  async listEvidenceLinks(identity: SpaceUserIdentity, filters: {
    evidenceId: string | null;
    targetType: string | null;
    targetId: string | null;
    status: string | null;
    limit: number;
    offset: number;
  }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.evidenceId) clauses.push(`evidence_id = ${add(filters.evidenceId)}`);
    if (filters.targetType) clauses.push(`target_type = ${add(filters.targetType)}`);
    if (filters.targetId) clauses.push(`target_id = ${add(filters.targetId)}`);
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM evidence_links WHERE ${clauses.join(" AND ")}`,
      params,
    );
    const rows = await this.db.query<EvidenceLinkRow>(
      `SELECT ${EVIDENCE_LINK_COLUMNS}
         FROM evidence_links
        WHERE ${clauses.join(" AND ")}
        ORDER BY created_at DESC, id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(evidenceLinkOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createEvidenceLink(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const evidence = await this.getEvidenceRow(identity, requiredString(body.evidence_id, "evidence_id"));
    if (!evidence) throw new HttpError(404, "Evidence not found");
    const linkType = optionalString(body.link_type) ?? "context_candidate";
    if (!EVIDENCE_LINK_TYPES.has(linkType)) throw new HttpError(422, "invalid link_type");
    const targetType = requiredString(body.target_type, "target_type");
    const targetId = optionalString(body.target_id);
    if (targetId) {
      await this.assertTargetInSpace(identity.spaceId, targetType, targetId);
    }
    const now = new Date().toISOString();
    let result;
    try {
      result = await this.db.query<EvidenceLinkRow>(
        `INSERT INTO evidence_links (
           id, space_id, evidence_id, target_type, target_id, link_type,
           status, confidence, reason, created_by_user_id, created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::float, $9, $10, $11, $11)
         RETURNING ${EVIDENCE_LINK_COLUMNS}`,
        [
          randomUUID(),
          identity.spaceId,
          evidence.id,
          targetType,
          targetId,
          linkType,
          optionalString(body.status) ?? "active",
          numberValue(body.confidence),
          optionalString(body.reason),
          identity.userId,
          now,
        ],
      );
    } catch (error) {
      if ((error as { code?: string }).code === "23505") {
        throw new HttpError(409, "An active link with this evidence, target, and link_type already exists");
      }
      throw error;
    }
    return evidenceLinkOut(result.rows[0]!);
  }

  private async assertTargetInSpace(spaceId: string, targetType: string, targetId: string): Promise<void> {
    const tableMap: Record<string, string | null> = {
      space: null,
      workspace: "workspaces",
      project: "projects",
      user: "space_memberships",
      agent: "agents",
      run: "runs",
      proposal: "proposals",
      artifact: "artifacts",
      knowledge: "knowledge_items",
      memory: "memory_entries",
      task: "tasks",
    };
    if (targetType === "space") {
      if (targetId !== spaceId) throw new HttpError(403, "Target space is not accessible");
      return;
    }
    const table = tableMap[targetType];
    if (!table) throw new HttpError(422, "Unknown target_type");
    const idCol = targetType === "user" ? "user_id" : "id";
    const rows = await this.db.query(
      `SELECT 1 FROM ${table} WHERE space_id = $1 AND ${idCol} = $2 LIMIT 1`,
      [spaceId, targetId],
    );
    if (!rows.rows[0]) throw new HttpError(403, "Target is not accessible in this space");
  }

  async listProjectSourceBindings(identity: SpaceUserIdentity, filters: { projectId: string; sourceConnectionId: string | null }) {
    if (!(await canAccessProject(this.db, identity.spaceId, filters.projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.sourceConnectionId) clauses.push(`source_connection_id = ${add(filters.sourceConnectionId)}`);
    clauses.push(`project_id = ${add(filters.projectId)}`);
    const rows = await this.db.query<ProjectSourceBindingRow>(
      `SELECT ${PROJECT_SOURCE_BINDING_COLUMNS}
         FROM project_source_bindings
        WHERE ${clauses.join(" AND ")}
        ORDER BY priority DESC, updated_at DESC, id DESC`,
      params,
    );
    return rows.rows.map(projectSourceBindingOut);
  }

  async createProjectSourceBinding(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const sourceConnectionId = requiredString(body.source_connection_id, "source_connection_id");
    const projectId = requiredString(body.project_id, "project_id");
    const connection = await this.getConnectionRow(identity, sourceConnectionId);
    if (!connection || !(await this.canViewConnectionMetadata(identity, connection))) {
      throw new HttpError(404, "Source connection not found");
    }
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const deliveryScope = this.resolveProjectSourceDeliveryScope(identity, connection, body);
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectSourceBindingRow>(
      `INSERT INTO project_source_bindings (
         id, space_id, project_id, source_connection_id, binding_key,
         status, priority, delivery_scope, collection_notifications_enabled,
         filters_json, routing_policy_json, extraction_policy_json,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, 'active', $6::int, $7, $8::boolean, $9::jsonb, $10::jsonb, $11::jsonb, $12, $13, $13)
       RETURNING ${PROJECT_SOURCE_BINDING_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        projectId,
        sourceConnectionId,
        optionalString(body.binding_key) ?? "default",
        numberValue(body.priority) ?? 0,
        deliveryScope,
        booleanBody(body.collection_notifications_enabled, "collection_notifications_enabled", true),
        JSON.stringify(objectValue(body.filters)),
        JSON.stringify(objectValue(body.routing_policy)),
        JSON.stringify(objectValue(body.extraction_policy)),
        identity.userId,
        now,
      ],
    );
    const row = result.rows[0]!;
    const out = projectSourceBindingOut(row);
    if (!booleanBody(body.backfill_history, "backfill_history", false)) return out;
    return {
      ...out,
      backfill_result: await this.backfillProjectSourceBindingRow(identity, row),
    };
  }

  async updateProjectSourceBinding(identity: SpaceUserIdentity, bindingId: string, body: Record<string, unknown>) {
    const row = await this.getProjectSourceBindingRow(identity.spaceId, bindingId);
    if (!row) throw new HttpError(404, "Project source binding not found");
    await assertProjectWriter(this.db, identity.spaceId, row.project_id, identity.userId);
    const connection = await this.getConnectionRow(identity, row.source_connection_id);
    if (!connection) throw new HttpError(404, "Source connection not found");
    const status = optionalString(body.status) ?? row.status;
    if (!["active", "paused", "archived"].includes(status)) throw new HttpError(422, "invalid project source binding status");
    const deliveryScope = body.delivery_scope === undefined
      ? row.delivery_scope
      : this.resolveProjectSourceDeliveryScope(identity, connection, body);
    const now = new Date().toISOString();
    const updated = await this.db.query<ProjectSourceBindingRow>(
      `UPDATE project_source_bindings
          SET binding_key = $3,
              status = $4,
              priority = $5::int,
              delivery_scope = $6,
              collection_notifications_enabled = $7::boolean,
              filters_json = $8::jsonb,
              routing_policy_json = $9::jsonb,
              extraction_policy_json = $10::jsonb,
              updated_at = $11
        WHERE space_id = $1
          AND id = $2
        RETURNING ${PROJECT_SOURCE_BINDING_COLUMNS}`,
      [
        identity.spaceId,
        bindingId,
        optionalString(body.binding_key) ?? row.binding_key,
        status,
        numberValue(body.priority) ?? row.priority,
        deliveryScope,
        booleanBody(body.collection_notifications_enabled, "collection_notifications_enabled", row.collection_notifications_enabled),
        JSON.stringify(body.filters === undefined ? row.filters_json ?? {} : objectValue(body.filters)),
        JSON.stringify(body.routing_policy === undefined ? row.routing_policy_json ?? {} : objectValue(body.routing_policy)),
        JSON.stringify(body.extraction_policy === undefined ? row.extraction_policy_json ?? {} : objectValue(body.extraction_policy)),
        now,
      ],
    );
    const out = projectSourceBindingOut(updated.rows[0]!);
    if (status === "active") {
      await this.backfillProjectSourceBindingRow(identity, updated.rows[0]!);
    } else {
      await this.archiveProjectSourceBindingLinks(identity.spaceId, bindingId, row.project_id);
    }
    return out;
  }

  async deleteProjectSourceBinding(identity: SpaceUserIdentity, bindingId: string) {
    const row = await this.getProjectSourceBindingRow(identity.spaceId, bindingId);
    if (!row) throw new HttpError(404, "Project source binding not found");
    await assertProjectWriter(this.db, identity.spaceId, row.project_id, identity.userId);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_source_bindings
          SET status = 'archived',
              updated_at = $3
        WHERE space_id = $1
          AND id = $2`,
      [identity.spaceId, bindingId, now],
    );
    await this.archiveProjectSourceBindingLinks(identity.spaceId, bindingId, row.project_id);
    return { id: bindingId, status: "archived" };
  }

  async backfillProjectSourceBinding(identity: SpaceUserIdentity, bindingId: string) {
    const row = await this.getProjectSourceBindingRow(identity.spaceId, bindingId);
    if (!row) throw new HttpError(404, "Project source binding not found");
    await assertProjectWriter(this.db, identity.spaceId, row.project_id, identity.userId);
    return this.backfillProjectSourceBindingRow(identity, row);
  }

  private async getProjectSourceBindingRow(spaceId: string, bindingId: string): Promise<ProjectSourceBindingRow | null> {
    const rows = await this.db.query<ProjectSourceBindingRow>(
      `SELECT ${PROJECT_SOURCE_BINDING_COLUMNS}
         FROM project_source_bindings
        WHERE space_id = $1
          AND id = $2`,
      [spaceId, bindingId],
    );
    return rows.rows[0] ?? null;
  }

  private async backfillProjectSourceBindingRow(
    identity: SpaceUserIdentity,
    row: ProjectSourceBindingRow,
  ): Promise<Record<string, unknown>> {
    if (row.status !== "active") {
      throw new HttpError(422, "Only active project source bindings can backfill history");
    }
    const result = await recomputeProjectSourceBindingLinks(this.db, {
      spaceId: identity.spaceId,
      bindingId: row.id,
    });
    return {
      binding_id: row.id,
      project_id: row.project_id,
      source_connection_id: row.source_connection_id,
      ...result,
    };
  }

  async listProjectItems(identity: SpaceUserIdentity, filters: {
    projectId: string;
    sourceConnectionId: string | null;
    itemType: string | null;
    sourceDomain: string | null;
    matchedDate: string | null;
    createdAfter: string | null;
    occurredAfter: string | null;
    q: string | null;
    limit: number;
    offset: number;
  }) {
    if (!(await canAccessProject(this.db, identity.spaceId, filters.projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    const params: unknown[] = [identity.spaceId, identity.userId, filters.projectId];
    const clauses = [
      "psil.space_id = $1",
      "psil.project_id = $3",
      "psil.status = 'active'",
      "psb.status = 'active'",
      "si.deleted_at IS NULL",
      contentReadSql("source_item", "si", "$2"),
      `(psb.delivery_scope = 'project_members' OR ${sourceItemConnectionGateClause("si", "$2", false)})`,
    ];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.sourceConnectionId) clauses.push(`psil.source_connection_id = ${add(filters.sourceConnectionId)}`);
    if (filters.itemType) clauses.push(`si.item_type = ${add(filters.itemType)}`);
    if (filters.sourceDomain) clauses.push(`si.source_domain = ${add(filters.sourceDomain)}`);
    if (filters.matchedDate) {
      const matchedDate = add(filters.matchedDate);
      clauses.push(`psil.matched_at >= ${matchedDate}::date AND psil.matched_at < (${matchedDate}::date + interval '1 day')`);
    }
    if (filters.createdAfter) clauses.push(`si.created_at >= ${add(filters.createdAfter)}::timestamptz`);
    if (filters.occurredAfter) clauses.push(`si.occurred_at >= ${add(filters.occurredAfter)}::timestamptz`);
    if (filters.q) {
      clauses.push(`(si.title ILIKE ${add(`%${filters.q}%`)} OR si.excerpt ILIKE $${params.length} OR si.source_uri ILIKE $${params.length} OR si.source_domain ILIKE $${params.length})`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const joins = `
      FROM project_source_item_links psil
      JOIN project_source_bindings psb
        ON psb.space_id = psil.space_id
       AND psb.id = psil.project_source_binding_id
      JOIN source_items si
        ON si.space_id = psil.space_id
       AND si.id = psil.source_item_id
      LEFT JOIN source_item_user_states suis
        ON suis.space_id = si.space_id
       AND suis.source_item_id = si.id
       AND suis.user_id = $2`;
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total ${joins} ${where}`,
      params,
    );
    const rows = await this.db.query<ProjectSourceItemOutRow>(
      `SELECT psil.id AS project_link_id,
              psil.space_id AS project_link_space_id,
              psil.project_id AS project_link_project_id,
              psil.project_source_binding_id AS project_link_project_source_binding_id,
              psil.source_connection_id AS project_link_source_connection_id,
              psil.source_item_id AS project_link_source_item_id,
              psil.status AS project_link_status,
              psil.matched_at AS project_link_matched_at,
              psil.match_reason AS project_link_match_reason,
              psil.created_at AS project_link_created_at,
              psil.updated_at AS project_link_updated_at,
              ${itemColumnsWithCurrentUserState("si")}
         ${joins}
       ${where}
       ORDER BY psil.matched_at DESC, psil.id DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(projectSourceItemOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async projectSourceSummary(identity: SpaceUserIdentity, projectId: string) {
    if (!(await canAccessProject(this.db, identity.spaceId, projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    const counts = await this.db.query<{ binding_count: string; today_new_items: string }>(
      `SELECT
         (SELECT count(*)::text
            FROM project_source_bindings
           WHERE space_id = $1 AND project_id = $2 AND status <> 'archived') AS binding_count,
         (SELECT count(*)::text
            FROM project_source_item_links
           WHERE space_id = $1
             AND project_id = $2
             AND status = 'active'
             AND matched_at >= date_trunc('day', now())) AS today_new_items`,
      [identity.spaceId, projectId],
    );
    const health = await this.projectSourceHealth(identity, projectId);
    const healthCounts = health.reduce<Record<string, number>>((acc, row) => {
      acc[row.status] = (acc[row.status] ?? 0) + 1;
      return acc;
    }, {});
    const recentItems = await this.listProjectItems(identity, {
      projectId,
      sourceConnectionId: null,
      itemType: null,
      sourceDomain: null,
      matchedDate: null,
      createdAfter: null,
      occurredAfter: null,
      q: null,
      limit: 5,
      offset: 0,
    });
    return {
      project_id: projectId,
      bound_source_count: countFromRow({ total: counts.rows[0]?.binding_count ?? "0" }),
      today_new_items: countFromRow({ total: counts.rows[0]?.today_new_items ?? "0" }),
      health_counts: healthCounts,
      recent_items: recentItems.items,
    };
  }

  async sourceHealth(identity: SpaceUserIdentity, filters: { connectionId: string | null }) {
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = [
      "sc.space_id = $1",
      "sc.deleted_at IS NULL",
      contentReadSql("source_connection", "sc", "$2"),
    ];
    if (filters.connectionId) {
      params.push(filters.connectionId);
      clauses.push(`sc.id = $${params.length}`);
    }
    const rows = await this.db.query<{
      source_connection_id: string;
      source_name: string;
      connection_status: string;
      scheduler_status: string | null;
      next_run_at: unknown;
      last_run_at: unknown;
      last_success_at: unknown;
      last_failure_at: unknown;
      last_error: string | null;
      queued_jobs: string;
      running_jobs: string;
      recent_new_items: string;
      consecutive_failures: string;
    }>(
      `WITH last_success AS (
         SELECT DISTINCT ON (space_id, connection_id) space_id, connection_id, completed_at
           FROM extraction_jobs
          WHERE space_id = $1 AND connection_id IS NOT NULL AND status = 'succeeded'
          ORDER BY space_id, connection_id, completed_at DESC NULLS LAST, created_at DESC
       ),
       last_failure AS (
         SELECT DISTINCT ON (space_id, connection_id) space_id, connection_id, completed_at, error_message
           FROM extraction_jobs
          WHERE space_id = $1 AND connection_id IS NOT NULL AND status = 'failed'
          ORDER BY space_id, connection_id, completed_at DESC NULLS LAST, created_at DESC
       )
       SELECT sc.id AS source_connection_id,
              sc.name AS source_name,
              sc.status AS connection_status,
              st.status AS scheduler_status,
              st.next_run_at,
              st.last_run_at,
              ls.completed_at AS last_success_at,
              lf.completed_at AS last_failure_at,
              lf.error_message AS last_error,
              (SELECT count(*)::text FROM extraction_jobs ej WHERE ej.space_id = sc.space_id AND ej.connection_id = sc.id AND ej.status = 'pending') AS queued_jobs,
              (SELECT count(*)::text FROM extraction_jobs ej WHERE ej.space_id = sc.space_id AND ej.connection_id = sc.id AND ej.status = 'running') AS running_jobs,
              (SELECT count(*)::text FROM source_items si WHERE si.space_id = sc.space_id AND si.connection_id = sc.id AND si.deleted_at IS NULL AND si.first_seen_at >= now() - interval '24 hours') AS recent_new_items,
              (SELECT count(*)::text
                 FROM extraction_jobs failed
                WHERE failed.space_id = sc.space_id
                  AND failed.connection_id = sc.id
                  AND failed.status = 'failed'
                  AND (ls.completed_at IS NULL OR failed.completed_at > ls.completed_at)) AS consecutive_failures
         FROM source_connections sc
         LEFT JOIN source_connection_user_subscriptions scus
           ON scus.space_id = sc.space_id
          AND scus.source_connection_id = sc.id
          AND scus.user_id = $2
         LEFT JOIN scheduler_tasks st
           ON st.space_id = sc.space_id
          AND st.task_type = 'source_connection_scan'
          AND st.task_key = sc.id
         LEFT JOIN last_success ls
           ON ls.space_id = sc.space_id
          AND ls.connection_id = sc.id
         LEFT JOIN last_failure lf
           ON lf.space_id = sc.space_id
          AND lf.connection_id = sc.id
        WHERE ${clauses.join(" AND ")}
        ORDER BY sc.updated_at DESC, sc.id DESC`,
      params,
    );
    return rows.rows.map((row) => {
      const queuedJobs = Number(row.queued_jobs) || 0;
      const runningJobs = Number(row.running_jobs) || 0;
      const consecutiveFailures = Number(row.consecutive_failures) || 0;
      const lastFailureAt = dateIso(row.last_failure_at);
      const lastSuccessAt = dateIso(row.last_success_at);
      let status = "healthy";
      if (row.connection_status === "paused" || row.scheduler_status === "paused") {
        status = "paused";
      } else if (runningJobs > 0 || queuedJobs > 0) {
        status = "running";
      } else if (consecutiveFailures >= 3) {
        status = "failing";
      } else if (lastFailureAt && (!lastSuccessAt || lastFailureAt > lastSuccessAt)) {
        status = "attention";
      }
      return {
        binding_id: null,
        project_id: null,
        source_connection_id: row.source_connection_id,
        source_name: row.source_name,
        status,
        last_success_at: lastSuccessAt,
        last_failure_at: lastFailureAt,
        last_error: row.last_error,
        next_run_at: dateIso(row.next_run_at),
        queued_jobs: queuedJobs,
        running_jobs: runningJobs,
        recent_new_items: Number(row.recent_new_items) || 0,
        consecutive_failures: consecutiveFailures,
      };
    });
  }

  async projectSourceHealth(identity: SpaceUserIdentity, projectId: string) {
    if (!(await canAccessProject(this.db, identity.spaceId, projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    const rows = await this.db.query<{
      binding_id: string;
      project_id: string;
      source_connection_id: string;
      source_name: string;
      binding_status: string;
      connection_status: string;
      scheduler_status: string | null;
      next_run_at: unknown;
      last_run_at: unknown;
      last_success_at: unknown;
      last_failure_at: unknown;
      last_error: string | null;
      queued_jobs: string;
      running_jobs: string;
      recent_new_items: string;
      consecutive_failures: string;
    }>(
      `WITH last_success AS (
         SELECT DISTINCT ON (space_id, connection_id) space_id, connection_id, completed_at
           FROM extraction_jobs
          WHERE space_id = $1 AND connection_id IS NOT NULL AND status = 'succeeded'
          ORDER BY space_id, connection_id, completed_at DESC NULLS LAST, created_at DESC
       ),
       last_failure AS (
         SELECT DISTINCT ON (space_id, connection_id) space_id, connection_id, completed_at, error_message
           FROM extraction_jobs
          WHERE space_id = $1 AND connection_id IS NOT NULL AND status = 'failed'
          ORDER BY space_id, connection_id, completed_at DESC NULLS LAST, created_at DESC
       )
       SELECT psb.id AS binding_id,
              psb.project_id,
              psb.source_connection_id,
              sc.name AS source_name,
              psb.status AS binding_status,
              sc.status AS connection_status,
              st.status AS scheduler_status,
              st.next_run_at,
              st.last_run_at,
              ls.completed_at AS last_success_at,
              lf.completed_at AS last_failure_at,
              lf.error_message AS last_error,
              (SELECT count(*)::text FROM extraction_jobs ej WHERE ej.space_id = psb.space_id AND ej.connection_id = psb.source_connection_id AND ej.status = 'pending') AS queued_jobs,
              (SELECT count(*)::text FROM extraction_jobs ej WHERE ej.space_id = psb.space_id AND ej.connection_id = psb.source_connection_id AND ej.status = 'running') AS running_jobs,
              (SELECT count(*)::text FROM project_source_item_links psil WHERE psil.space_id = psb.space_id AND psil.project_source_binding_id = psb.id AND psil.status = 'active' AND psil.matched_at >= now() - interval '24 hours') AS recent_new_items,
              (SELECT count(*)::text
                 FROM extraction_jobs failed
                WHERE failed.space_id = psb.space_id
                  AND failed.connection_id = psb.source_connection_id
                  AND failed.status = 'failed'
                  AND (ls.completed_at IS NULL OR failed.completed_at > ls.completed_at)) AS consecutive_failures
         FROM project_source_bindings psb
         JOIN source_connections sc
           ON sc.space_id = psb.space_id
          AND sc.id = psb.source_connection_id
          AND sc.deleted_at IS NULL
         LEFT JOIN scheduler_tasks st
           ON st.space_id = psb.space_id
          AND st.task_type = 'source_connection_scan'
          AND st.task_key = psb.source_connection_id
         LEFT JOIN last_success ls
           ON ls.space_id = psb.space_id
          AND ls.connection_id = psb.source_connection_id
         LEFT JOIN last_failure lf
           ON lf.space_id = psb.space_id
          AND lf.connection_id = psb.source_connection_id
        WHERE psb.space_id = $1
          AND psb.project_id = $2
          AND psb.status <> 'archived'
        ORDER BY psb.priority DESC, psb.updated_at DESC`,
      [identity.spaceId, projectId],
    );
    return rows.rows.map((row) => {
      const queuedJobs = Number(row.queued_jobs) || 0;
      const runningJobs = Number(row.running_jobs) || 0;
      const consecutiveFailures = Number(row.consecutive_failures) || 0;
      const lastFailureAt = dateIso(row.last_failure_at);
      const lastSuccessAt = dateIso(row.last_success_at);
      let status = "healthy";
      if (row.binding_status === "paused" || row.connection_status === "paused" || row.scheduler_status === "paused") {
        status = "paused";
      } else if (runningJobs > 0 || queuedJobs > 0) {
        status = "running";
      } else if (consecutiveFailures >= 3) {
        status = "failing";
      } else if (lastFailureAt && (!lastSuccessAt || lastFailureAt > lastSuccessAt)) {
        status = "attention";
      }
      return {
        binding_id: row.binding_id,
        project_id: row.project_id,
        source_connection_id: row.source_connection_id,
        source_name: row.source_name,
        status,
        last_success_at: lastSuccessAt,
        last_failure_at: lastFailureAt,
        last_error: row.last_error,
        next_run_at: dateIso(row.next_run_at),
        queued_jobs: queuedJobs,
        running_jobs: runningJobs,
        recent_new_items: Number(row.recent_new_items) || 0,
        consecutive_failures: consecutiveFailures,
      };
    });
  }

  private async archiveProjectSourceBindingLinks(spaceId: string, bindingId: string, projectId: string): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `WITH archived_links AS (
         UPDATE project_source_item_links
            SET status = 'archived',
                updated_at = $4
          WHERE space_id = $1
            AND project_source_binding_id = $2
            AND project_id = $3
            AND status <> 'archived'
          RETURNING source_item_id
       )
       UPDATE evidence_links el
          SET status = 'archived',
              updated_at = $4
        WHERE el.space_id = $1
          AND el.target_type = 'project'
          AND el.target_id = $3
          AND el.status = 'active'
          AND el.reason = 'project_source_binding:' || $2
          AND EXISTS (
            SELECT 1
              FROM extracted_evidence ev
              JOIN archived_links al ON al.source_item_id = ev.source_item_id
             WHERE ev.space_id = el.space_id
               AND ev.id = el.evidence_id
          )`,
      [spaceId, bindingId, projectId, now],
    );
  }

  async createSummaryRun(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const evidenceIds = stringList(body.evidence_ids);
    const sourceItemIds = stringList(body.source_item_ids);
    if (!evidenceIds.length && !sourceItemIds.length) throw new HttpError(422, "At least one evidence_id or source_item_id is required");
    const evidenceRows = evidenceIds.length
      ? await this.db.query<EvidenceRow>(
          `SELECT ${evidenceColumnsForAlias("ee")}
             FROM extracted_evidence ee
             LEFT JOIN source_items si
               ON si.space_id = ee.space_id
              AND si.id = ee.source_item_id
              AND si.deleted_at IS NULL
            WHERE ee.space_id = $1
              AND ee.id::text = ANY($2::text[])
              AND ee.deleted_at IS NULL
              AND ${contentReadSql("extracted_evidence", "ee", "$3")}
              AND (
                ee.source_item_id IS NULL
                OR ${sourceItemReadableClause("si", "$3", false)}
              )`,
          [identity.spaceId, evidenceIds, identity.userId],
        )
      : { rows: [] as EvidenceRow[] };
    const itemRows = sourceItemIds.length
      ? await this.db.query<SourceItemRow>(
          `SELECT ${itemColumnsForAlias("si")}
             FROM source_items si
            WHERE si.space_id = $1
              AND si.id::text = ANY($2::text[])
              AND si.deleted_at IS NULL
              AND ${sourceItemReadableClause("si", "$3", false)}`,
          [identity.spaceId, sourceItemIds, identity.userId],
        )
      : { rows: [] as SourceItemRow[] };
    if (evidenceRows.rows.length !== evidenceIds.length || itemRows.rows.length !== sourceItemIds.length) throw new HttpError(404, "Summary input not found");
    const summary = buildSummary(evidenceRows.rows, itemRows.rows, optionalString(body.summary_goal));
    if (body.create_memory_proposal === true || body.create_memory_proposals === true) {
      await this.enforceSummaryImportTargetPolicy(identity, evidenceRows.rows, itemRows.rows, "memory_proposal");
    }
    if (body.create_knowledge_proposal === true || body.create_knowledge_proposals === true) {
      await this.enforceSummaryImportTargetPolicy(identity, evidenceRows.rows, itemRows.rows, "knowledge");
    }
    const artifactId = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, run_id, proposal_id, artifact_type, title, content,
         storage_ref, storage_path, mime_type, export_formats_json, canonical_format,
         preview, created_at, updated_at, metadata_json, visibility, owner_user_id,
         trust_level
       ) VALUES (
         $1, $2, NULL, NULL, 'summary', $3, $4,
         NULL, NULL, 'text/markdown', $5::jsonb, 'markdown',
         false, $6, $6, $7::jsonb, 'space_shared', $8, 'medium'
       )`,
      [
        artifactId,
        identity.spaceId,
        optionalString(body.summary_goal) ?? "Source evidence summary",
        summary,
        JSON.stringify(["markdown", "txt"]),
        now,
        JSON.stringify({ evidence_ids: evidenceIds, source_item_ids: sourceItemIds, generated_by: "server" }),
        identity.userId,
      ],
    );
    const proposalIds: string[] = [];
    if (body.create_memory_proposal === true || body.create_memory_proposals === true) {
      proposalIds.push(await this.insertSummaryProposal(identity, "memory_create", "Summary memory", summary, artifactId, evidenceIds, sourceItemIds));
    }
    if (body.create_knowledge_proposal === true || body.create_knowledge_proposals === true) {
      proposalIds.push(await this.insertSummaryProposal(identity, "knowledge_create", "Summary knowledge", summary, artifactId, evidenceIds, sourceItemIds));
    }
    return { run_id: `summary:${artifactId}`, artifact_id: artifactId, proposal_ids: proposalIds, status: "succeeded", summary_preview: summary.slice(0, 500) };
  }

  private async enforceItemRetentionPolicy(identity: SpaceUserIdentity, item: SourceItemRow, retention: "metadata_only" | "summary_only" | "full_text" | "full_snapshot") {
    if (!item.connection_id) return;
    const connection = await this.getConnectionRow(identity, item.connection_id);
    if (!connection) throw new HttpError(404, "Source connection not found");
    enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, retention);
  }

  private async enforceSummaryImportTargetPolicy(
    identity: SpaceUserIdentity,
    evidenceRows: EvidenceRow[],
    itemRows: SourceItemRow[],
    target: "knowledge" | "memory_proposal",
  ) {
    const itemsById = new Map<string, SourceItemRow>();
    for (const row of itemRows) {
      if (row.id) itemsById.set(row.id, row);
    }
    const evidenceItemIds = [
      ...new Set(
        evidenceRows
          .map((row) => row.source_item_id)
          .filter((id): id is string => typeof id === "string" && id.length > 0 && !itemsById.has(id)),
      ),
    ];
    if (evidenceItemIds.length) {
      const evidenceItems = await this.db.query<SourceItemRow>(
        `SELECT ${itemColumnsForAlias("si")}
           FROM source_items si
          WHERE si.space_id = $1
            AND si.id::text = ANY($2::text[])
            AND si.deleted_at IS NULL
            AND ${sourceItemReadableClause("si", "$3", false)}`,
        [identity.spaceId, evidenceItemIds, identity.userId],
      );
      if (evidenceItems.rows.length !== evidenceItemIds.length) throw new HttpError(404, "Summary source item not found");
      for (const row of evidenceItems.rows) {
        itemsById.set(row.id, row);
      }
    }

    const connectionIds = [
      ...new Set(
        [...itemsById.values()]
          .map((row) => row.connection_id)
          .filter((id): id is string => typeof id === "string" && id.length > 0),
      ),
    ];
    if (!connectionIds.length) return;

    const connections = await this.db.query<SourceConnectionRow>(
      `SELECT ${CONNECTION_COLUMNS} FROM source_connections WHERE space_id = $1 AND id::text = ANY($2::text[]) AND deleted_at IS NULL`,
      [identity.spaceId, connectionIds],
    );
    if (connections.rows.length !== connectionIds.length) throw new HttpError(404, "Source connection not found");
    const connectionsById = new Map(connections.rows.map((row) => [row.id, row]));
    for (const item of itemsById.values()) {
      if (!item.connection_id) continue;
      const connection = connectionsById.get(item.connection_id);
      if (!connection) throw new HttpError(404, "Source connection not found");
      enforceSourceDerivedImportTarget(normalizeSourceConnectionReadGovernance(connection).policy, target);
    }
  }

  private async getItemRow(identity: SpaceUserIdentity, itemId: string) {
    const result = await this.db.query<SourceItemRow>(
      `SELECT ${itemColumnsWithCurrentUserState("si")}
         FROM source_items si
         LEFT JOIN source_item_user_states suis
           ON suis.space_id = si.space_id
          AND suis.source_item_id = si.id
          AND suis.user_id = $2
        WHERE si.space_id = $1
          AND si.id = $3
          AND si.deleted_at IS NULL
          AND ${sourceItemReadableClause("si", "$2", false)}`,
      [identity.spaceId, identity.userId, itemId],
    );
    return result.rows[0] ?? null;
  }

  private async getConnectionRow(identity: SpaceUserIdentity, connectionId: string) {
    const result = await this.db.query<SourceConnectionRow>(
      `SELECT ${connectionColumnsWithConnectorForAlias("sc", "c")}, ${CONNECTION_SUBSCRIPTION_SELECT}
         FROM source_connections sc
         JOIN source_connectors c ON c.id = sc.connector_id
         LEFT JOIN source_connection_user_subscriptions scus
           ON scus.space_id = sc.space_id
          AND scus.source_connection_id = sc.id
          AND scus.user_id = $3
        WHERE sc.space_id = $1 AND sc.id = $2 AND sc.deleted_at IS NULL`,
      [identity.spaceId, connectionId, identity.userId],
    );
    return result.rows[0] ? this.withConnectionSchedule(result.rows[0]) : null;
  }

  private async assertConnectionSubscribed(
    identity: SpaceUserIdentity,
    connectionId: string,
    requireLibraryEnabled: boolean,
  ): Promise<void> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id
         FROM source_connection_user_subscriptions
        WHERE space_id = $1
          AND source_connection_id = $2
          AND user_id = $3
          AND status = 'subscribed'
          ${requireLibraryEnabled ? "AND library_enabled = true" : ""}
        LIMIT 1`,
      [identity.spaceId, connectionId, identity.userId],
    );
    if (!result.rows[0]) throw new HttpError(404, "Source connection not found");
  }

  private async canViewConnectionMetadata(identity: SpaceUserIdentity, connection: SourceConnectionRow): Promise<boolean> {
    return (await contentDecisionFromDb(this.db, identity, "source_connection", connection.id)) !== "deny";
  }

  private resolveProjectSourceDeliveryScope(
    identity: SpaceUserIdentity,
    connection: SourceConnectionRow,
    body: Record<string, unknown>,
  ): string {
    const requested = optionalString(body.delivery_scope);
    if (requested && !PROJECT_SOURCE_DELIVERY_SCOPES.has(requested)) {
      throw new HttpError(422, "delivery_scope must be project_members or source_subscribers");
    }
    const restrictedSource =
      connection.visibility !== "space_shared" ||
      Boolean(connection.credential_id) ||
      connection.handler_kind === "generated_custom" ||
      connection.connector_type === "custom" ||
      connection.connector_key === "custom";
    const scope = requested ?? (restrictedSource ? "source_subscribers" : "project_members");
    if (scope === "project_members" && restrictedSource && connection.owner_user_id !== identity.userId) {
      throw new HttpError(403, "Only the source owner can share a private or credentialed source with project members");
    }
    return scope;
  }

  private async upsertItemUserState(
    identity: SpaceUserIdentity,
    itemId: string,
    input: {
      libraryStatus: string | null;
      readStatus: string | null;
      firstOpenedAt: string | null;
      lastOpenedAt: string | null;
      progress: Record<string, unknown> | null;
    },
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO source_item_user_states (
         id, space_id, source_item_id, user_id, library_status, read_status,
         first_opened_at, last_opened_at, progress_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, COALESCE($5::varchar(32), 'new'), COALESCE($6::varchar(32), 'unread'),
         $7::timestamptz, $8::timestamptz, COALESCE($9::jsonb, '{}'::jsonb), $10, $10
       )
       ON CONFLICT (space_id, source_item_id, user_id) DO UPDATE SET
         library_status = COALESCE($5::varchar(32), source_item_user_states.library_status),
         read_status = COALESCE($6::varchar(32), source_item_user_states.read_status),
         first_opened_at = COALESCE(source_item_user_states.first_opened_at, $7::timestamptz),
         last_opened_at = COALESCE($8::timestamptz, source_item_user_states.last_opened_at),
         progress_json = COALESCE($9::jsonb, source_item_user_states.progress_json),
         updated_at = $10`,
      [
        randomUUID(),
        identity.spaceId,
        itemId,
        identity.userId,
        input.libraryStatus,
        input.readStatus,
        input.firstOpenedAt,
        input.lastOpenedAt,
        input.progress ? JSON.stringify(input.progress) : null,
        now,
      ],
    );
  }

  private async upsertConnectionSubscription(input: {
    spaceId: string;
    connectionId: string;
    userId: string;
    status: string;
    libraryEnabled: boolean;
    digestEnabled: boolean;
    recommendedByUserId: string | null;
    recommendationMessage: string | null;
    notify: boolean;
    now: string;
  }): Promise<boolean> {
    if (!SOURCE_CONNECTION_SUBSCRIPTION_STATUSES.has(input.status)) {
      throw new HttpError(422, "invalid source subscription status");
    }
    const result = await this.db.query<{ status: string }>(
      `INSERT INTO source_connection_user_subscriptions (
         id, space_id, source_connection_id, user_id, status,
         library_enabled, digest_enabled, recommended_by_user_id,
         recommendation_message, last_notified_at, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8, $9, CASE WHEN $10::boolean THEN $11::timestamptz ELSE NULL END, $11, $11
       )
       ON CONFLICT (space_id, source_connection_id, user_id) DO UPDATE SET
         status = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.status
           ELSE $5::varchar(32)
         END,
         library_enabled = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.library_enabled
           ELSE $6::boolean
         END,
         digest_enabled = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.digest_enabled
           ELSE $7::boolean
         END,
         recommended_by_user_id = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.recommended_by_user_id
           ELSE $8
         END,
         recommendation_message = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.recommendation_message
           ELSE $9
         END,
         last_notified_at = CASE
           WHEN source_connection_user_subscriptions.status IN ('muted', 'subscribed') AND $5::varchar(32) = 'pending'
             THEN source_connection_user_subscriptions.last_notified_at
           WHEN $10::boolean THEN $11::timestamptz
           ELSE source_connection_user_subscriptions.last_notified_at
         END,
         updated_at = $11
       RETURNING status`,
      [
        randomUUID(),
        input.spaceId,
        input.connectionId,
        input.userId,
        input.status,
        input.libraryEnabled,
        input.digestEnabled,
        input.recommendedByUserId,
        input.recommendationMessage,
        input.notify,
        input.now,
      ],
    );
    return result.rows[0]?.status === input.status;
  }

  private async createDefaultPendingSubscriptions(
    identity: SpaceUserIdentity,
    connection: SourceConnectionRow,
    now: string,
  ): Promise<void> {
    if (connection.visibility !== "space_shared" || connection.credential_id) return;
    const space = await this.db.query<{ type: string }>(
      `SELECT type FROM spaces WHERE id = $1 LIMIT 1`,
      [identity.spaceId],
    );
    if (space.rows[0]?.type === "personal") return;
    const members = await this.db.query<{ user_id: string }>(
      `SELECT user_id
         FROM space_memberships
        WHERE space_id = $1
          AND status = 'active'
          AND role <> 'guest'
          AND user_id <> $2`,
      [identity.spaceId, identity.userId],
    );
    for (const member of members.rows) {
      const changed = await this.upsertConnectionSubscription({
        spaceId: identity.spaceId,
        connectionId: connection.id,
        userId: member.user_id,
        status: "pending",
        libraryEnabled: true,
        digestEnabled: true,
        recommendedByUserId: identity.userId,
        recommendationMessage: null,
        notify: true,
        now,
      });
      if (!changed) continue;
      await this.upsertSourceRecommendationActivity({
        spaceId: identity.spaceId,
        targetUserId: member.user_id,
        connection,
        recommendedByUserId: identity.userId,
        recommendationMessage: null,
        now,
      });
    }
  }

  private async resolveRecommendationTargets(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
  ): Promise<string[]> {
    const rawTargets = Array.isArray(body.target_user_ids)
      ? body.target_user_ids.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
      : [];
    if (body.all_space === true) {
      const members = await this.db.query<{ user_id: string }>(
        `SELECT user_id
           FROM space_memberships
          WHERE space_id = $1
            AND status = 'active'
            AND role <> 'guest'`,
        [identity.spaceId],
      );
      return [...new Set(members.rows.map((row) => row.user_id))];
    }
    if (!rawTargets.length) throw new HttpError(422, "target_user_ids or all_space is required");
    const uniqueTargets = [...new Set(rawTargets)];
    const members = await this.db.query<{ user_id: string }>(
      `SELECT user_id
         FROM space_memberships
        WHERE space_id = $1
          AND status = 'active'
          AND user_id = ANY($2::varchar[])`,
      [identity.spaceId, uniqueTargets],
    );
    const found = new Set(members.rows.map((row) => row.user_id));
    if (found.size !== uniqueTargets.length) throw new HttpError(404, "Recommendation target not found");
    return uniqueTargets;
  }

  private async upsertSourceRecommendationActivity(input: {
    spaceId: string;
    targetUserId: string;
    connection: SourceConnectionRow;
    recommendedByUserId: string;
    recommendationMessage: string | null;
    now: string;
  }): Promise<void> {
    const aggregateKey = `source_recommendation:${input.connection.id}:${input.targetUserId}`;
    const title = `Source recommended: ${input.connection.name}`;
    const content = input.recommendationMessage ?? "A source was recommended for your Library.";
    const payload = {
      pointer_type: "source_recommendation",
      source_connection_id: input.connection.id,
      source_connection_name: input.connection.name,
      recommended_by_user_id: input.recommendedByUserId,
      recommendation_message: input.recommendationMessage,
    };
    await this.db.query(
      `INSERT INTO activity_records (
         id, space_id, user_id, activity_type, title, content, payload_json,
         occurred_at, created_at, status, updated_at, source_kind, source_trust,
         visibility, owner_user_id, subject_user_id, aggregate_key
       ) VALUES (
         $1, $2, $3, 'source_recommendation', $4, $5, $6::jsonb,
         $7, $7, 'raw', $7, 'source', 'internal_system',
         'private', $3, $3, $8
       )
       ON CONFLICT (space_id, aggregate_key) WHERE aggregate_key IS NOT NULL DO UPDATE SET
         title = EXCLUDED.title,
         content = EXCLUDED.content,
         payload_json = EXCLUDED.payload_json,
         status = 'raw',
         updated_at = EXCLUDED.updated_at,
         occurred_at = EXCLUDED.occurred_at,
         discarded_at = NULL`,
      [
        randomUUID(),
        input.spaceId,
        input.targetUserId,
        title,
        content,
        JSON.stringify(payload),
        input.now,
        aggregateKey,
      ],
    );
  }

  private async withConnectionSchedules(rows: SourceConnectionRow[]): Promise<SourceConnectionRow[]> {
    return Promise.all(rows.map((row) => this.withConnectionSchedule(row)));
  }

  private async withConnectionSchedule(row: SourceConnectionRow): Promise<SourceConnectionRow> {
    const task = await getSourceConnectionScanTask(this.db, row.id);
    return sourceConnectionWithSchedule(row, task);
  }

  private async getEvidenceRow(identity: SpaceUserIdentity, evidenceId: string) {
    const result = await this.db.query<EvidenceRow>(
      `SELECT ${evidenceColumnsForAlias("ee")}
         FROM extracted_evidence ee
         LEFT JOIN source_items si
           ON si.space_id = ee.space_id
          AND si.id = ee.source_item_id
          AND si.deleted_at IS NULL
        WHERE ee.space_id = $1
          AND ee.id = $2
          AND ee.deleted_at IS NULL
          AND ${contentReadSql("extracted_evidence", "ee", "$3")}
          AND (
            ee.source_item_id IS NULL
            OR ${sourceItemReadableClause("si", "$3", false)}
          )`,
      [identity.spaceId, evidenceId, identity.userId],
    );
    return result.rows[0] ?? null;
  }

  private async createJob(input: { identity: SpaceUserIdentity; connectionId: string | null; sourceItemId: string | null; jobType: string; metadata: Record<string, unknown> }) {
    const now = new Date().toISOString();
    const result = await this.db.query<ExtractionJobRow>(
      `INSERT INTO extraction_jobs (
         id, space_id, connection_id, source_item_id, job_type, status,
         metadata_json, created_at
       ) VALUES ($1, $2, $3, $4, $5, 'pending', $6::jsonb, $7)
       RETURNING ${JOB_COLUMNS}`,
      [randomUUID(), input.identity.spaceId, input.connectionId, input.sourceItemId, input.jobType, JSON.stringify(input.metadata), now],
    );
    return jobOut(result.rows[0]!);
  }

  private async createCustomSourceScanJob(input: {
    identity: SpaceUserIdentity;
    connectionId: string;
    handlerVersionId: string;
    metadata: Record<string, unknown>;
  }) {
    const now = new Date().toISOString();
    const jobId = randomUUID();
    const runId = randomUUID();
    const result = await this.db.query<ExtractionJobRow>(
      `WITH inserted_job AS (
         INSERT INTO extraction_jobs (
           id, space_id, connection_id, source_item_id, job_type, status,
           metadata_json, created_at
         ) VALUES ($1, $2, $3, NULL, 'connection_scan', 'pending', $4::jsonb, $5)
         RETURNING ${JOB_COLUMNS}
       ), inserted_run AS (
         INSERT INTO source_handler_runs (
           id, space_id, source_connection_id, handler_version_id, extraction_job_id, status, created_at
         )
         SELECT $6, space_id, connection_id, $7, id, 'queued', $5 FROM inserted_job
       )
       SELECT ${JOB_COLUMNS} FROM inserted_job`,
      [
        jobId,
        input.identity.spaceId,
        input.connectionId,
        JSON.stringify(input.metadata),
        now,
        runId,
        input.handlerVersionId,
      ],
    );
    return jobOut(result.rows[0]!);
  }

  private async hasActiveItemJob(identity: SpaceUserIdentity, sourceItemId: string, jobType: string) {
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM extraction_jobs
        WHERE space_id = $1
          AND source_item_id = $2
          AND job_type = $3
          AND status IN ('pending', 'running')
        LIMIT 1`,
      [identity.spaceId, sourceItemId, jobType],
    );
    return Boolean(result.rows[0]);
  }

  private async reindexItemForRetrieval(spaceId: string, itemId: string, trigger: string): Promise<void> {
    await reindexSourceItemAndEvidenceForRetrieval(this.db, { spaceId, itemId, trigger }).catch((error) => {
      process.stderr.write(
        `[source.retrieval] item reindex failed (${itemId}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
  }

  private async reindexEvidenceForRetrieval(spaceId: string, evidenceId: string, trigger: string): Promise<void> {
    await reindexExtractedEvidenceAndParentForRetrieval(this.db, { spaceId, evidenceId, trigger }).catch((error) => {
      process.stderr.write(
        `[source.retrieval] evidence reindex failed (${evidenceId}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
  }

  private async insertSummaryProposal(identity: SpaceUserIdentity, proposalType: string, title: string, summary: string, artifactId: string, evidenceIds: string[], sourceItemIds: string[]) {
    const sourceRefs = [
      { source_type: "artifact", source_id: artifactId, source_trust: "internal_system" },
      ...evidenceIds.map((id) => ({ source_type: "extracted_evidence", source_id: id, source_trust: "agent_inferred" })),
      ...sourceItemIds.map((id) => ({ source_type: "source_item", source_id: id, source_trust: "untrusted_external" })),
    ];
    const payload = proposalType === "knowledge_create"
      ? {
          operation: "create",
          knowledge_kind: "summary",
          title,
          content: summary,
          content_format: "markdown",
          visibility: "space_shared",
          tags: ["summary"],
          source_artifact_id: artifactId,
          source_refs: sourceRefs,
        }
      : {
          operation: "create",
          proposed_content: summary,
          memory_type: "experience",
          target_scope: "user",
          target_namespace: "source.summary",
          source_artifact_id: artifactId,
          provenance_entries: sourceRefs,
        };
    const row = await insertProposalRow(this.db, {
      spaceId: identity.spaceId,
      proposalType,
      title,
      payload,
      rationale: "Source summary generated a proposal without directly mutating memory or knowledge.",
      createdByUserId: identity.userId,
      visibility: "space_shared",
      riskLevel: "low",
    });
    return row.id;
  }
}

function booleanBody(value: unknown, field: string, fallback: boolean): boolean {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "boolean") return value;
  throw new HttpError(422, `${field} must be a boolean`);
}
