import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import type { Queryable } from "../routeUtils/common";
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
import { IntakeExtractionWorker } from "./extractionWorker";
import {
  bindingOut,
  buildSummary,
  connectionOut,
  connectorOut,
  evidenceLinkOut,
  evidenceOut,
  itemOut,
  jobOut,
  normalizeUrl,
  profileOut,
  sha256,
  sourceDomain,
  stringList,
} from "./intakeRepositoryMappers";
import {
  BINDING_COLUMNS,
  CONNECTION_COLUMNS,
  CONNECTOR_COLUMNS,
  EVIDENCE_COLUMNS,
  EVIDENCE_LINK_COLUMNS,
  ITEM_COLUMNS,
  JOB_COLUMNS,
  PROFILE_COLUMNS,
  type EvidenceLinkRow,
  type EvidenceRow,
  type ExtractionJobRow,
  type IntakeItemRow,
  type SourceConnectionRow,
  type SourceConnectorRow,
  type WorkspaceBindingRow,
  type WorkspaceProfileRow,
} from "./intakeRepositoryRows";
import {
  enforceSourceDerivedImportTarget,
  enforceSourceRetentionPolicy,
  normalizeSourceConnectionCreateGovernance,
  normalizeSourceConnectionReadGovernance,
  normalizeSourceConnectionUpdateGovernance,
} from "./sourceConsent";

export class PgIntakeRepository {
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

  async listConnections(identity: SpaceUserIdentity, filters: { status: string | null; limit: number; offset: number }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1", "deleted_at IS NULL"];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`status = $${params.length}`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string }>(`SELECT count(*)::text AS total FROM source_connections ${where}`, params);
    const rows = await this.db.query<SourceConnectionRow>(
      `SELECT ${CONNECTION_COLUMNS} FROM source_connections ${where}
       ORDER BY updated_at DESC, id DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(connectionOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createConnection(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const connectorKey = requiredString(body.connector_key, "connector_key");
    const connector = await this.db.query<{ id: string }>(
      `SELECT id FROM source_connectors WHERE connector_key = $1 AND status = 'active'`,
      [connectorKey],
    );
    if (!connector.rows[0]) throw new HttpError(404, "Source connector not found");
    const now = new Date().toISOString();
    const governance = normalizeSourceConnectionCreateGovernance(identity, body);
    const result = await this.db.query<SourceConnectionRow>(
      `INSERT INTO source_connections (
         id, space_id, connector_id, owner_user_id, credential_id, name, endpoint_url,
         status, fetch_frequency, capture_policy, trust_level, topic_hints_json,
         consent_json, policy_json, config_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7,
         'active', $8, $9, $10, $11::jsonb,
         $12::jsonb, $13::jsonb, $14::jsonb, $15, $15
       ) RETURNING ${CONNECTION_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        connector.rows[0].id,
        identity.userId,
        optionalString(body.credential_id),
        requiredString(body.name, "name"),
        optionalString(body.endpoint_url),
        optionalString(body.fetch_frequency) ?? "manual",
        governance.capturePolicy,
        governance.trustLevel,
        JSON.stringify(Array.isArray(body.topic_hints) ? body.topic_hints : null),
        JSON.stringify(governance.consent),
        JSON.stringify(governance.policy),
        JSON.stringify(objectValue(body.config)),
        now,
      ],
    );
    return connectionOut(result.rows[0]!);
  }

  async getConnection(identity: SpaceUserIdentity, connectionId: string) {
    const result = await this.db.query<SourceConnectionRow>(
      `SELECT ${CONNECTION_COLUMNS} FROM source_connections WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, connectionId],
    );
    return result.rows[0] ? connectionOut(result.rows[0]) : null;
  }

  async updateConnection(identity: SpaceUserIdentity, connectionId: string, body: Record<string, unknown>) {
    const existing = await this.getConnectionRow(identity, connectionId);
    if (!existing) throw new HttpError(404, "Source connection not found");
    const now = new Date().toISOString();
    const governance = normalizeSourceConnectionUpdateGovernance(identity, existing, body);
    const result = await this.db.query<SourceConnectionRow>(
      `UPDATE source_connections SET
         name = COALESCE($3, name),
         status = COALESCE($4, status),
         credential_id = CASE WHEN $5::boolean THEN $6 ELSE credential_id END,
         fetch_frequency = COALESCE($7, fetch_frequency),
         capture_policy = COALESCE($8, capture_policy),
         trust_level = COALESCE($9, trust_level),
         topic_hints_json = CASE WHEN $10::boolean THEN $11::jsonb ELSE topic_hints_json END,
         consent_json = CASE WHEN $12::boolean THEN $13::jsonb ELSE consent_json END,
         policy_json = CASE WHEN $14::boolean THEN $15::jsonb ELSE policy_json END,
         config_json = CASE WHEN $16::boolean THEN $17::jsonb ELSE config_json END,
         deleted_at = CASE WHEN $4 = 'archived' THEN $18::timestamptz ELSE deleted_at END,
         updated_at = $18
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
        now,
      ],
    );
    return connectionOut(result.rows[0]!);
  }

  async scanConnection(identity: SpaceUserIdentity, connectionId: string) {
    if (!(await this.getConnection(identity, connectionId))) throw new HttpError(404, "Source connection not found");
    const job = await this.createJob({ identity, connectionId, intakeItemId: null, jobType: "connection_scan", metadata: { created_by: "server" } });
    await this.db.query(`UPDATE source_connections SET last_checked_at = $3, updated_at = $3 WHERE space_id = $1 AND id = $2`, [identity.spaceId, connectionId, new Date().toISOString()]);
    return job;
  }

  async listItems(identity: SpaceUserIdentity, filters: {
    status: string | null;
    readStatus: string | null;
    contentState: string | null;
    connectionId: string | null;
    itemType: string | null;
    sourceDomain: string | null;
    createdAfter: string | null;
    occurredAfter: string | null;
    includeIgnored: boolean;
    includeArchived: boolean;
    q: string | null;
    limit: number;
    offset: number;
  }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1", "deleted_at IS NULL"];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    if (!filters.status && !filters.includeIgnored) clauses.push("status <> 'ignored'");
    if (!filters.status && !filters.includeArchived) clauses.push("status <> 'archived'");
    if (filters.readStatus) clauses.push(`read_status = ${add(filters.readStatus)}`);
    if (filters.contentState) clauses.push(`content_state = ${add(filters.contentState)}`);
    if (filters.connectionId) clauses.push(`connection_id = ${add(filters.connectionId)}`);
    if (filters.itemType) clauses.push(`item_type = ${add(filters.itemType)}`);
    if (filters.sourceDomain) clauses.push(`source_domain = ${add(filters.sourceDomain)}`);
    if (filters.createdAfter) clauses.push(`created_at >= ${add(filters.createdAfter)}::timestamptz`);
    if (filters.occurredAfter) clauses.push(`occurred_at >= ${add(filters.occurredAfter)}::timestamptz`);
    if (filters.q) clauses.push(`(title ILIKE ${add(`%${filters.q}%`)} OR excerpt ILIKE $${params.length} OR source_uri ILIKE $${params.length})`);
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string }>(`SELECT count(*)::text AS total FROM intake_items ${where}`, params);
    const rows = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS} FROM intake_items ${where}
       ORDER BY last_seen_at DESC, created_at DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
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
    const retention = body.queue_content === true ? "full_text" : "metadata_only";
    if (connection) enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, retention);
    const existing = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND deleted_at IS NULL AND (canonical_uri = $2 OR source_uri = $2) LIMIT 1`,
      [identity.spaceId, canonical],
    );
    const now = new Date().toISOString();
    let row = existing.rows[0];
    if (!row) {
      const inserted = await this.db.query<IntakeItemRow>(
        `INSERT INTO intake_items (
           id, space_id, connection_id, item_type, title, source_uri, canonical_uri,
           source_domain, status, read_status, content_state, retention_policy,
           metadata_json, first_seen_at, last_seen_at, created_at, updated_at
         ) VALUES (
           $1, $2, $3, 'external_url', $4, $5, $6,
           $7, 'new', 'unread', $8, $9,
           $10::jsonb, $11, $11, $11, $11
         ) RETURNING ${ITEM_COLUMNS}`,
        [
          randomUUID(),
          identity.spaceId,
          connectionId,
          optionalString(body.title) ?? canonical,
          url,
          canonical,
          sourceDomain(canonical),
          body.queue_content === true ? "content_queued" : "metadata_only",
          retention,
          JSON.stringify({ created_by: "manual_url" }),
          now,
        ],
      );
      row = inserted.rows[0]!;
    }
    if (body.queue_content === true) {
      await this.createJob({ identity, connectionId: row.connection_id, intakeItemId: row.id, jobType: "manual_url", metadata: { url: canonical } });
    }
    return itemOut(row);
  }

  async itemAction(identity: SpaceUserIdentity, itemId: string, body: Record<string, unknown>) {
    const item = await this.getItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Intake item not found");
    const action = requiredString(body.action, "action");
    if (action === "queue_content" || action === "archive_snapshot") {
      const contentState = action === "queue_content" ? "content_queued" : "snapshot_queued";
      const retention = action === "queue_content" ? "full_text" : "full_snapshot";
      await this.enforceItemRetentionPolicy(identity, item, retention);
      await this.db.query(
        `UPDATE intake_items SET content_state = $3, retention_policy = $4, updated_at = $5 WHERE space_id = $1 AND id = $2`,
        [identity.spaceId, itemId, contentState, retention, new Date().toISOString()],
      );
      await this.createJob({ identity, connectionId: item.connection_id, intakeItemId: item.id, jobType: action === "queue_content" ? "extract_text" : "snapshot", metadata: { action } });
      return this.getItem(identity, itemId);
    }
    if (action === "mark_selected" || action === "mark_ignored" || action === "read_later" || action === "mark_discussed") {
      const status = action === "mark_selected" ? "selected" : action === "mark_ignored" ? "ignored" : "triaged";
      const readStatus = action === "mark_discussed" ? "discussed" : item.read_status;
      await this.db.query(
        `UPDATE intake_items SET status = $3, read_status = $4, updated_at = $5 WHERE space_id = $1 AND id = $2`,
        [identity.spaceId, itemId, status, readStatus, new Date().toISOString()],
      );
      return this.getItem(identity, itemId);
    }
    if (action === "extract_evidence") {
      await this.createEvidence(identity, {
        intake_item_id: item.id,
        evidence_type: "excerpt",
        title: item.title,
        content_excerpt: item.excerpt ?? item.title,
        source_uri: item.source_uri,
        trust_level: "normal",
        extraction_method: "manual_action",
        confidence: 0.5,
        status: "candidate",
        metadata: { source: "intake_item_action" },
      });
      return this.getItem(identity, itemId);
    }
    throw new HttpError(422, "Unsupported intake action");
  }

  async listJobs(identity: SpaceUserIdentity, filters: {
    status: string | null;
    intakeItemId: string | null;
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
    if (filters.intakeItemId) {
      params.push(filters.intakeItemId);
      clauses.push(`intake_item_id = $${params.length}`);
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
    const worker = new IntakeExtractionWorker(this.db, this.config);
    await worker.runPendingJob(jobId, identity.spaceId);
    const result = await this.db.query<ExtractionJobRow>(
      `SELECT ${JOB_COLUMNS} FROM extraction_jobs WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, jobId],
    );
    if (!result.rows[0]) throw new HttpError(404, "Extraction job not found");
    return jobOut(result.rows[0]);
  }

  async listEvidence(identity: SpaceUserIdentity, filters: { status: string | null; evidenceType: string | null; intakeItemId: string | null; limit: number; offset: number }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1", "deleted_at IS NULL"];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    if (filters.evidenceType) clauses.push(`evidence_type = ${add(filters.evidenceType)}`);
    if (filters.intakeItemId) clauses.push(`intake_item_id = ${add(filters.intakeItemId)}`);
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
    if (status === "active") throw new HttpError(409, "Intake evidence remains candidate-only");
    const intakeItemId = optionalString(body.intake_item_id);
    const item = intakeItemId ? await this.getItemRow(identity, intakeItemId) : null;
    if (intakeItemId && !item) throw new HttpError(404, "Intake item not found");
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
         id, space_id, intake_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, content_hash, artifact_id,
         source_uri, source_title, source_author, occurred_at, trust_level,
         extraction_method, confidence, status, metadata_json, created_by_user_id,
         created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8, $9, $10,
         $11, $12, $13, $14::timestamptz, $15,
         $16, $17::float, $18, $19::jsonb, $20,
         $21, $21
       ) RETURNING ${EVIDENCE_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        intakeItemId,
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
    return evidenceOut(result.rows[0]!);
  }

  async getEvidence(identity: SpaceUserIdentity, evidenceId: string) {
    const row = await this.getEvidenceRow(identity, evidenceId);
    return row ? evidenceOut(row) : null;
  }

  async updateEvidence(identity: SpaceUserIdentity, evidenceId: string, body: Record<string, unknown>) {
    if (!(await this.getEvidenceRow(identity, evidenceId))) throw new HttpError(404, "Evidence not found");
    const status = optionalString(body.status);
    if (status === "active") throw new HttpError(409, "Intake evidence remains candidate-only");
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
    return evidenceOut(result.rows[0]!);
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
    const now = new Date().toISOString();
    const result = await this.db.query<EvidenceLinkRow>(
      `INSERT INTO evidence_links (
         id, space_id, evidence_id, target_type, target_id, link_type,
         status, confidence, reason, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::float, $9, $10, $11, $11)
       RETURNING ${EVIDENCE_LINK_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        evidence.id,
        requiredString(body.target_type, "target_type"),
        optionalString(body.target_id),
        optionalString(body.link_type) ?? "context_candidate",
        optionalString(body.status) ?? "active",
        numberValue(body.confidence),
        optionalString(body.reason),
        identity.userId,
        now,
      ],
    );
    return evidenceLinkOut(result.rows[0]!);
  }

  async listWorkspaceProfiles(identity: SpaceUserIdentity) {
    const rows = await this.db.query<WorkspaceProfileRow>(
      `SELECT ${PROFILE_COLUMNS} FROM workspace_intake_profiles WHERE space_id = $1 ORDER BY updated_at DESC, id DESC`,
      [identity.spaceId],
    );
    return rows.rows.map(profileOut);
  }

  async createWorkspaceProfile(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const now = new Date().toISOString();
    const result = await this.db.query<WorkspaceProfileRow>(
      `INSERT INTO workspace_intake_profiles (
         id, space_id, workspace_id, name, status, observation_policy, routing_policy_json,
         filters_json, extraction_policy_json, context_policy_json, created_by_user_id,
         created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'active', $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10, $11, $11)
       ON CONFLICT (space_id, workspace_id) DO UPDATE SET
         name = EXCLUDED.name,
         observation_policy = EXCLUDED.observation_policy,
         routing_policy_json = EXCLUDED.routing_policy_json,
         filters_json = EXCLUDED.filters_json,
         extraction_policy_json = EXCLUDED.extraction_policy_json,
         context_policy_json = EXCLUDED.context_policy_json,
         updated_at = EXCLUDED.updated_at
       RETURNING ${PROFILE_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        requiredString(body.workspace_id, "workspace_id"),
        optionalString(body.name) ?? "Default intake profile",
        optionalString(body.observation_policy) ?? "manual",
        JSON.stringify(objectValue(body.routing_policy)),
        JSON.stringify(objectValue(body.filters)),
        JSON.stringify(objectValue(body.extraction_policy)),
        JSON.stringify(objectValue(body.context_policy)),
        identity.userId,
        now,
      ],
    );
    return profileOut(result.rows[0]!);
  }

  async listWorkspaceBindings(identity: SpaceUserIdentity) {
    const rows = await this.db.query<WorkspaceBindingRow>(
      `SELECT ${BINDING_COLUMNS} FROM workspace_source_bindings WHERE space_id = $1 ORDER BY priority DESC, updated_at DESC, id DESC`,
      [identity.spaceId],
    );
    return rows.rows.map(bindingOut);
  }

  async createWorkspaceBinding(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    if (!(await this.getConnection(identity, requiredString(body.source_connection_id, "source_connection_id")))) {
      throw new HttpError(404, "Source connection not found");
    }
    const now = new Date().toISOString();
    const result = await this.db.query<WorkspaceBindingRow>(
      `INSERT INTO workspace_source_bindings (
         id, space_id, workspace_id, project_id, source_connection_id, binding_key,
         status, priority, filters_json, routing_policy_json, extraction_policy_json,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, 'active', $7::int, $8::jsonb, $9::jsonb, $10::jsonb, $11, $12, $12)
       RETURNING ${BINDING_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        requiredString(body.workspace_id, "workspace_id"),
        optionalString(body.project_id),
        requiredString(body.source_connection_id, "source_connection_id"),
        optionalString(body.binding_key) ?? "default",
        numberValue(body.priority) ?? 0,
        JSON.stringify(objectValue(body.filters)),
        JSON.stringify(objectValue(body.routing_policy)),
        JSON.stringify(objectValue(body.extraction_policy)),
        identity.userId,
        now,
      ],
    );
    return bindingOut(result.rows[0]!);
  }

  async createSummaryRun(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const evidenceIds = stringList(body.evidence_ids);
    const intakeItemIds = stringList(body.intake_item_ids);
    if (!evidenceIds.length && !intakeItemIds.length) throw new HttpError(422, "At least one evidence_id or intake_item_id is required");
    const evidenceRows = evidenceIds.length
      ? await this.db.query<EvidenceRow>(`SELECT ${EVIDENCE_COLUMNS} FROM extracted_evidence WHERE space_id = $1 AND id::text = ANY($2::text[]) AND deleted_at IS NULL`, [identity.spaceId, evidenceIds])
      : { rows: [] as EvidenceRow[] };
    const itemRows = intakeItemIds.length
      ? await this.db.query<IntakeItemRow>(`SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id::text = ANY($2::text[]) AND deleted_at IS NULL`, [identity.spaceId, intakeItemIds])
      : { rows: [] as IntakeItemRow[] };
    if (evidenceRows.rows.length !== evidenceIds.length || itemRows.rows.length !== intakeItemIds.length) throw new HttpError(404, "Summary input not found");
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
        optionalString(body.summary_goal) ?? "Intake evidence summary",
        summary,
        JSON.stringify(["markdown", "txt"]),
        now,
        JSON.stringify({ evidence_ids: evidenceIds, intake_item_ids: intakeItemIds, generated_by: "server" }),
        identity.userId,
      ],
    );
    const proposalIds: string[] = [];
    if (body.create_memory_proposal === true || body.create_memory_proposals === true) {
      proposalIds.push(await this.insertSummaryProposal(identity, "memory_create", "Summary memory", summary, artifactId, evidenceIds, intakeItemIds));
    }
    if (body.create_knowledge_proposal === true || body.create_knowledge_proposals === true) {
      proposalIds.push(await this.insertSummaryProposal(identity, "knowledge_create", "Summary knowledge", summary, artifactId, evidenceIds, intakeItemIds));
    }
    return { run_id: `summary:${artifactId}`, artifact_id: artifactId, proposal_ids: proposalIds, status: "succeeded", summary_preview: summary.slice(0, 500) };
  }

  private async enforceItemRetentionPolicy(identity: SpaceUserIdentity, item: IntakeItemRow, retention: "metadata_only" | "summary_only" | "full_text" | "full_snapshot") {
    if (!item.connection_id) return;
    const connection = await this.getConnectionRow(identity, item.connection_id);
    if (!connection) throw new HttpError(404, "Source connection not found");
    enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, retention);
  }

  private async enforceSummaryImportTargetPolicy(
    identity: SpaceUserIdentity,
    evidenceRows: EvidenceRow[],
    itemRows: IntakeItemRow[],
    target: "knowledge" | "memory_proposal",
  ) {
    const itemsById = new Map<string, IntakeItemRow>();
    for (const row of itemRows) {
      if (row.id) itemsById.set(row.id, row);
    }
    const evidenceItemIds = [
      ...new Set(
        evidenceRows
          .map((row) => row.intake_item_id)
          .filter((id): id is string => typeof id === "string" && id.length > 0 && !itemsById.has(id)),
      ),
    ];
    if (evidenceItemIds.length) {
      const evidenceItems = await this.db.query<IntakeItemRow>(
        `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id::text = ANY($2::text[]) AND deleted_at IS NULL`,
        [identity.spaceId, evidenceItemIds],
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
    const result = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, itemId],
    );
    return result.rows[0] ?? null;
  }

  private async getConnectionRow(identity: SpaceUserIdentity, connectionId: string) {
    const result = await this.db.query<SourceConnectionRow>(
      `SELECT ${CONNECTION_COLUMNS} FROM source_connections WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, connectionId],
    );
    return result.rows[0] ?? null;
  }

  private async getEvidenceRow(identity: SpaceUserIdentity, evidenceId: string) {
    const result = await this.db.query<EvidenceRow>(
      `SELECT ${EVIDENCE_COLUMNS} FROM extracted_evidence WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, evidenceId],
    );
    return result.rows[0] ?? null;
  }

  private async createJob(input: { identity: SpaceUserIdentity; connectionId: string | null; intakeItemId: string | null; jobType: string; metadata: Record<string, unknown> }) {
    const now = new Date().toISOString();
    const result = await this.db.query<ExtractionJobRow>(
      `INSERT INTO extraction_jobs (
         id, space_id, connection_id, intake_item_id, job_type, status,
         metadata_json, created_at
       ) VALUES ($1, $2, $3, $4, $5, 'pending', $6::jsonb, $7)
       RETURNING ${JOB_COLUMNS}`,
      [randomUUID(), input.identity.spaceId, input.connectionId, input.intakeItemId, input.jobType, JSON.stringify(input.metadata), now],
    );
    return jobOut(result.rows[0]!);
  }

  private async insertSummaryProposal(identity: SpaceUserIdentity, proposalType: string, title: string, summary: string, artifactId: string, evidenceIds: string[], intakeItemIds: string[]) {
    const now = new Date().toISOString();
    const sourceRefs = [
      { source_type: "artifact", source_id: artifactId, source_trust: "internal_system" },
      ...evidenceIds.map((id) => ({ source_type: "extracted_evidence", source_id: id, source_trust: "agent_inferred" })),
      ...intakeItemIds.map((id) => ({ source_type: "intake_item", source_id: id, source_trust: "untrusted_external" })),
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
          target_namespace: "intake.summary",
          source_artifact_id: artifactId,
          provenance_entries: sourceRefs,
        };
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO proposals (
         id, space_id, proposal_type, status, risk_level, urgency, preview,
         title, summary, payload_json, review_deadline, expires_at, created_at,
         updated_at, reviewed_at, reviewed_by, workspace_id, rationale,
         created_by_agent_id, created_by_user_id, required_approver_role,
         visibility, project_id
       ) VALUES (
         $1, $2, $3, 'pending', 'low', 'normal', false,
         $4, NULL, $5::jsonb, NULL, NULL, $6,
         $6, NULL, NULL, NULL, $7,
         NULL, $8, NULL,
         'space_shared', NULL
       ) RETURNING id`,
      [
        randomUUID(),
        identity.spaceId,
        proposalType,
        title,
        JSON.stringify(payload),
        now,
        "Intake summary generated a proposal without directly mutating memory or knowledge.",
        identity.userId,
      ],
    );
    return result.rows[0]!.id;
  }
}
