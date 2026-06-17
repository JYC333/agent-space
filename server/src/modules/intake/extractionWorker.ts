import { createHash, randomUUID } from "node:crypto";
import { writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import type { ServerConfig } from "../../config";
import type { Queryable } from "../routeUtils/common";
import { HttpError } from "../routeUtils/common";

interface ExtractionJobRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  intake_item_id: string | null;
  source_object_type: string | null;
  source_object_id: string | null;
  job_type: string;
  status: string;
  metadata_json: Record<string, unknown> | null;
}

interface IntakeItemRow {
  id: string;
  space_id: string;
  source_uri: string | null;
  title: string | null;
  content_state: string;
}

const JOB_COLUMNS = `
  id, space_id, connection_id, intake_item_id, source_object_type, source_object_id,
  job_type, status, metadata_json
`;

export class IntakeExtractionWorker {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  async runPendingJob(jobId: string, spaceId: string): Promise<ExtractionJobRow> {
    const now = new Date().toISOString();
    const claimed = await this.db.query<ExtractionJobRow>(
      `UPDATE extraction_jobs
          SET status = 'running',
              started_at = $3,
              updated_at = $3
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

    try {
      if (job.job_type === "extract_text") {
        await this.executeTextExtraction(job);
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
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const code = error instanceof HttpError ? String(error.statusCode) : "run_error";
      await this.finishJob(jobId, spaceId, "failed", code, message);
      if (job.intake_item_id) {
        await this.db.query(
          `UPDATE intake_items SET content_state = 'extraction_failed', updated_at = $3
           WHERE space_id = $1 AND id = $2`,
          [spaceId, job.intake_item_id, new Date().toISOString()],
        );
      }
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
              error_message = $6,
              updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [jobId, spaceId, status, now, errorCode, errorMessage],
    );
  }

  private async executeTextExtraction(job: ExtractionJobRow): Promise<void> {
    if (!job.intake_item_id) throw new HttpError(422, "extract_text requires intake_item_id");
    const item = await this.getItem(job.space_id, job.intake_item_id);
    if (!item?.source_uri) throw new HttpError(422, "Intake item is missing source_uri");

    const response = await fetch(item.source_uri, { redirect: "follow" });
    if (!response.ok) {
      throw new HttpError(502, `Failed to fetch source URL (${response.status})`);
    }
    const raw = await response.text();
    const text = stripHtml(raw).trim();
    const artifactId = await this.writeTextArtifact(job.space_id, item.title ?? "extracted", text);
    const contentHash = sha256(text);
    const now = new Date().toISOString();

    await this.db.query(
      `UPDATE intake_items
          SET content_state = 'content_saved',
              extracted_artifact_id = $3,
              content_hash = $4,
              updated_at = $5
        WHERE space_id = $1 AND id = $2`,
      [job.space_id, item.id, artifactId, contentHash, now],
    );

    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, intake_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, content_hash, artifact_id,
         extraction_method, confidence, status, metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, 'intake_item', $3,
         'text', $4, $5, $6, $7,
         'full_text', 0.7, 'candidate', '{}'::jsonb, $8, $8
       )`,
      [
        randomUUID(),
        job.space_id,
        item.id,
        item.title ?? "Extracted text",
        text.slice(0, 4000),
        contentHash,
        artifactId,
        now,
      ],
    );
  }

  private async executeSnapshot(job: ExtractionJobRow): Promise<void> {
    if (!job.intake_item_id) throw new HttpError(422, "snapshot requires intake_item_id");
    const item = await this.getItem(job.space_id, job.intake_item_id);
    if (!item?.source_uri) throw new HttpError(422, "Intake item is missing source_uri");

    const response = await fetch(item.source_uri, { redirect: "follow" });
    if (!response.ok) {
      throw new HttpError(502, `Failed to fetch source URL (${response.status})`);
    }
    const raw = await response.text();
    const artifactId = await this.writeRawArtifact(job.space_id, item.title ?? "snapshot", raw);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE intake_items
          SET content_state = 'snapshot_saved',
              raw_artifact_id = $3,
              updated_at = $4
        WHERE space_id = $1 AND id = $2`,
      [job.space_id, item.id, artifactId, now],
    );

    try {
      const text = stripHtml(raw).trim();
      if (text) {
        const extractedId = await this.writeTextArtifact(job.space_id, item.title ?? "extracted", text);
        await this.db.query(
          `UPDATE intake_items
              SET extracted_artifact_id = $3,
                  content_state = 'content_saved',
                  content_hash = $4,
                  updated_at = $5
            WHERE space_id = $1 AND id = $2`,
          [job.space_id, item.id, extractedId, sha256(text), now],
        );
      }
    } catch {
      // Snapshot succeeded even when text extraction fails.
    }
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
      `INSERT INTO intake_items (
         id, space_id, item_type, source_object_type, source_object_id,
         title, excerpt, status, read_status, content_state, retention_policy,
         metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, 'internal', $3, $4,
         $5, $6, 'active', 'unread', 'normalized', 'standard',
         $7::jsonb, $8, $8
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
      ],
    );
    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, intake_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, extraction_method, confidence,
         status, metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8, 'internal_normalization', 0.8,
         'candidate', '{}'::jsonb, $9, $9
       )`,
      [
        randomUUID(),
        job.space_id,
        itemId,
        sourceType,
        sourceId,
        payload.evidenceType,
        payload.title,
        payload.excerpt,
        now,
      ],
    );
    await this.db.query(
      `UPDATE extraction_jobs
          SET intake_item_id = $3,
              items_seen = 1,
              items_created = 1,
              updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [job.id, job.space_id, itemId, now],
    );
  }

  private async loadInternalSource(
    spaceId: string,
    sourceType: string,
    sourceId: string,
  ): Promise<{ title: string; excerpt: string; evidenceType: string }> {
    if (sourceType === "activity_record") {
      const row = await this.db.query<{ title: string | null; content: string | null }>(
        `SELECT title, content FROM activity_records WHERE space_id = $1 AND id = $2`,
        [spaceId, sourceId],
      );
      const activity = row.rows[0];
      if (!activity) throw new HttpError(404, "Activity record not found");
      return {
        title: activity.title ?? "Activity",
        excerpt: (activity.content ?? "").slice(0, 4000),
        evidenceType: "event",
      };
    }
    if (sourceType === "artifact") {
      const row = await this.db.query<{ title: string | null; content: string | null }>(
        `SELECT title, content FROM artifacts WHERE space_id = $1 AND id = $2`,
        [spaceId, sourceId],
      );
      const artifact = row.rows[0];
      if (!artifact) throw new HttpError(404, "Artifact not found");
      return {
        title: artifact.title ?? "Artifact",
        excerpt: (artifact.content ?? "").slice(0, 4000),
        evidenceType: "artifact",
      };
    }
    if (sourceType === "run_event") {
      const row = await this.db.query<{ event_type: string | null; payload_json: unknown }>(
        `SELECT event_type, payload_json FROM run_events WHERE space_id = $1 AND id = $2`,
        [spaceId, sourceId],
      );
      const event = row.rows[0];
      if (!event) throw new HttpError(404, "Run event not found");
      return {
        title: event.event_type ?? "Run event",
        excerpt: JSON.stringify(event.payload_json ?? {}).slice(0, 4000),
        evidenceType: "event",
      };
    }
    throw new HttpError(422, `Unsupported internal source_object_type: ${sourceType}`);
  }

  private async getItem(spaceId: string, itemId: string): Promise<IntakeItemRow | null> {
    const result = await this.db.query<IntakeItemRow>(
      `SELECT id, space_id, source_uri, title, content_state
         FROM intake_items
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, itemId],
    );
    return result.rows[0] ?? null;
  }

  private async writeTextArtifact(spaceId: string, title: string, content: string): Promise<string> {
    const artifactId = randomUUID();
    const relPath = join(spaceId, `${artifactId}.txt`);
    const absPath = join(this.config.artifactStorageRoot, relPath);
    await mkdir(join(this.config.artifactStorageRoot, spaceId), { recursive: true });
    await writeFile(absPath, content, "utf8");
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, preview, created_at, updated_at, visibility, trust_level
       ) VALUES (
         $1, $2, 'intake_extracted_text', $3, $4, $5, 'text/plain',
         true, false, $6, $6, 'space_shared', 'medium'
       )`,
      [artifactId, spaceId, title, content.slice(0, 10000), relPath, now],
    );
    return artifactId;
  }

  private async writeRawArtifact(spaceId: string, title: string, content: string): Promise<string> {
    const artifactId = randomUUID();
    const relPath = join(spaceId, `${artifactId}.raw`);
    const absPath = join(this.config.artifactStorageRoot, relPath);
    await mkdir(join(this.config.artifactStorageRoot, spaceId), { recursive: true });
    await writeFile(absPath, content, "utf8");
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, preview, created_at, updated_at, visibility, trust_level
       ) VALUES (
         $1, $2, 'intake_raw_snapshot', $3, NULL, $4, 'text/html',
         false, false, $6, $6, 'space_shared', 'medium'
       )`,
      [artifactId, spaceId, title, relPath, now],
    );
    return artifactId;
  }
}

function stripHtml(input: string): string {
  return input
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
