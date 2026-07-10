import { createHash, randomUUID } from "node:crypto";
import { writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import type { ServerConfig } from "../../config";
import type { Queryable } from "../routeUtils/common";
import { HttpError } from "../routeUtils/common";
import {
  CONNECTION_COLUMNS,
  connectionColumnsForAlias,
  type SourceConnectionRow,
} from "./sourceRepositoryRows";
import {
  excerpt,
  extractStructuredReaderContent,
  htmlTitle,
  stripHtml,
  type StructuredReaderContent,
} from "./contentParsing";
import { extractPdfReaderContent } from "./pdfExtract";
import { parseFeed } from "./feedParser";
import { arxivHtmlUrl, arxivPdfUrl, parseArxivFeed, parseArxivReference } from "./connectors/arxiv";
import { acquireArxivRequestSlot } from "./connectors/arxivThrottle";
import { fetchSource, type SourceFetchResult } from "./sourceFetch";
import { normalizeUrl, sourceDomain } from "./sourceRepositoryMappers";
import { linkEvidenceToBoundProjects, materializeProjectSourceItemLinks } from "./evidenceProjectLinker";
import {
  emitSourcePostProcessingDeepAnalysisEvent,
  emitSourcePostProcessingEvent,
} from "./postProcessing/eventEmitter";
import {
  reindexExtractedEvidenceAndParentForRetrieval,
  reindexSourceItemAndEvidenceForRetrieval,
} from "./retrievalIndexing";
import { computeNextCheckAt } from "./scanSchedule";
import {
  getSourceConnectionScanTask,
  sourceConnectionWithSchedule,
  upsertSourceConnectionScanTask,
} from "./sourceConnectionScheduler";
import {
  enforceSourceRetentionPolicy,
  normalizeSourceConnectionReadGovernance,
} from "./sourceConsent";
import { PgCustomSourceHandlerRepository } from "./customSources/customSourceHandlerRepository";
import { capturePolicyScanState } from "./capturePolicy";
import { inheritContentAccessGrants } from "../access/contentAccessInheritance";

interface ExtractionJobRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  source_item_id: string | null;
  source_object_type: string | null;
  source_object_id: string | null;
  job_type: string;
  status: string;
  metadata_json: Record<string, unknown> | null;
}

interface SourceItemRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  source_uri: string | null;
  canonical_uri: string | null;
  source_external_id: string | null;
  title: string | null;
  excerpt: string | null;
  author: string | null;
  occurred_at: unknown;
  content_state: string;
  visibility: string;
}

const JOB_COLUMNS = `
  id, space_id, connection_id, source_item_id, source_object_type, source_object_id,
  job_type, status, metadata_json
`;

const CONNECTION_SCAN_CHILD_JOB_LIMIT = 25;

interface ConnectionWithConnectorRow extends SourceConnectionRow {
  connector_key: string;
}

interface ScanCursor {
  etag?: string;
  last_modified?: string;
  last_guid?: string;
  last_published_at?: string;
}

export class SourceExtractionWorker {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  async runPendingJob(jobId: string, spaceId: string): Promise<ExtractionJobRow> {
    const now = new Date().toISOString();
    const claimed = await this.db.query<ExtractionJobRow>(
      `UPDATE extraction_jobs
          SET status = 'running',
              started_at = $3
        WHERE id = $1
          AND space_id = $2
          AND status = 'pending'
        RETURNING ${JOB_COLUMNS}`,
      [jobId, spaceId, now],
    );
    const job = claimed.rows[0];
    if (!job) {
      const current = await this.getJob(jobId, spaceId);
      if (!current) throw new HttpError(404, "Extraction job not found");
      if (current.status === "running") throw new HttpError(409, `ExtractionJob ${jobId} is already running`);
      if (["succeeded", "failed", "skipped"].includes(current.status)) return current;
      throw new HttpError(409, `Unexpected ExtractionJob status ${current.status}`);
    }

    let runChildrenAfterSuccess = false;
    try {
      if (job.job_type === "connection_scan") {
        await this.executeConnectionScan(job);
      } else if (job.job_type === "manual_url" || job.job_type === "extract_text") {
        await this.executeTextExtraction(job);
        await emitSourcePostProcessingDeepAnalysisEvent(this.db, {
          spaceId: job.space_id,
          sourceConnectionId: job.connection_id,
          sourceItemId: job.source_item_id,
          metadata: job.metadata_json,
        });
      } else if (job.job_type === "snapshot") {
        await this.executeSnapshot(job);
      } else if (
        ["normalize_activity", "normalize_artifact", "normalize_run_event"].includes(job.job_type)
      ) {
        await this.executeInternalNormalization(job);
      } else {
        throw new HttpError(422, `Unsupported pending job_type: ${job.job_type}`);
      }
      await this.finishJob(jobId, spaceId, "succeeded", null, null);
      runChildrenAfterSuccess = job.job_type === "connection_scan";
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const code = error instanceof HttpError ? String(error.statusCode) : "run_error";
      await this.finishJob(jobId, spaceId, "failed", code, message);
      if (job.job_type === "connection_scan" && job.connection_id) {
        await this.recordFailedConnectionScan(job);
      }
      if (job.source_item_id) {
        await this.db.query(
          `UPDATE source_items SET content_state = 'extraction_failed', updated_at = $3
           WHERE space_id = $1 AND id = $2`,
          [spaceId, job.source_item_id, new Date().toISOString()],
        );
      }
    }
    if (runChildrenAfterSuccess) {
      await this.runPendingConnectionScanChildren(job);
    }

    const updated = await this.getJob(jobId, spaceId);
    if (!updated) throw new HttpError(404, "Extraction job not found");
    return updated;
  }

  private async getJob(jobId: string, spaceId: string): Promise<ExtractionJobRow | null> {
    const result = await this.db.query<ExtractionJobRow>(
      `SELECT ${JOB_COLUMNS} FROM extraction_jobs WHERE id = $1 AND space_id = $2`,
      [jobId, spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async runPendingConnectionScanChildren(job: ExtractionJobRow): Promise<void> {
    const children = await this.db.query<{ id: string }>(
      `SELECT id
         FROM extraction_jobs
        WHERE space_id = $1
          AND status = 'pending'
          AND metadata_json->>'parent_job_id' = $2
        ORDER BY created_at ASC, id ASC
        LIMIT $3`,
      [job.space_id, job.id, CONNECTION_SCAN_CHILD_JOB_LIMIT],
    );
    for (const child of children.rows) {
      try {
        await this.runPendingJob(child.id, job.space_id);
      } catch (error) {
        if (error instanceof HttpError && error.statusCode === 409) continue;
        throw error;
      }
    }
  }

  private async queueFailedFollowUpsForConnection(
    job: ExtractionJobRow,
    connection: ConnectionWithConnectorRow,
    createdAt: string,
  ): Promise<void> {
    if (!this.isManualScan(job)) return;
    const policy = capturePolicyScanState(connection.capture_policy);
    if (!policy.followUpJobType) return;
    if (policy.retention !== "metadata_only") {
      enforceSourceRetentionPolicy(
        normalizeSourceConnectionReadGovernance(connection).policy,
        policy.retention,
      );
    }
    const failedItems = await this.db.query<{ id: string }>(
      `SELECT id
         FROM source_items
        WHERE space_id = $1
          AND connection_id = $2
          AND content_state = 'extraction_failed'
          AND deleted_at IS NULL
        ORDER BY updated_at ASC, id ASC
        LIMIT $3`,
      [job.space_id, connection.id, CONNECTION_SCAN_CHILD_JOB_LIMIT],
    );
    for (const item of failedItems.rows) {
      const hasActiveFollowUp = await this.hasActiveFollowUpJob(job.space_id, item.id, policy.followUpJobType);
      if (hasActiveFollowUp) continue;
      await this.db.query(
        `UPDATE source_items
            SET content_state = $3,
                retention_policy = CASE
                  WHEN retention_policy IN ('metadata_only', 'summary_only') THEN $4
                  ELSE retention_policy
                END,
                updated_at = $5
          WHERE space_id = $1
            AND id = $2
            AND content_state = 'extraction_failed'`,
        [job.space_id, item.id, policy.contentState, policy.retention, createdAt],
      );
      await this.createExtractionJob({
        spaceId: job.space_id,
        connectionId: connection.id,
        sourceItemId: item.id,
        sourceSnapshotId: null,
        jobType: policy.followUpJobType,
        metadata: {
          created_by: "connection_scan_retry",
          parent_job_id: job.id,
          retry_reason: "previous_extraction_failed",
        },
        createdAt,
      });
    }
  }

  private async finishJob(
    jobId: string,
    spaceId: string,
    status: string,
    errorCode: string | null,
    errorMessage: string | null,
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE extraction_jobs
          SET status = $3,
              completed_at = $4,
              error_code = $5,
              error_message = $6
        WHERE id = $1 AND space_id = $2`,
      [jobId, spaceId, status, now, errorCode, errorMessage],
    );
  }

  private async executeConnectionScan(job: ExtractionJobRow): Promise<void> {
    if (!job.connection_id) throw new HttpError(422, "connection_scan requires connection_id");
    const connection = await this.getConnection(job.space_id, job.connection_id);
    if (!connection.endpoint_url) throw new HttpError(422, "Source connection is missing endpoint_url");
    const cursor = scanCursor(connection.config_json);
    const headers: Record<string, string> = {};
    if (cursor.etag) headers["If-None-Match"] = cursor.etag;
    if (cursor.last_modified) headers["If-Modified-Since"] = cursor.last_modified;

    if (connection.connector_key === "arxiv") await acquireArxivRequestSlot();
    const response = await fetchSource(connection.endpoint_url, {
      headers,
      maxDownloadBytes: await this.maxDownloadBytes(job.space_id),
    });
    const completedAt = new Date().toISOString();
    if (response.notModified) {
      await this.queueFailedFollowUpsForConnection(job, connection, completedAt);
      await this.updateConnectionAfterScan(connection, cursor, completedAt, this.isManualScan(job));
      await this.updateJobStats(job, { seen: 0, created: 0, updated: 0, metadata: { not_modified: true } });
      return;
    }
    if (!response.ok) {
      throw new HttpError(502, `Failed to fetch source connection (${response.status})`);
    }
    if (!response.isText || response.text === null) {
      throw new HttpError(415, `Source connection returned unsupported binary content (${response.contentType ?? "unknown"})`);
    }

    const raw = response.text;
    const nextCursor = {
      ...cursor,
      etag: response.headers.get("etag") ?? cursor.etag,
      last_modified: response.headers.get("last-modified") ?? cursor.last_modified,
    };
    const result = connection.connector_key === "web_page"
      ? await this.scanWebPage(job, connection, raw, completedAt)
      : connection.connector_key === "arxiv"
        ? await this.scanArxiv(job, connection, raw, completedAt)
        : await this.scanFeed(job, connection, raw, completedAt);
    await this.updateConnectionAfterScan(connection, {
      ...nextCursor,
      ...result.cursor,
    }, completedAt, this.isManualScan(job));
    await this.updateJobStats(job, {
      seen: result.seen,
      created: result.created,
      updated: result.updated,
      metadata: {
        connector_key: connection.connector_key,
        endpoint_url: connection.endpoint_url,
      },
    });
    await emitSourcePostProcessingEvent(this.db, {
      spaceId: job.space_id,
      sourceConnectionId: job.connection_id,
      newItemCount: result.created,
    });
  }

  private async scanFeed(
    job: ExtractionJobRow,
    connection: ConnectionWithConnectorRow,
    raw: string,
    capturedAt: string,
  ): Promise<{ seen: number; created: number; updated: number; cursor: ScanCursor }> {
    if (!["rss", "atom"].includes(connection.connector_key)) {
      throw new HttpError(422, `Unsupported connection_scan connector: ${connection.connector_key}`);
    }
    const items = parseFeed(raw, connection.connector_key).slice(0, 100);
    let created = 0;
    let updated = 0;
    let lastGuid: string | undefined;
    let lastPublishedAt: string | undefined;
    for (const item of items) {
      if (!lastGuid && item.externalId) lastGuid = item.externalId;
      if (!lastPublishedAt && item.occurredAt) lastPublishedAt = item.occurredAt;
      const outcome = await this.upsertScannedItem({
        job,
        connection,
        itemType: "feed_entry",
        title: item.title,
        sourceUri: item.url,
        canonicalUri: safeNormalizeUrl(item.url),
        sourceExternalId: item.externalId,
        author: item.author,
        occurredAt: item.occurredAt,
        contentHash: sha256([
          item.externalId ?? "",
          item.url ?? "",
          item.title,
          item.excerpt ?? "",
          item.occurredAt ?? "",
        ].join("\n")),
        excerpt: item.excerpt,
        metadata: item.metadata,
        capturedAt,
      });
      if (outcome.created) created += 1;
      else updated += 1;
    }
    return {
      seen: items.length,
      created,
      updated,
      cursor: {
        last_guid: lastGuid,
        last_published_at: lastPublishedAt,
      },
    };
  }

  private async scanWebPage(
    job: ExtractionJobRow,
    connection: ConnectionWithConnectorRow,
    raw: string,
    capturedAt: string,
  ): Promise<{ seen: number; created: number; updated: number; cursor: ScanCursor }> {
    const canonical = safeNormalizeUrl(connection.endpoint_url);
    const text = stripHtml(raw).trim();
    const contentHash = sha256(raw);
    const outcome = await this.upsertScannedItem({
      job,
      connection,
      itemType: "external_url",
      title: htmlTitle(raw) ?? canonical ?? connection.endpoint_url ?? connection.name,
      sourceUri: connection.endpoint_url,
      canonicalUri: canonical,
      sourceExternalId: canonical ?? connection.endpoint_url,
      author: null,
      occurredAt: null,
      contentHash,
      excerpt: text ? text.slice(0, 2048) : null,
      metadata: { page_title: htmlTitle(raw), content_length: raw.length },
      capturedAt,
    });
    return {
      seen: 1,
      created: outcome.created ? 1 : 0,
      updated: outcome.created ? 0 : 1,
      cursor: { last_guid: canonical ?? connection.endpoint_url ?? undefined },
    };
  }

  private async scanArxiv(
    job: ExtractionJobRow,
    connection: ConnectionWithConnectorRow,
    raw: string,
    capturedAt: string,
  ): Promise<{ seen: number; created: number; updated: number; cursor: ScanCursor }> {
    const papers = parseArxivFeed(raw).slice(0, 100);
    let created = 0;
    let updated = 0;
    let lastGuid: string | undefined;
    let lastPublishedAt: string | undefined;
    for (const paper of papers) {
      if (!lastGuid) lastGuid = paper.arxiv_id;
      if (!lastPublishedAt) lastPublishedAt = paper.published_at ?? paper.updated_at ?? undefined;
      const outcome = await this.upsertScannedItem({
        job,
        connection,
        itemType: "feed_entry",
        title: paper.title,
        sourceUri: paper.abs_url,
        canonicalUri: safeNormalizeUrl(paper.abs_url),
        sourceExternalId: paper.arxiv_id,
        author: paper.authors.length ? paper.authors.join(", ").slice(0, 512) : null,
        occurredAt: paper.published_at ?? paper.updated_at,
        contentHash: sha256([
          paper.arxiv_id,
          paper.arxiv_version ?? "",
          paper.title,
          paper.summary ?? "",
          paper.updated_at ?? "",
        ].join("\n")),
        excerpt: paper.summary ? excerpt(paper.summary) : null,
        metadata: {
          arxiv_id: paper.arxiv_id,
          arxiv_version: paper.arxiv_version,
          authors: paper.authors,
          categories: paper.categories,
          primary_category: paper.primary_category,
          published_at: paper.published_at,
          updated_at: paper.updated_at,
          abs_url: paper.abs_url,
          html_url: paper.html_url,
          pdf_url: paper.pdf_url,
          doi: paper.doi,
          journal_ref: paper.journal_ref,
          comment: paper.comment,
        },
        capturedAt,
      });
      if (outcome.created) created += 1;
      else updated += 1;
    }
    return {
      seen: papers.length,
      created,
      updated,
      cursor: {
        last_guid: lastGuid,
        last_published_at: lastPublishedAt,
      },
    };
  }

  private async upsertScannedItem(input: {
    job: ExtractionJobRow;
    connection: ConnectionWithConnectorRow;
    itemType: "feed_entry" | "external_url";
    title: string;
    sourceUri: string | null;
    canonicalUri: string | null;
    sourceExternalId: string | null;
    author: string | null;
    occurredAt: string | null;
    contentHash: string;
    excerpt: string | null;
    metadata: Record<string, unknown>;
    capturedAt: string;
  }): Promise<{ itemId: string; created: boolean }> {
    const now = input.capturedAt;
    const existing = await this.db.query<{ id: string; content_state: string | null }>(
      `SELECT id, content_state
         FROM source_items
        WHERE space_id = $1
          AND deleted_at IS NULL
          AND (
            ($2::text IS NOT NULL AND canonical_uri = $2)
            OR ($3::text IS NOT NULL AND connection_id = $4 AND source_external_id = $3)
            OR ($5::text IS NOT NULL AND connection_id = $4 AND content_hash = $5)
          )
        LIMIT 1`,
      [
        input.job.space_id,
        input.canonicalUri,
        input.sourceExternalId,
        input.connection.id,
        input.contentHash,
      ],
    );
    const policy = capturePolicyScanState(input.connection.capture_policy);
    if (policy.retention !== "metadata_only") {
      enforceSourceRetentionPolicy(
        normalizeSourceConnectionReadGovernance(input.connection).policy,
        policy.retention,
      );
    }
    const metadata = {
      ...input.metadata,
      capture_method: "connection_scan",
      job_id: input.job.id,
      connector_key: input.connection.connector_key,
      connection_id: input.connection.id,
    };
    const existingItem = existing.rows[0];
    let itemId = existingItem?.id;
    let created = false;
    if (!itemId) {
      itemId = randomUUID();
      await this.db.query(
        `INSERT INTO source_items (
           id, space_id, connection_id, item_type, title, source_uri, canonical_uri,
           source_domain, source_external_id, author, occurred_at, first_seen_at,
           last_seen_at, content_hash, excerpt, content_state,
           retention_policy, metadata_json, created_at, updated_at,
           owner_user_id, visibility, access_level
         ) VALUES (
           $1, $2, $3, $4, $5, $6, $7,
           $8, $9, $10, $11::timestamptz, $12,
           $12, $13, $14, $15,
           $16, $17::jsonb, $12, $12,
           $18, $19, $20
         )`,
        [
          itemId,
          input.job.space_id,
          input.connection.id,
          input.itemType,
          input.title.slice(0, 1024),
          input.sourceUri,
          input.canonicalUri,
          sourceDomain(input.canonicalUri ?? input.sourceUri ?? ""),
          input.sourceExternalId,
          input.author,
          input.occurredAt,
          now,
          input.contentHash,
          input.excerpt,
          policy.contentState,
          policy.retention,
          JSON.stringify(metadata),
          input.connection.owner_user_id,
          input.connection.visibility,
          input.connection.access_level,
        ],
      );
      if (input.connection.visibility === "selected_users") await inheritContentAccessGrants(this.db, {
        spaceId: input.job.space_id,
        sourceResourceType: "source_connection",
        sourceResourceId: input.connection.id,
        targetResourceType: "source_item",
        targetResourceId: itemId,
        inheritedAt: now,
      });
      created = true;
    } else {
      await this.db.query(
        `UPDATE source_items
            SET title = $3,
                source_uri = COALESCE($4, source_uri),
                canonical_uri = COALESCE($5, canonical_uri),
                source_domain = COALESCE($6, source_domain),
                source_external_id = COALESCE($7, source_external_id),
                author = COALESCE($8, author),
                occurred_at = COALESCE($9::timestamptz, occurred_at),
                last_seen_at = $10,
                content_hash = $11,
                excerpt = COALESCE($12, excerpt),
                content_state = CASE
                  WHEN content_state IN ('metadata_only', 'excerpt_saved', 'extraction_failed') THEN $13
                  ELSE content_state
                END,
                retention_policy = CASE
                  WHEN retention_policy IN ('metadata_only', 'summary_only') THEN $14
                  ELSE retention_policy
                END,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || $15::jsonb,
                updated_at = $10
          WHERE space_id = $1 AND id = $2`,
        [
          input.job.space_id,
          itemId,
          input.title.slice(0, 1024),
          input.sourceUri,
          input.canonicalUri,
          sourceDomain(input.canonicalUri ?? input.sourceUri ?? ""),
          input.sourceExternalId,
          input.author,
          input.occurredAt,
          now,
          input.contentHash,
          input.excerpt,
          policy.contentState,
          policy.retention,
          JSON.stringify(metadata),
        ],
      );
    }

    const sourceSnapshotId = await this.createSourceSnapshot({
      spaceId: input.job.space_id,
      sourceItemId: itemId,
      connectionId: input.connection.id,
      snapshotType: "metadata",
      artifactId: null,
      contentHash: input.contentHash,
      sourceUri: input.sourceUri,
      captureMethod: "connection_scan",
      trustLevel: input.connection.trust_level,
      sourceVisibility: input.connection.visibility,
      metadata,
      capturedAt: now,
    });
    await materializeProjectSourceItemLinks(this.db, {
      spaceId: input.job.space_id,
      sourceItemId: itemId,
    });
    await linkEvidenceToBoundProjects(
      this.db,
      { spaceId: input.job.space_id, sourceItemId: itemId },
      { materializeSourceItemLinks: false },
    );
    const needsFollowUp =
      Boolean(policy.followUpJobType) &&
      (
        created ||
        existingItem?.content_state === "metadata_only" ||
        existingItem?.content_state === "excerpt_saved" ||
        existingItem?.content_state === "extraction_failed"
      );
    const hasActiveFollowUp = policy.followUpJobType
      ? await this.hasActiveFollowUpJob(input.job.space_id, itemId, policy.followUpJobType)
      : false;
    if (needsFollowUp && policy.followUpJobType && !hasActiveFollowUp) {
      await this.createExtractionJob({
        spaceId: input.job.space_id,
        connectionId: input.connection.id,
        sourceItemId: itemId,
        sourceSnapshotId,
        jobType: policy.followUpJobType,
        metadata: { created_by: "connection_scan", parent_job_id: input.job.id },
        createdAt: now,
      });
    }
    await this.reindexItemForRetrieval(input.job.space_id, itemId, "source_connection_scan");
    return { itemId, created };
  }

  private async executeTextExtraction(job: ExtractionJobRow): Promise<void> {
    if (!job.source_item_id) throw new HttpError(422, "extract_text requires source_item_id");
    const item = await this.getItem(job.space_id, job.source_item_id);
    if (!item?.source_uri) throw new HttpError(422, "Source item is missing source_uri");
    await this.enforceItemRetentionPolicy(job.space_id, item, "full_text");

    const resolved = await this.fetchItemSourceContent(job.space_id, item.source_uri);
    const response = resolved.response;
    let rawSnapshotId: string | null = null;
    let rawArtifactId: string | null = null;
    if (response.isPdf) {
      if (!response.bytes) throw new HttpError(415, "PDF response did not include binary content");
      rawArtifactId = await this.writeRawArtifact(job.space_id, item.id, item.visibility, item.title ?? "snapshot", {
        content: response.bytes,
        mimeType: "application/pdf",
      });
      rawSnapshotId = await this.createSourceSnapshot({
        spaceId: job.space_id,
        sourceItemId: item.id,
        connectionId: item.connection_id,
        snapshotType: "raw",
        artifactId: rawArtifactId,
        contentHash: sha256(response.bytes),
        sourceUri: item.source_uri,
        captureMethod: "full_text",
        trustLevel: "normal",
        sourceVisibility: item.visibility,
        metadata: { job_id: job.id, ...resolved.contentMeta },
        capturedAt: new Date().toISOString(),
      });
    }
    const readerContent = resolved.readerContent
      ?? await this.readerContentFromFetched(response, item.source_uri);
    const text = readerContent.plain_text;
    const evidenceExtractionMethod = response.isPdf ? "pdf_text_v1" : "full_text";
    const artifactId = await this.writeReaderDocumentArtifact(
      job.space_id,
      item.id,
      item.visibility,
      item.title ?? readerContent.title ?? "extracted",
      readerContent,
      resolved.contentMeta,
    );
    const contentHash = sha256(text);
    const now = new Date().toISOString();
    const sourceSnapshotId = await this.createSourceSnapshot({
      spaceId: job.space_id,
      sourceItemId: item.id,
      connectionId: item.connection_id,
      snapshotType: "extracted",
      artifactId,
      contentHash,
      sourceUri: item.source_uri,
      captureMethod: "full_text",
      trustLevel: "normal",
      sourceVisibility: item.visibility,
      metadata: {
        job_id: job.id,
        ...(rawSnapshotId ? { raw_source_snapshot_id: rawSnapshotId } : {}),
        ...resolved.contentMeta,
      },
      capturedAt: now,
    });

    await this.db.query(
      `UPDATE source_items
          SET content_state = 'content_saved',
              retention_policy = 'full_text',
              raw_artifact_id = COALESCE($6, raw_artifact_id),
              extracted_artifact_id = $3,
              content_hash = $4,
              updated_at = $5
        WHERE space_id = $1 AND id = $2`,
      [job.space_id, item.id, artifactId, contentHash, now, rawArtifactId],
    );
    const evidenceId = randomUUID();
    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, source_item_id, source_object_type, source_object_id,
         extraction_job_id, source_snapshot_id, evidence_type, title, content_excerpt,
         content_hash, artifact_id, source_uri, source_title,
         extraction_method, trust_level, confidence, status, metadata_json, created_at, updated_at,
         owner_user_id, visibility, access_level
       ) VALUES (
         $1, $2, $3, 'source_item', $3,
         $4, $5, 'document', $6, $7,
         $8, $9, $10, $11,
         $13, 'normal', 0.7, 'candidate', '{}'::jsonb, $12, $12,
         (SELECT owner_user_id FROM source_items WHERE space_id = $2 AND id = $3),
         (SELECT visibility FROM source_items WHERE space_id = $2 AND id = $3),
         (SELECT access_level FROM source_items WHERE space_id = $2 AND id = $3)
      )`,
      [
        evidenceId,
        job.space_id,
        item.id,
        job.id,
        sourceSnapshotId,
        item.title ?? "Extracted text",
        text.slice(0, 4000),
        contentHash,
        artifactId,
        item.source_uri,
        item.title,
        now,
        evidenceExtractionMethod,
      ],
    );
    if (item.visibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId: job.space_id,
      sourceResourceType: "source_item",
      sourceResourceId: item.id,
      targetResourceType: "extracted_evidence",
      targetResourceId: evidenceId,
      inheritedAt: now,
    });
    await linkEvidenceToBoundProjects(this.db, {
      spaceId: job.space_id,
      sourceItemId: item.id,
    });
    await this.reindexEvidenceForRetrieval(job.space_id, evidenceId, "source_text_extraction");

    await this.db.query(
      `UPDATE extraction_jobs SET source_snapshot_id = $3 WHERE id = $1 AND space_id = $2`,
      [job.id, job.space_id, sourceSnapshotId],
    );
  }

  private async executeSnapshot(job: ExtractionJobRow): Promise<void> {
    if (!job.source_item_id) throw new HttpError(422, "snapshot requires source_item_id");
    const item = await this.getItem(job.space_id, job.source_item_id);
    if (!item?.source_uri) throw new HttpError(422, "Source item is missing source_uri");
    await this.enforceItemRetentionPolicy(job.space_id, item, "full_snapshot");

    const resolved = await this.fetchItemSourceContent(job.space_id, item.source_uri);
    const response = resolved.response;
    const rawContent = this.rawContentFromFetched(response);
    const artifactId = await this.writeRawArtifact(job.space_id, item.id, item.visibility, item.title ?? "snapshot", rawContent);
    const contentHash = sha256(rawContent.content);
    const now = new Date().toISOString();
    const rawSnapshotId = await this.createSourceSnapshot({
      spaceId: job.space_id,
      sourceItemId: item.id,
      connectionId: item.connection_id,
      snapshotType: "raw",
      artifactId,
      contentHash,
      sourceUri: item.source_uri,
      captureMethod: "snapshot",
      trustLevel: "normal",
      sourceVisibility: item.visibility,
      metadata: { job_id: job.id, ...resolved.contentMeta },
      capturedAt: now,
    });
    await this.db.query(
      `UPDATE source_items
          SET content_state = 'snapshot_saved',
              retention_policy = 'full_snapshot',
              raw_artifact_id = $3,
              content_hash = $4,
              updated_at = $5
        WHERE space_id = $1 AND id = $2`,
      [job.space_id, item.id, artifactId, contentHash, now],
    );

    try {
      const readerContent = resolved.readerContent
        ?? await this.readerContentFromFetched(response, item.source_uri);
      const text = readerContent.plain_text;
      if (text || readerContent.content_json.content.length > 0) {
        const extractedId = await this.writeReaderDocumentArtifact(
          job.space_id,
          item.id,
          item.visibility,
          item.title ?? readerContent.title ?? "extracted",
          readerContent,
          resolved.contentMeta,
        );
        await this.createSourceSnapshot({
          spaceId: job.space_id,
          sourceItemId: item.id,
          connectionId: item.connection_id,
          snapshotType: "extracted",
          artifactId: extractedId,
          contentHash: sha256(text),
          sourceUri: item.source_uri,
          captureMethod: "snapshot",
          trustLevel: "normal",
          sourceVisibility: item.visibility,
          metadata: { job_id: job.id, raw_source_snapshot_id: rawSnapshotId, ...resolved.contentMeta },
          capturedAt: now,
        });
        await this.db.query(
          `UPDATE source_items
              SET extracted_artifact_id = $3,
                  content_state = 'content_saved',
                  retention_policy = 'full_snapshot',
                  content_hash = $4,
                  updated_at = $5
            WHERE space_id = $1 AND id = $2`,
          [job.space_id, item.id, extractedId, sha256(text), now],
        );
      }
    } catch {
      // Snapshot succeeded even when text extraction fails.
    }

    await this.db.query(
      `UPDATE extraction_jobs SET source_snapshot_id = $3 WHERE id = $1 AND space_id = $2`,
      [job.id, job.space_id, rawSnapshotId],
    );
  }

  private async executeInternalNormalization(job: ExtractionJobRow): Promise<void> {
    const sourceType = job.source_object_type;
    const sourceId = job.source_object_id;
    if (!sourceType || !sourceId) {
      throw new HttpError(422, "Internal normalization requires source_object_type/id");
    }
    const payload = await this.loadInternalSource(job.space_id, sourceType, sourceId);
    const now = new Date().toISOString();
    const itemId = randomUUID();
    await this.db.query(
      `INSERT INTO source_items (
         id, space_id, item_type, source_object_type, source_object_id,
         title, excerpt, content_state, retention_policy,
         metadata_json, created_at, updated_at, owner_user_id, visibility, access_level
       ) VALUES (
         $1, $2, $3, $3, $4,
         $5, $6, 'excerpt_saved', 'summary_only',
         $7::jsonb, $8, $8, $9, $10, $11
       )
       ON CONFLICT DO NOTHING`,
      [
        itemId,
        job.space_id,
        sourceType,
        sourceId,
        payload.title,
        payload.excerpt,
        JSON.stringify({ capture_method: "internal", job_id: job.id }),
        now,
        payload.ownerUserId,
        payload.visibility,
        payload.accessLevel,
      ],
    );
    if (payload.visibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId: job.space_id,
      sourceResourceType: payload.sourceResourceType,
      sourceResourceId: payload.sourceResourceId,
      targetResourceType: "source_item",
      targetResourceId: itemId,
      inheritedAt: now,
    });
    const evidenceId = randomUUID();
    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, source_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, extraction_method, trust_level,
         confidence, status, metadata_json, created_at, updated_at,
         owner_user_id, visibility, access_level
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8, 'internal_normalization', 'normal',
         0.8, 'candidate', '{}'::jsonb, $9, $9,
         $10, $11, $12
       )`,
      [
        evidenceId,
        job.space_id,
        itemId,
        sourceType,
        sourceId,
        payload.evidenceType,
        payload.title,
        payload.excerpt,
        now,
        payload.ownerUserId,
        payload.visibility,
        payload.accessLevel,
      ],
    );
    if (payload.visibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId: job.space_id,
      sourceResourceType: "source_item",
      sourceResourceId: itemId,
      targetResourceType: "extracted_evidence",
      targetResourceId: evidenceId,
      inheritedAt: now,
    });
    await this.db.query(
      `UPDATE extraction_jobs
          SET source_item_id = $3,
              items_seen = 1,
              items_created = 1
        WHERE id = $1 AND space_id = $2`,
      [job.id, job.space_id, itemId],
    );
    await this.reindexItemForRetrieval(job.space_id, itemId, "source_internal_normalization");
  }

  private async loadInternalSource(
    spaceId: string,
    sourceType: string,
    sourceId: string,
  ): Promise<{
    title: string;
    excerpt: string;
    evidenceType: string;
    ownerUserId: string | null;
    visibility: string;
    accessLevel: string;
    sourceResourceType: "activity" | "artifact" | "run";
    sourceResourceId: string;
  }> {
    if (sourceType === "activity_record") {
      const row = await this.db.query<{ title: string | null; content: string | null; owner_user_id: string | null; visibility: string; access_level: string }>(
        `SELECT title, content, owner_user_id, visibility, access_level FROM activity_records
          WHERE space_id = $1 AND id = $2 AND status NOT IN ('archived', 'failed')`,
        [spaceId, sourceId],
      );
      const activity = row.rows[0];
      if (!activity) throw new HttpError(404, "Activity record not found");
      return {
        title: activity.title ?? "Activity",
        excerpt: (activity.content ?? "").slice(0, 4000),
        evidenceType: "event",
        ownerUserId: activity.owner_user_id,
        visibility: activity.visibility,
        accessLevel: activity.access_level,
        sourceResourceType: "activity",
        sourceResourceId: sourceId,
      };
    }
    if (sourceType === "artifact") {
      const row = await this.db.query<{ title: string | null; content: string | null; owner_user_id: string | null; visibility: string; access_level: string }>(
        `SELECT title, content, owner_user_id, visibility, access_level FROM artifacts WHERE space_id = $1 AND id = $2`,
        [spaceId, sourceId],
      );
      const artifact = row.rows[0];
      if (!artifact) throw new HttpError(404, "Artifact not found");
      return {
        title: artifact.title ?? "Artifact",
        excerpt: (artifact.content ?? "").slice(0, 4000),
        evidenceType: "artifact",
        ownerUserId: artifact.owner_user_id,
        visibility: artifact.visibility,
        accessLevel: artifact.access_level,
        sourceResourceType: "artifact",
        sourceResourceId: sourceId,
      };
    }
    if (sourceType === "run_event") {
      const row = await this.db.query<{ event_type: string | null; payload_json: unknown; run_id: string; owner_user_id: string | null; visibility: string; access_level: string }>(
        `SELECT re.event_type, re.payload_json, re.run_id, r.owner_user_id, r.visibility, r.access_level
           FROM run_events re
           JOIN runs r ON r.space_id = re.space_id AND r.id = re.run_id
          WHERE re.space_id = $1 AND re.id = $2`,
        [spaceId, sourceId],
      );
      const event = row.rows[0];
      if (!event) throw new HttpError(404, "Run event not found");
      return {
        title: event.event_type ?? "Run event",
        excerpt: JSON.stringify(event.payload_json ?? {}).slice(0, 4000),
        evidenceType: "event",
        ownerUserId: event.owner_user_id,
        visibility: event.visibility,
        accessLevel: event.access_level,
        sourceResourceType: "run",
        sourceResourceId: event.run_id,
      };
    }
    throw new HttpError(422, `Unsupported internal source_object_type: ${sourceType}`);
  }

  /**
   * Fetches an item's content for extraction/snapshot. Non-arXiv URLs keep the
   * existing single-fetch behavior. arXiv abs/pdf/html URLs resolve HTML-first
   * candidates (html -> pdf -> original URL) and pre-validate reader extraction
   * so extraction can fall back from HTML to PDF.
   */
  private async fetchItemSourceContent(
    spaceId: string,
    sourceUri: string,
  ): Promise<{
    response: SourceFetchResult;
    readerContent: StructuredReaderContent | null;
    contentMeta: Record<string, unknown>;
  }> {
    const maxDownloadBytes = await this.maxDownloadBytes(spaceId);
    const arxivRef = parseArxivReference(sourceUri);
    if (!arxivRef) {
      const response = await fetchSource(sourceUri, { maxDownloadBytes });
      if (!response.ok) {
        throw new HttpError(502, `Failed to fetch source URL (${response.status})`);
      }
      return { response, readerContent: null, contentMeta: {} };
    }

    const candidates: Array<{ url: string; format: "html" | "pdf" | "auto" }> = [
      { url: arxivHtmlUrl(arxivRef.baseId), format: "html" },
      { url: arxivPdfUrl(arxivRef.baseId), format: "pdf" },
    ];
    if (!candidates.some((candidate) => candidate.url === sourceUri)) {
      candidates.push({ url: sourceUri, format: "auto" });
    }

    let lastError: unknown = null;
    let htmlFallbackReason: string | null = null;
    for (const candidate of candidates) {
      await acquireArxivRequestSlot();
      try {
        const response = await fetchSource(candidate.url, { maxDownloadBytes });
        if (!response.ok) {
          throw new HttpError(502, `Failed to fetch source URL (${response.status})`);
        }
        const format = candidate.format === "auto"
          ? (response.isPdf ? "pdf" : "html")
          : candidate.format;
        let readerContent: StructuredReaderContent;
        if (format === "html") {
          if (!response.isText || response.text === null) {
            throw new HttpError(415, `Unsupported source content type (${response.contentType ?? "unknown"})`);
          }
          readerContent = extractStructuredReaderContent(response.text, candidate.url);
          if (!readerContent.plain_text.trim()) {
            throw new HttpError(422, "HTML extraction produced no text");
          }
        } else {
          if (!response.isPdf || !response.bytes) {
            throw new HttpError(415, `Unsupported source content type (${response.contentType ?? "unknown"})`);
          }
          // Copy the bytes: pdf.js detaches the buffer it parses, and the
          // caller still writes response.bytes as the raw artifact.
          readerContent = await extractPdfReaderContent(response.bytes.slice(), candidate.url);
        }
        return {
          response,
          readerContent,
          contentMeta: {
            content_source_format: format,
            content_source_url: candidate.url,
            arxiv_id: arxivRef.baseId,
            ...(htmlFallbackReason
              ? { fallback_from: "html", fallback_reason: htmlFallbackReason.slice(0, 300) }
              : {}),
          },
        };
      } catch (error) {
        lastError = error;
        if (htmlFallbackReason === null) {
          htmlFallbackReason = error instanceof Error ? error.message : String(error);
        }
      }
    }
    if (lastError instanceof Error) throw lastError;
    throw new HttpError(502, "Failed to fetch arXiv source content");
  }

  private async getItem(spaceId: string, itemId: string): Promise<SourceItemRow | null> {
    const result = await this.db.query<SourceItemRow>(
      `SELECT id, space_id, connection_id, source_uri, canonical_uri, source_external_id,
              title, excerpt, author, occurred_at, content_state, visibility
         FROM source_items
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, itemId],
    );
    return result.rows[0] ?? null;
  }

  private async maxDownloadBytes(spaceId: string): Promise<number> {
    return (await new PgCustomSourceHandlerRepository(this.db, this.config).getRunnerSettingsForSpace(spaceId)).download_bytes_max;
  }

  private async enforceItemRetentionPolicy(
    spaceId: string,
    item: SourceItemRow,
    retention: "full_text" | "full_snapshot",
  ): Promise<void> {
    if (!item.connection_id) return;
    const result = await this.db.query<SourceConnectionRow>(
      `SELECT ${CONNECTION_COLUMNS} FROM source_connections WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, item.connection_id],
    );
    const connection = result.rows[0]
      ? sourceConnectionWithSchedule(
          result.rows[0],
          await getSourceConnectionScanTask(this.db, result.rows[0].id),
        )
      : null;
    if (!connection) throw new HttpError(404, "Source connection not found");
    enforceSourceRetentionPolicy(normalizeSourceConnectionReadGovernance(connection).policy, retention);
  }

  private async getConnection(spaceId: string, connectionId: string): Promise<ConnectionWithConnectorRow> {
    const result = await this.db.query<ConnectionWithConnectorRow>(
      `SELECT ${connectionColumnsForAlias("sc")}, c.connector_key
         FROM source_connections sc
         JOIN source_connectors c
           ON c.id = sc.connector_id
        WHERE sc.space_id = $1
          AND sc.id = $2
          AND sc.deleted_at IS NULL
          AND c.status = 'active'`,
      [spaceId, connectionId],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Source connection not found");
    const task = await getSourceConnectionScanTask(this.db, row.id);
    return sourceConnectionWithSchedule(row, task) as ConnectionWithConnectorRow;
  }

  private async updateConnectionAfterScan(
    connection: ConnectionWithConnectorRow,
    cursor: ScanCursor,
    completedAt: string,
    manualRun: boolean,
  ): Promise<void> {
    const config = record(connection.config_json);
    config.scan_cursor = compactCursor(cursor);
    const nextCheckAt = computeNextCheckAt(connection.fetch_frequency, completedAt, {
      manualRun,
      existingNextCheckAt: connection.next_check_at,
      scheduleRule: connection.schedule_rule_json,
    });
    await this.db.query(
      `UPDATE source_connections
          SET config_json = $3::jsonb,
              updated_at = $4
        WHERE space_id = $1 AND id = $2`,
      [
        connection.space_id,
        connection.id,
        JSON.stringify(config),
        completedAt,
      ],
    );
    await upsertSourceConnectionScanTask(this.db, {
      connection,
      nextRunAt: nextCheckAt,
      lastRunAt: completedAt,
      updatedAt: completedAt,
    });
  }

  private async recordFailedConnectionScan(job: ExtractionJobRow): Promise<void> {
    if (!job.connection_id) return;
    try {
      const connection = await this.getConnection(job.space_id, job.connection_id);
      await this.updateConnectionAfterScan(
        connection,
        scanCursor(connection.config_json),
        new Date().toISOString(),
        this.isManualScan(job),
      );
    } catch {
      // Preserve the original extraction job failure.
    }
  }

  private async updateJobStats(
    job: ExtractionJobRow,
    input: { seen: number; created: number; updated: number; metadata: Record<string, unknown> },
  ): Promise<void> {
    await this.db.query(
      `UPDATE extraction_jobs
          SET items_seen = $3,
              items_created = $4,
              items_updated = $5,
              metadata_json = COALESCE(metadata_json, '{}'::jsonb) || $6::jsonb
        WHERE id = $1 AND space_id = $2`,
      [
        job.id,
        job.space_id,
        input.seen,
        input.created,
        input.updated,
        JSON.stringify(input.metadata),
      ],
    );
  }

  private async createSourceSnapshot(input: {
    spaceId: string;
    sourceItemId: string | null;
    connectionId: string | null;
    snapshotType: "metadata" | "raw" | "extracted" | "summary";
    artifactId: string | null;
    contentHash: string | null;
    sourceUri: string | null;
    captureMethod: "manual" | "connection_scan" | "full_text" | "snapshot" | "internal";
    trustLevel: string;
    sourceVisibility: string;
    metadata: Record<string, unknown>;
    capturedAt: string;
  }): Promise<string> {
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO source_snapshots (
         id, space_id, source_item_id, connection_id, snapshot_type, artifact_id,
         content_hash, source_uri, capture_method, trust_level, metadata_json,
         captured_at, created_at, updated_at, owner_user_id, visibility, access_level
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11::jsonb,
         $12, $12, $12,
         COALESCE(
           (SELECT owner_user_id FROM source_items WHERE space_id = $2 AND id = $3),
           (SELECT owner_user_id FROM source_connections WHERE space_id = $2 AND id = $4)
         ),
         COALESCE(
           (SELECT visibility FROM source_items WHERE space_id = $2 AND id = $3),
           (SELECT visibility FROM source_connections WHERE space_id = $2 AND id = $4)
         ),
         COALESCE(
           (SELECT access_level FROM source_items WHERE space_id = $2 AND id = $3),
           (SELECT access_level FROM source_connections WHERE space_id = $2 AND id = $4)
         )
       )`,
      [
        id,
        input.spaceId,
        input.sourceItemId,
        input.connectionId,
        input.snapshotType,
        input.artifactId,
        input.contentHash,
        input.sourceUri,
        input.captureMethod,
        input.trustLevel,
        JSON.stringify(input.metadata),
        input.capturedAt,
      ],
    );
    if (input.sourceVisibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId: input.spaceId,
      sourceResourceType: input.sourceItemId ? "source_item" : "source_connection",
      sourceResourceId: input.sourceItemId ?? input.connectionId!,
      targetResourceType: "source_snapshot",
      targetResourceId: id,
      inheritedAt: input.capturedAt,
    });
    return id;
  }

  private async createExtractionJob(input: {
    spaceId: string;
    connectionId: string | null;
    sourceItemId: string | null;
    sourceSnapshotId: string | null;
    jobType: "extract_text" | "snapshot";
    metadata: Record<string, unknown>;
    createdAt: string;
  }): Promise<void> {
    await this.db.query(
      `INSERT INTO extraction_jobs (
         id, space_id, connection_id, source_item_id, source_snapshot_id,
         job_type, status, metadata_json, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7::jsonb, $8)`,
      [
        randomUUID(),
        input.spaceId,
        input.connectionId,
        input.sourceItemId,
        input.sourceSnapshotId,
        input.jobType,
        JSON.stringify(input.metadata),
        input.createdAt,
      ],
    );
  }

  private async hasActiveFollowUpJob(
    spaceId: string,
    sourceItemId: string,
    jobType: "extract_text" | "snapshot",
  ): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id
         FROM extraction_jobs
        WHERE space_id = $1
          AND source_item_id = $2
          AND job_type = $3
          AND status IN ('pending', 'running')
        ORDER BY created_at DESC, id DESC
        LIMIT 1`,
      [spaceId, sourceItemId, jobType],
    );
    return Boolean(result.rows[0]);
  }

  private isManualScan(job: ExtractionJobRow): boolean {
    return record(job.metadata_json).created_by === "manual_scan";
  }

  private async writeReaderDocumentArtifact(
    spaceId: string,
    sourceItemId: string,
    sourceVisibility: string,
    title: string,
    content: StructuredReaderContent,
    extraMetadata: Record<string, unknown> = {},
  ): Promise<string> {
    const artifactId = randomUUID();
    const relPath = join(spaceId, `${artifactId}.reader.json`);
    const absPath = join(this.config.artifactStorageRoot, relPath);
    const payload = JSON.stringify(content);
    await mkdir(join(this.config.artifactStorageRoot, spaceId), { recursive: true });
    await writeFile(absPath, payload, "utf8");
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, export_formats_json, canonical_format, preview, metadata_json,
         created_at, updated_at, visibility, access_level, owner_user_id, trust_level
       ) VALUES (
         $1, $2, 'source_reader_document', $3, $4, $5, 'application/json',
         true, $6::jsonb, 'reader_document_json', false, $7::jsonb,
         $8, $8,
         (SELECT visibility FROM source_items WHERE space_id = $2 AND id = $9),
         (SELECT access_level FROM source_items WHERE space_id = $2 AND id = $9),
         (SELECT owner_user_id FROM source_items WHERE space_id = $2 AND id = $9),
         'medium'
       )`,
      [
        artifactId,
        spaceId,
        title.slice(0, 512),
        payload,
        relPath,
        JSON.stringify(["json"]),
        JSON.stringify({
          schema_version: content.schema_version,
          kind: content.kind,
          extraction_method: content.extraction_method,
          image_policy: content.image_policy,
          image_count: content.image_count,
          source_uri: content.source_uri,
          ...extraMetadata,
        }),
        now,
        sourceItemId,
      ],
    );
    if (sourceVisibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId,
      sourceResourceType: "source_item",
      sourceResourceId: sourceItemId,
      targetResourceType: "artifact",
      targetResourceId: artifactId,
      inheritedAt: now,
    });
    return artifactId;
  }

  private async writeRawArtifact(
    spaceId: string,
    sourceItemId: string,
    sourceVisibility: string,
    title: string,
    input: { content: string | Uint8Array; mimeType: string },
  ): Promise<string> {
    const artifactId = randomUUID();
    const format = exportFormatForMime(input.mimeType);
    const relPath = join(spaceId, `${artifactId}.${format === "html" ? "raw" : format}`);
    const absPath = join(this.config.artifactStorageRoot, relPath);
    await mkdir(join(this.config.artifactStorageRoot, spaceId), { recursive: true });
    if (typeof input.content === "string") {
      await writeFile(absPath, input.content, "utf8");
    } else {
      await writeFile(absPath, input.content);
    }
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, export_formats_json, canonical_format, preview,
         created_at, updated_at, visibility, access_level, owner_user_id, trust_level
       ) VALUES (
         $1, $2, 'source_raw_snapshot', $3, NULL, $4, $5,
         false, $6::jsonb, $7, false,
         $8, $8,
         (SELECT visibility FROM source_items WHERE space_id = $2 AND id = $9),
         (SELECT access_level FROM source_items WHERE space_id = $2 AND id = $9),
         (SELECT owner_user_id FROM source_items WHERE space_id = $2 AND id = $9),
         'medium'
       )`,
      [
        artifactId,
        spaceId,
        title.slice(0, 512),
        relPath,
        input.mimeType,
        JSON.stringify([format]),
        format,
        now,
        sourceItemId,
      ],
    );
    if (sourceVisibility === "selected_users") await inheritContentAccessGrants(this.db, {
      spaceId,
      sourceResourceType: "source_item",
      sourceResourceId: sourceItemId,
      targetResourceType: "artifact",
      targetResourceId: artifactId,
      inheritedAt: now,
    });
    return artifactId;
  }

  private async readerContentFromFetched(
    response: SourceFetchResult,
    sourceUri: string,
  ): Promise<StructuredReaderContent> {
    if (response.isPdf) {
      if (!response.bytes) throw new HttpError(415, "PDF response did not include binary content");
      return extractPdfReaderContent(response.bytes, sourceUri);
    }
    if (response.isText && response.text !== null) {
      return extractStructuredReaderContent(response.text, sourceUri);
    }
    throw new HttpError(415, `Unsupported source content type (${response.contentType ?? "unknown"})`);
  }

  private rawContentFromFetched(
    response: SourceFetchResult,
  ): { content: string | Uint8Array; mimeType: string } {
    if (response.isPdf) {
      if (!response.bytes) throw new HttpError(415, "PDF response did not include binary content");
      return { content: response.bytes, mimeType: "application/pdf" };
    }
    if (response.isText && response.text !== null) {
      return { content: response.text, mimeType: response.contentType ?? "text/html" };
    }
    if (response.bytes) {
      return { content: response.bytes, mimeType: response.contentType ?? "application/octet-stream" };
    }
    throw new HttpError(415, `Unsupported source content type (${response.contentType ?? "unknown"})`);
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
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function exportFormatForMime(mimeType: string): string {
  const normalized = mimeType.toLowerCase().split(";")[0]?.trim();
  if (normalized === "application/pdf") return "pdf";
  if (normalized === "text/html" || normalized === "application/xhtml+xml") return "html";
  if (normalized === "application/json") return "json";
  if (normalized?.endsWith("+xml") || normalized === "application/xml") return "xml";
  if (normalized?.startsWith("text/")) return "txt";
  return "bin";
}

function scanCursor(configJson: unknown): ScanCursor {
  const cursor = record(record(configJson).scan_cursor);
  return {
    etag: stringValue(cursor.etag),
    last_modified: stringValue(cursor.last_modified),
    last_guid: stringValue(cursor.last_guid),
    last_published_at: stringValue(cursor.last_published_at),
  };
}

function compactCursor(cursor: ScanCursor): ScanCursor {
  const out: ScanCursor = {};
  if (cursor.etag) out.etag = cursor.etag;
  if (cursor.last_modified) out.last_modified = cursor.last_modified;
  if (cursor.last_guid) out.last_guid = cursor.last_guid;
  if (cursor.last_published_at) out.last_published_at = cursor.last_published_at;
  return out;
}

function safeNormalizeUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    return normalizeUrl(value);
  } catch {
    return null;
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
