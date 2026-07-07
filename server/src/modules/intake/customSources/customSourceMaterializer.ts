import { randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import type {
  CustomSourceHandlerOutput,
  SourcePolicyEnvelope,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../../config";
import type { Queryable } from "../../routeUtils/common";
import { sha256, sourceDomain } from "../intakeRepositoryMappers";
import { linkEvidenceToBoundProjects } from "../evidenceProjectLinker";
import { reindexIntakeItemAndEvidenceForRetrieval } from "../retrievalIndexing";
import {
  validateCustomSourceHandlerOutput,
  type CustomSourceContractValidationResult,
} from "./customSourceContractValidator";
import { effectiveCustomSourceLimits, type CustomSourceRunnerSettings } from "./customSourceRunner";

/**
 * Validates and materializes source implementation output (Level 2 recipes or
 * Level 3 Custom Source handlers) into Intake-owned tables only:
 * `intake_items`, `source_snapshots`, `extracted_evidence`, and `artifacts`.
 * Mirrors the validate-before-write / per-item best-effort pattern used by
 * `RunMaterializationService`
 * (server/src/modules/runs/materializationService.ts) — see
 * `.agent/architecture/DATABASE_AND_TRANSACTIONS.md#external-call-boundary`
 * for why file copies are not held inside a long-lived transaction.
 *
 * Acceptance (Phase 3): an invalid output never reaches any Intake write —
 * `validateCustomSourceHandlerOutput` runs to completion before the first
 * INSERT. A valid output writes only Intake objects and artifacts.
 */

export interface CustomSourceHandlerRunContext {
  runId: string;
  spaceId: string;
  sourceConnectionId: string;
  handlerVersionId: string;
}

export interface CustomSourceMaterializationResult {
  status: "succeeded" | "failed" | "validation_failed";
  itemsCreated: number;
  itemsUpdated: number;
  snapshotsCreated: number;
  evidenceCreated: number;
  errors: string[];
}

type SourceMaterializationKind = "custom_source_handler" | "source_recipe";

interface SourceMaterializationDescriptor {
  captureMethod: SourceMaterializationKind;
  implementationVersionMetadataKey: "handler_version_id" | "recipe_version_id";
  runMetadataKey: "handler_run_id" | "extraction_job_id";
  artifactPathSegment: string;
  snapshotArtifactType: string;
  outputArtifactType: string;
  snapshotTitlePrefix: string;
  outputTitlePrefix: string;
  outputRunLabel: string;
}

export class CustomSourceMaterializationService {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
    private readonly settings: CustomSourceRunnerSettings,
  ) {}

  async materialize(input: {
    run: CustomSourceHandlerRunContext;
    /** Shared envelope fields (`SourcePolicyEnvelopeSchema`) — a Level 3 `CustomSourcePolicyEnvelope` is a structural superset, so both recipe and handler callers pass their envelope directly. */
    policyEnvelope: SourcePolicyEnvelope;
    /** Absolute path to the run-local `files/` directory that contains referenced snapshot files. */
    sandboxFilesRoot: string;
    /** Raw, not-yet-validated content of the sandbox `output.json`. */
    rawOutputJson: unknown;
    /** False for Level 2 recipe scans, which have no `source_handler_runs` row to update (`run.runId` is the extraction job id there). Defaults to true. */
    recordHandlerRun?: boolean;
    /** Identifies which source implementation produced the validated output. Defaults to the Level 3 Custom Source handler path for backward compatibility. */
    sourceKind?: SourceMaterializationKind;
  }): Promise<CustomSourceMaterializationResult> {
    const recordHandlerRun = input.recordHandlerRun ?? true;
    const descriptor = sourceMaterializationDescriptor(input.sourceKind ?? "custom_source_handler");
    const validation = await validateCustomSourceHandlerOutput({
      raw: input.rawOutputJson,
      limits: effectiveCustomSourceLimits(this.settings, input.policyEnvelope.limits),
      allowedNetworkOrigins: input.policyEnvelope.allowed_network_origins,
      sandboxFilesRoot: input.sandboxFilesRoot,
    });

    if (!validation.ok) {
      if (recordHandlerRun) {
        await this.recordRunResult(input.run, {
          status: "validation_failed",
          validationResult: { errors: validation.errors },
          outputArtifactId: null,
        });
      }
      return {
        status: "validation_failed",
        itemsCreated: 0,
        itemsUpdated: 0,
        snapshotsCreated: 0,
        evidenceCreated: 0,
        errors: validation.errors,
      };
    }

    const retentionPolicy = normalizeRetentionPolicy(input.policyEnvelope.retention_policy);
    const retainedOutput = applyCustomSourceRetentionPolicy(validation.output, retentionPolicy);
    const retainedValidation = { ...validation, output: retainedOutput };
    const result = await this.materializeValidatedOutput(
      input.run,
      retainedValidation,
      input.sandboxFilesRoot,
      retentionPolicy,
      descriptor,
    );
    const outputArtifactId = await this.storeRawOutputArtifact(input.run, retainedOutput, descriptor);
    const status = result.errors.length > 0 ? "failed" : "succeeded";
    if (recordHandlerRun) {
      await this.recordRunResult(input.run, {
        status,
        validationResult: { warnings: validation.output.diagnostics.warnings, errors: result.errors },
        outputArtifactId,
      });
      await this.db.query(
        `UPDATE source_connections SET last_handler_run_id = $1 WHERE id = $2 AND space_id = $3`,
        [input.run.runId, input.run.sourceConnectionId, input.run.spaceId],
      );
    }

    return { status, ...result };
  }

  private async materializeValidatedOutput(
    run: CustomSourceHandlerRunContext,
    validation: Extract<CustomSourceContractValidationResult, { ok: true }>,
    sandboxFilesRoot: string,
    retentionPolicy: string,
    descriptor: SourceMaterializationDescriptor,
  ): Promise<{
    itemsCreated: number;
    itemsUpdated: number;
    snapshotsCreated: number;
    evidenceCreated: number;
    errors: string[];
  }> {
    const errors: string[] = [];
    let itemsCreated = 0;
    let itemsUpdated = 0;
    let snapshotsCreated = 0;
    let evidenceCreated = 0;

    for (const [index, item] of validation.output.items.entries()) {
      try {
        const { itemId, created } = await this.upsertItem(run, item, retentionPolicy, descriptor);
        if (created) itemsCreated++;
        else itemsUpdated++;

        for (const snapshot of item.snapshots) {
          await this.materializeSnapshot(run, itemId, snapshot, sandboxFilesRoot, descriptor);
          snapshotsCreated++;
        }
        for (const evidence of item.evidence) {
          await this.materializeEvidence(run, itemId, evidence, descriptor);
          evidenceCreated++;
        }
        if (item.evidence.length > 0) {
          await linkEvidenceToBoundProjects(this.db, {
            spaceId: run.spaceId,
            intakeItemId: itemId,
          });
        }
        await this.reindexItemForRetrieval(run.spaceId, itemId, "custom_source_materialization");
      } catch (error) {
        errors.push(
          `items[${index}] (${item.external_id}): ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }

    return { itemsCreated, itemsUpdated, snapshotsCreated, evidenceCreated, errors };
  }

  private async upsertItem(
    run: CustomSourceHandlerRunContext,
    item: CustomSourceHandlerOutput["items"][number],
    retentionPolicy: string,
    descriptor: SourceMaterializationDescriptor,
  ): Promise<{ itemId: string; created: boolean }> {
    const now = new Date().toISOString();
    const existing = await this.db.query<{ id: string; content_state: string }>(
      `SELECT id, content_state FROM intake_items
        WHERE space_id = $1 AND connection_id = $2 AND source_external_id = $3
        LIMIT 1`,
      [run.spaceId, run.sourceConnectionId, item.external_id],
    );
    const contentState = materializedItemContentState(item);
    const contentHash = sha256(item.excerpt ?? item.title ?? item.source_uri);
    const metadata = JSON.stringify({
      capture_method: descriptor.captureMethod,
      [descriptor.implementationVersionMetadataKey]: run.handlerVersionId,
      [descriptor.runMetadataKey]: run.runId,
      ...(item.metadata ?? {}),
    });
    // Column limits: title varchar(1024), excerpt varchar(2048), author varchar(512).
    const title = item.title.slice(0, 1024);
    const excerpt = item.excerpt?.slice(0, 2048) ?? null;
    const author = item.author?.slice(0, 512) ?? null;

    if (existing.rows[0]) {
      const itemId = existing.rows[0].id;
      await this.db.query(
        `UPDATE intake_items
            SET title = $3,
                source_uri = $4,
                excerpt = COALESCE($5, excerpt),
                author = COALESCE($6, author),
                occurred_at = COALESCE($7::timestamptz, occurred_at),
                content_hash = $8,
                last_seen_at = $9,
                content_state = CASE
                  WHEN content_state IN ('metadata_only', 'excerpt_saved', 'extraction_failed') THEN $10::varchar
                  WHEN content_state = 'content_saved'
                    AND $10::text <> 'content_saved'
                    AND NOT EXISTS (
                      SELECT 1 FROM source_snapshots
                       WHERE source_snapshots.space_id = $1
                         AND source_snapshots.intake_item_id = $2
                    )
                    THEN $10::varchar
                  ELSE content_state
                END,
                retention_policy = $12,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || $11::jsonb,
                updated_at = $9
          WHERE space_id = $1 AND id = $2`,
        [
          run.spaceId,
          itemId,
          title,
          item.source_uri,
          excerpt,
          author,
          item.published_at,
          contentHash,
          now,
          contentState,
          metadata,
          retentionPolicy,
        ],
      );
      return { itemId, created: false };
    }

    const itemId = randomUUID();
    await this.db.query(
      `INSERT INTO intake_items (
         id, space_id, connection_id, item_type, title, source_uri, canonical_uri,
         source_domain, source_external_id, author, occurred_at, first_seen_at,
         last_seen_at, content_hash, excerpt, status, read_status, content_state,
         retention_policy, metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, 'external_url', $4, $5, $5,
         $6, $7, $8, $9::timestamptz, $10,
         $10, $11, $12, 'new', 'unread', $13,
         $15, $14::jsonb, $10, $10
       )`,
      [
        itemId,
        run.spaceId,
        run.sourceConnectionId,
        title,
        item.source_uri,
        sourceDomain(item.source_uri),
        item.external_id,
        author,
        item.published_at,
        now,
        contentHash,
        excerpt,
        contentState,
        metadata,
        retentionPolicy,
      ],
    );
    return { itemId, created: true };
  }

  private async materializeSnapshot(
    run: CustomSourceHandlerRunContext,
    intakeItemId: string,
    snapshot: CustomSourceHandlerOutput["items"][number]["snapshots"][number],
    sandboxFilesRoot: string,
    descriptor: SourceMaterializationDescriptor,
  ): Promise<void> {
    const sourcePath = resolve(sandboxFilesRoot, snapshot.file_path);
    const bytes = await readFile(sourcePath);
    const artifactId = randomUUID();
    const extension = safeExtension(extname(snapshot.file_path));
    const relativePath = join(run.spaceId, descriptor.artifactPathSegment, `${artifactId}${extension}`);
    const absoluteTarget = resolve(this.config.artifactStorageRoot, relativePath);
    await mkdir(dirname(absoluteTarget), { recursive: true });
    await copyFile(sourcePath, absoluteTarget);
    const now = new Date().toISOString();

    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, export_formats_json, canonical_format, preview,
         created_at, updated_at, visibility, trust_level
       ) VALUES (
         $1, $2, $8, $3, NULL, $4, $5,
         false, $6::jsonb, NULL, false,
         $7, $7, 'space_shared', 'low'
       )`,
      [
        artifactId,
        run.spaceId,
        `${descriptor.snapshotTitlePrefix} (${snapshot.snapshot_type})`,
        relativePath,
        snapshot.mime_type || "application/octet-stream",
        JSON.stringify([extension.replace(".", "") || "bin"]),
        now,
        descriptor.snapshotArtifactType,
      ],
    );

    await this.db.query(
      `INSERT INTO source_snapshots (
         id, space_id, intake_item_id, connection_id, snapshot_type, artifact_id,
         content_hash, source_uri, capture_method, trust_level, metadata_json,
         captured_at, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, NULL, $10, 'untrusted', $8::jsonb,
         $9, $9
       )`,
      [
        randomUUID(),
        run.spaceId,
        intakeItemId,
        run.sourceConnectionId,
        normalizeSnapshotType(snapshot.snapshot_type),
        artifactId,
        sha256(bytes.toString("base64")),
        JSON.stringify({
          [descriptor.implementationVersionMetadataKey]: run.handlerVersionId,
          [descriptor.runMetadataKey]: run.runId,
          declared_snapshot_type: snapshot.snapshot_type,
        }),
        now,
        descriptor.captureMethod,
      ],
    );
  }

  private async materializeEvidence(
    run: CustomSourceHandlerRunContext,
    intakeItemId: string,
    evidence: CustomSourceHandlerOutput["items"][number]["evidence"][number],
    descriptor: SourceMaterializationDescriptor,
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, intake_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, content_hash,
         extraction_method, trust_level, confidence, status,
         metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, 'intake_item', $3,
         $4, $5, $6, $7,
         $11, 'untrusted', $8::float, 'candidate',
         $9::jsonb, $10, $10
       )`,
      [
        randomUUID(),
        run.spaceId,
        intakeItemId,
        normalizeEvidenceType(evidence.evidence_type),
        evidence.title.slice(0, 1024),
        evidence.content_excerpt?.slice(0, 4096) ?? null,
        evidence.content_excerpt ? sha256(evidence.content_excerpt) : null,
        evidence.confidence ?? 0.5,
        JSON.stringify({
          [descriptor.implementationVersionMetadataKey]: run.handlerVersionId,
          [descriptor.runMetadataKey]: run.runId,
        }),
        now,
        descriptor.captureMethod,
      ],
    );
  }

  private async storeRawOutputArtifact(
    run: CustomSourceHandlerRunContext,
    output: CustomSourceHandlerOutput,
    descriptor: SourceMaterializationDescriptor,
  ): Promise<string> {
    const artifactId = randomUUID();
    const content = JSON.stringify(output);
    const relativePath = join(run.spaceId, descriptor.artifactPathSegment, `${artifactId}.output.json`);
    const absolutePath = resolve(this.config.artifactStorageRoot, relativePath);
    await mkdir(dirname(absolutePath), { recursive: true });
    await writeFile(absolutePath, content, "utf8");
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, storage_path, mime_type,
         exportable, export_formats_json, canonical_format, preview,
         created_at, updated_at, visibility, trust_level
       ) VALUES (
         $1, $2, $7, $3, NULL, $4, 'application/json',
         true, $5::jsonb, 'json', false,
         $6, $6, 'space_shared', 'low'
       )`,
      [
        artifactId,
        run.spaceId,
        `${descriptor.outputTitlePrefix} (${descriptor.outputRunLabel} ${run.runId})`,
        relativePath,
        JSON.stringify(["json"]),
        now,
        descriptor.outputArtifactType,
      ],
    );
    return artifactId;
  }

  private async reindexItemForRetrieval(spaceId: string, itemId: string, trigger: string): Promise<void> {
    await reindexIntakeItemAndEvidenceForRetrieval(this.db, { spaceId, itemId, trigger }).catch((error) => {
      process.stderr.write(
        `[intake.retrieval] item reindex failed (${itemId}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
  }

  private async recordRunResult(
    run: CustomSourceHandlerRunContext,
    input: {
      status: "succeeded" | "failed" | "validation_failed";
      validationResult: Record<string, unknown>;
      outputArtifactId: string | null;
    },
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE source_handler_runs
          SET status = $3,
              output_artifact_id = COALESCE($4, output_artifact_id),
              validation_result_json = $5::jsonb,
              completed_at = $6
        WHERE id = $1 AND space_id = $2`,
      [run.runId, run.spaceId, input.status, input.outputArtifactId, JSON.stringify(input.validationResult), now],
    );
  }
}

const ALLOWED_SNAPSHOT_TYPES = new Set(["metadata", "raw", "extracted", "summary"]);
function sourceMaterializationDescriptor(kind: SourceMaterializationKind): SourceMaterializationDescriptor {
  if (kind === "source_recipe") {
    return {
      captureMethod: "source_recipe",
      implementationVersionMetadataKey: "recipe_version_id",
      runMetadataKey: "extraction_job_id",
      artifactPathSegment: "source-recipe",
      snapshotArtifactType: "intake_source_recipe_snapshot",
      outputArtifactType: "intake_source_recipe_output",
      snapshotTitlePrefix: "Source Recipe snapshot",
      outputTitlePrefix: "Source Recipe output",
      outputRunLabel: "extraction_job_id",
    };
  }
  return {
    captureMethod: "custom_source_handler",
    implementationVersionMetadataKey: "handler_version_id",
    runMetadataKey: "handler_run_id",
    artifactPathSegment: "custom-source",
    snapshotArtifactType: "intake_custom_source_snapshot",
    outputArtifactType: "intake_custom_source_output",
    snapshotTitlePrefix: "Custom Source snapshot",
    outputTitlePrefix: "Custom Source handler output",
    outputRunLabel: "run",
  };
}

function normalizeSnapshotType(declared: string): string {
  if (ALLOWED_SNAPSHOT_TYPES.has(declared)) return declared;
  const lowered = declared.toLowerCase();
  if (lowered.includes("extract")) return "extracted";
  if (lowered.includes("summary")) return "summary";
  if (lowered.includes("raw")) return "raw";
  return "metadata";
}

const ALLOWED_EVIDENCE_TYPES = new Set([
  "document",
  "excerpt",
  "event",
  "log",
  "artifact",
  "claim",
  "summary",
]);
function normalizeEvidenceType(declared: string): string {
  return ALLOWED_EVIDENCE_TYPES.has(declared) ? declared : "excerpt";
}

function safeExtension(value: string): string {
  return value && /^[.][a-zA-Z0-9_-]{1,16}$/.test(value) ? value : "";
}

// intake_items.retention_policy CHECK constraint values (server/migrations/0001_baseline.sql).
const ALLOWED_RETENTION_POLICIES = new Set([
  "metadata_only",
  "summary_only",
  "full_text",
  "full_snapshot",
  "archived",
]);
/** Falls back to the narrowest retention (metadata_only) for an unrecognized value, never to full_text — a hardcoded 'full_text' would silently widen retention beyond what Space/source policy allows. */
function normalizeRetentionPolicy(declared: string): string {
  return ALLOWED_RETENTION_POLICIES.has(declared) ? declared : "metadata_only";
}

function materializedItemContentState(item: CustomSourceHandlerOutput["items"][number]): "metadata_only" | "excerpt_saved" | "content_saved" {
  if (item.snapshots.length > 0) return "content_saved";
  if (item.excerpt) return "excerpt_saved";
  return "metadata_only";
}

export function applyCustomSourceRetentionPolicy(
  output: CustomSourceHandlerOutput,
  retentionPolicy: string,
): CustomSourceHandlerOutput {
  const allowsText = retentionPolicy === "summary_only" ||
    retentionPolicy === "full_text" ||
    retentionPolicy === "full_snapshot" ||
    retentionPolicy === "archived";
  const allowsSnapshots = retentionPolicy === "full_snapshot" || retentionPolicy === "archived";

  return {
    ...output,
    items: output.items.map((item) => ({
      ...item,
      excerpt: allowsText ? item.excerpt : null,
      metadata: allowsText ? item.metadata : null,
      snapshots: allowsSnapshots ? item.snapshots : [],
      evidence: allowsText ? item.evidence : [],
    })),
  };
}
