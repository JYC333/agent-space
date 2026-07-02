import { randomUUID } from "node:crypto";
import { createHash } from "node:crypto";
import { stat, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { ServerConfig } from "../../config";
import { HttpError, dateIso, objectValue, optionalString, type Queryable, type SpaceUserIdentity } from "../routeUtils/common";
import { normalizeSourceConnectionReadGovernance, enforceSourceDerivedImportTarget } from "./sourceConsent";
import type { IntakeItemRow } from "./intakeRepositoryRows";
import { ITEM_COLUMNS } from "./intakeRepositoryRows";
import { isSpaceOwnerOrAdmin } from "../access/roles";
import { artifactVisibleSql } from "../access/visibility";
import { insertProposalRow } from "../proposals/reviewPackets";
import { canAccessProject } from "../memory/projectAccess";
import { parseStructuredReaderContent, type ReaderPmDoc } from "./contentParsing";

/**
 * Normalizes raw plainText into the canonical form used by the Tiptap reader:
 * trim → split on double-newlines → trim each paragraph → rejoin with ' '.
 *
 * This is the same text the editor produces via `textBetween(0, size, ' ')`,
 * so text_range offsets, content_hash, before_context, and after_context must
 * all be computed from this normalized form.
 */
export function normalizeReaderText(text: string | null | undefined): string {
  const trimmed = text?.trim() ?? "";
  if (!trimmed) return "";
  return trimmed
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .join(" ");
}

function plainTextToPmDoc(text: string | null | undefined): ReaderPmDoc {
  const trimmed = text?.trim();
  if (!trimmed) {
    return { type: "doc", content: [{ type: "paragraph" }] };
  }
  const paragraphs = trimmed.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return {
    type: "doc",
    content: paragraphs.map((p) => ({
      type: "paragraph",
      content: [{ type: "text", text: p }],
    })),
  };
}

function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

// ── Safe artifact text reader ─────────────────────────────────────────────────

interface ArtifactTextRow {
  id: string;
  space_id: string;
  artifact_type: string;
  title: string;
  content: string | null;
  storage_path: string | null;
  mime_type: string | null;
  visibility: string;
  owner_user_id: string | null;
}

async function loadVisibleArtifactForReader(
  db: Queryable,
  spaceId: string,
  userId: string,
  artifactId: string,
): Promise<ArtifactTextRow | null> {
  const result = await db.query<ArtifactTextRow>(
    `SELECT a.id, a.space_id, a.artifact_type, a.title, a.content, a.storage_path, a.mime_type, a.visibility, a.owner_user_id
       FROM artifacts a
      WHERE a.id = $1 AND a.space_id = $2
        AND ${artifactVisibleSql({ userExpr: "$3" })}`,
    [artifactId, spaceId, userId],
  );
  return result.rows[0] ?? null;
}

async function assertArtifactReadable(
  db: Queryable,
  identity: SpaceUserIdentity,
  artifactId: string,
  notFoundMessage: string,
): Promise<void> {
  const artifact = await loadVisibleArtifactForReader(db, identity.spaceId, identity.userId, artifactId);
  if (!artifact) throw new HttpError(404, notFoundMessage);
}

interface ArtifactReaderContent {
  text: string;
  title: string;
  contentJson?: ReaderPmDoc;
}

async function readArtifactForReader(
  db: Queryable,
  config: Pick<ServerConfig, "artifactStorageRoot" | "sandboxRoot">,
  spaceId: string,
  userId: string,
  artifactId: string,
): Promise<ArtifactReaderContent | null> {
  const row = await loadVisibleArtifactForReader(db, spaceId, userId, artifactId);
  if (!row) return null;

  // Only text-compatible types for reader v1
  const textMime = !row.mime_type || row.mime_type.startsWith("text/") || row.mime_type === "application/json";
  if (!textMime) return null;

  const raw = row.content
    ? row.content
    : row.storage_path
      ? await safeReadTextFile(config, row.storage_path)
      : null;
  if (raw === null) return null;

  if (row.mime_type === "application/json") {
    const structured = parseStructuredReaderContent(raw);
    if (structured) {
      return {
        text: structured.plain_text,
        title: structured.title ?? row.title,
        contentJson: structured.content_json,
      };
    }
  }

  return { text: raw, title: row.title };
}

async function safeReadTextFile(
  config: Pick<ServerConfig, "artifactStorageRoot" | "sandboxRoot">,
  storagePath: string,
): Promise<string | null> {
  if (storagePath.startsWith("/") || storagePath.includes("\0")) return null;
  const root = resolve(config.artifactStorageRoot);
  const sandboxRoot = resolve(config.sandboxRoot);
  const candidate = resolve(root, storagePath);
  if (!candidate.startsWith(root + "/") && candidate !== root) return null;
  if (candidate.startsWith(sandboxRoot + "/") || candidate === sandboxRoot) return null;
  const info = await stat(candidate).catch(() => null);
  if (!info?.isFile()) return null;
  return readFile(candidate, "utf8").catch(() => null);
}

// ── Source snapshot row ───────────────────────────────────────────────────────

interface SourceSnapshotRow {
  id: string;
  space_id: string;
  intake_item_id: string | null;
  connection_id: string | null;
  snapshot_type: string;
  artifact_id: string | null;
  content_hash: string | null;
  source_uri: string | null;
}

// ── Reader document output ────────────────────────────────────────────────────

export interface ReaderDocumentOut {
  document_type: string;
  document_id: string;
  space_id: string;
  title: string;
  plain_text: string;
  /** Canonical form: trim → split on ≥2 newlines → trim paragraphs → join with ' '.
   *  All anchor text_range offsets, content_hash, and context windows must be
   *  computed from this field, not from plain_text. */
  normalized_text: string;
  content_hash: string;
  content_format: "tiptap_json";
  content_schema_version: 1;
  content_json: ReaderPmDoc;
  intake_item_id: string | null;
  artifact_id: string | null;
  source_snapshot_id: string | null;
  raw_artifact_id: string | null;
  extracted_artifact_id: string | null;
  source_uri: string | null;
  content_state: string | null;
  retention_policy: string | null;
  can_annotate: true;
}

// ── Source consent check ──────────────────────────────────────────────────────

interface ConsentCheckInput {
  db: Queryable;
  identity: SpaceUserIdentity;
  item: IntakeItemRow;
}

async function enforceConnectionReadConsent(
  db: Queryable,
  identity: SpaceUserIdentity,
  connectionId: string,
): Promise<void> {
  const conn = await db.query<{ consent_json: unknown; policy_json: unknown; owner_user_id: string }>(
    `SELECT consent_json, policy_json, owner_user_id
       FROM source_connections WHERE space_id = $1 AND id = $2`,
    [identity.spaceId, connectionId],
  );
  // Intentionally omits deleted_at IS NULL: soft-deleted connections still carry
  // consent_json and should continue to gate access to their derived snapshots.
  // A missing row (hard-deleted or wrong space) is treated as fail-closed.
  if (!conn.rows[0]) throw new HttpError(404, "Not found");
  const gov = normalizeSourceConnectionReadGovernance({
    ...conn.rows[0],
    id: connectionId,
    space_id: identity.spaceId,
    connector_id: "",
    name: "",
    endpoint_url: null,
    status: "active",
    fetch_frequency: "manual",
    capture_policy: "metadata_only",
    trust_level: "normal",
    topic_hints_json: null,
    config_json: null,
    credential_id: null,
    last_checked_at: null,
    next_check_at: null,
    handler_kind: "built_in",
    active_handler_version_id: null,
    active_recipe_version_id: null,
    repair_status: "ok",
    last_handler_run_id: null,
    created_at: null,
    updated_at: null,
  });
  const consent = gov.consent;
  if (identity.userId === consent.owner_user_id) return;
  if (consent.allowed_reader_user_ids.includes(identity.userId)) return;
  if (consent.allow_space_admins) {
    const roleRow = await db.query<{ role: string }>(
      `SELECT role FROM space_memberships WHERE user_id = $1 AND space_id = $2 AND status = 'active' LIMIT 1`,
      [identity.userId, identity.spaceId],
    );
    if (isSpaceOwnerOrAdmin(roleRow.rows[0]?.role)) return;
  }
  throw new HttpError(404, "Not found");
}

async function enforceIntakeItemReadConsent({ db, identity, item }: ConsentCheckInput): Promise<void> {
  if (item.space_id !== identity.spaceId) throw new HttpError(404, "Not found");
  if (item.connection_id) {
    await enforceConnectionReadConsent(db, identity, item.connection_id);
  }
  // No connection — any space member can read
}

// ── Repository ────────────────────────────────────────────────────────────────

export class PgReaderRepository {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  async getDocument(
    identity: SpaceUserIdentity,
    documentType: string,
    documentId: string,
  ): Promise<ReaderDocumentOut | null> {
    if (documentType === "intake_item") {
      return this.resolveIntakeItem(identity, documentId);
    }
    if (documentType === "artifact") {
      return this.resolveArtifact(identity, documentId);
    }
    if (documentType === "source_snapshot") {
      return this.resolveSourceSnapshot(identity, documentId);
    }
    throw new HttpError(400, `Unsupported document type: ${documentType}`);
  }

  // ── intake_item resolver ────────────────────────────────────────────────────

  private async resolveIntakeItem(
    identity: SpaceUserIdentity,
    itemId: string,
  ): Promise<ReaderDocumentOut | null> {
    const result = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, itemId],
    );
    const item = result.rows[0];
    if (!item) return null;

    await enforceIntakeItemReadConsent({ db: this.db, identity, item });

    // Priority 1: extracted_artifact_id
    if (item.extracted_artifact_id) {
      const text = await readArtifactForReader(this.db, this.config, identity.spaceId, identity.userId, item.extracted_artifact_id);
      if (text) {
        return this.buildDocOut({
          documentType: "intake_item",
          documentId: itemId,
          spaceId: identity.spaceId,
          title: item.title,
          plainText: text.text,
          contentJson: text.contentJson,
          intakeItemId: itemId,
          artifactId: item.extracted_artifact_id,
          sourceSnapshotId: null,
          rawArtifactId: item.raw_artifact_id,
          extractedArtifactId: item.extracted_artifact_id,
          sourceUri: item.source_uri,
          contentState: item.content_state,
          retentionPolicy: item.retention_policy,
        });
      }
    }

    // Priority 2: latest extracted snapshot (by captured_at, not id)
    const snapResult = await this.db.query<SourceSnapshotRow>(
      `SELECT id, space_id, intake_item_id, snapshot_type, artifact_id, content_hash, source_uri
         FROM source_snapshots
        WHERE space_id = $1 AND intake_item_id = $2 AND snapshot_type = 'extracted' AND artifact_id IS NOT NULL
        ORDER BY captured_at DESC LIMIT 1`,
      [identity.spaceId, itemId],
    );
    const snap = snapResult.rows[0];
    if (snap?.artifact_id) {
      const text = await readArtifactForReader(this.db, this.config, identity.spaceId, identity.userId, snap.artifact_id);
      if (text) {
        return this.buildDocOut({
          documentType: "intake_item",
          documentId: itemId,
          spaceId: identity.spaceId,
          title: item.title,
          plainText: text.text,
          contentJson: text.contentJson,
          intakeItemId: itemId,
          artifactId: snap.artifact_id,
          sourceSnapshotId: snap.id,
          rawArtifactId: item.raw_artifact_id,
          extractedArtifactId: item.extracted_artifact_id,
          sourceUri: item.source_uri,
          contentState: item.content_state,
          retentionPolicy: item.retention_policy,
        });
      }
    }

    // Priority 3: raw_artifact_id (stripped to plain text)
    if (item.raw_artifact_id) {
      const text = await readArtifactForReader(this.db, this.config, identity.spaceId, identity.userId, item.raw_artifact_id);
      if (text) {
        const stripped = stripToPlainText(text.text);
        return this.buildDocOut({
          documentType: "intake_item",
          documentId: itemId,
          spaceId: identity.spaceId,
          title: item.title,
          plainText: stripped,
          intakeItemId: itemId,
          artifactId: item.raw_artifact_id,
          sourceSnapshotId: null,
          rawArtifactId: item.raw_artifact_id,
          extractedArtifactId: item.extracted_artifact_id,
          sourceUri: item.source_uri,
          contentState: item.content_state,
          retentionPolicy: item.retention_policy,
        });
      }
    }

    // Priority 4: excerpt fallback
    if (item.excerpt) {
      return this.buildDocOut({
        documentType: "intake_item",
        documentId: itemId,
        spaceId: identity.spaceId,
        title: item.title,
        plainText: item.excerpt,
        intakeItemId: itemId,
        artifactId: null,
        sourceSnapshotId: null,
        rawArtifactId: item.raw_artifact_id,
        extractedArtifactId: item.extracted_artifact_id,
        sourceUri: item.source_uri,
        contentState: item.content_state,
        retentionPolicy: item.retention_policy,
      });
    }

    return null;
  }

  // ── artifact resolver ───────────────────────────────────────────────────────

  private async resolveArtifact(
    identity: SpaceUserIdentity,
    artifactId: string,
  ): Promise<ReaderDocumentOut | null> {
    const text = await readArtifactForReader(this.db, this.config, identity.spaceId, identity.userId, artifactId);
    if (!text) return null;

    const titleRow = await this.db.query<{ title: string }>(
      `SELECT title FROM artifacts WHERE id = $1 AND space_id = $2`,
      [artifactId, identity.spaceId],
    );
    const title = titleRow.rows[0]?.title ?? text.title;

    return this.buildDocOut({
      documentType: "artifact",
      documentId: artifactId,
      spaceId: identity.spaceId,
      title,
      plainText: text.text,
      contentJson: text.contentJson,
      intakeItemId: null,
      artifactId,
      sourceSnapshotId: null,
      rawArtifactId: null,
      extractedArtifactId: null,
      sourceUri: null,
      contentState: null,
      retentionPolicy: null,
    });
  }

  // ── source_snapshot resolver ────────────────────────────────────────────────

  private async resolveSourceSnapshot(
    identity: SpaceUserIdentity,
    snapshotId: string,
  ): Promise<ReaderDocumentOut | null> {
    const result = await this.db.query<SourceSnapshotRow>(
      `SELECT id, space_id, intake_item_id, connection_id, snapshot_type, artifact_id, content_hash, source_uri
         FROM source_snapshots WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, snapshotId],
    );
    const snap = result.rows[0];
    if (!snap) return null;

    // Enforce source consent: intake-item consent covers the connection gate;
    // connection-only snapshots are gated directly against the connection's consent_json.
    if (snap.intake_item_id) {
      const itemResult = await this.db.query<IntakeItemRow>(
        `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
        [identity.spaceId, snap.intake_item_id],
      );
      if (itemResult.rows[0]) {
        await enforceIntakeItemReadConsent({ db: this.db, identity, item: itemResult.rows[0] });
      } else if (snap.connection_id) {
        // Item soft-deleted: fall back to connection gate rather than opening access.
        await enforceConnectionReadConsent(this.db, identity, snap.connection_id);
      } else {
        throw new HttpError(404, "Not found");
      }
    } else if (snap.connection_id) {
      await enforceConnectionReadConsent(this.db, identity, snap.connection_id);
    }

    if (!snap.artifact_id) return null;

    const text = await readArtifactForReader(this.db, this.config, identity.spaceId, identity.userId, snap.artifact_id);
    if (!text) return null;

    return this.buildDocOut({
      documentType: "source_snapshot",
      documentId: snapshotId,
      spaceId: identity.spaceId,
      title: text.title,
      plainText: text.text,
      contentJson: text.contentJson,
      intakeItemId: snap.intake_item_id,
      artifactId: snap.artifact_id,
      sourceSnapshotId: snapshotId,
      rawArtifactId: null,
      extractedArtifactId: null,
      sourceUri: snap.source_uri,
      contentState: null,
      retentionPolicy: null,
    });
  }

  // ── builder ─────────────────────────────────────────────────────────────────

  private buildDocOut(args: {
    documentType: string;
    documentId: string;
    spaceId: string;
    title: string;
    plainText: string;
    contentJson?: ReaderPmDoc;
    intakeItemId: string | null;
    artifactId: string | null;
    sourceSnapshotId: string | null;
    rawArtifactId: string | null;
    extractedArtifactId: string | null;
    sourceUri: string | null;
    contentState: string | null;
    retentionPolicy: string | null;
  }): ReaderDocumentOut {
    const normalizedText = normalizeReaderText(args.plainText);
    const contentJson = args.contentJson ?? plainTextToPmDoc(args.plainText);
    const contentHash = sha256Hex(normalizedText);
    return {
      document_type: args.documentType,
      document_id: args.documentId,
      space_id: args.spaceId,
      title: args.title,
      plain_text: args.plainText,
      normalized_text: normalizedText,
      content_hash: contentHash,
      content_format: "tiptap_json",
      content_schema_version: 1,
      content_json: contentJson,
      intake_item_id: args.intakeItemId,
      artifact_id: args.artifactId,
      source_snapshot_id: args.sourceSnapshotId,
      raw_artifact_id: args.rawArtifactId,
      extracted_artifact_id: args.extractedArtifactId,
      source_uri: args.sourceUri,
      content_state: args.contentState,
      retention_policy: args.retentionPolicy,
      can_annotate: true,
    };
  }
}

// ── Annotation repository ─────────────────────────────────────────────────────

const ANNOTATION_TYPES = new Set(["highlight", "comment", "excerpt", "bookmark"]);
const VISIBILITY_VALUES = new Set(["private", "space_shared"]);

export interface ReaderAnnotationRow {
  id: string;
  space_id: string;
  intake_item_id: string | null;
  artifact_id: string | null;
  source_snapshot_id: string | null;
  annotation_type: string;
  quote_text: string;
  anchor_json: unknown;
  color: string | null;
  label: string | null;
  visibility: string;
  status: string;
  anchor_state: string;
  created_by_user_id: string;
  created_at: unknown;
  updated_at: unknown;
}

const ANNOTATION_COLUMNS = `id, space_id, intake_item_id, artifact_id, source_snapshot_id,
  annotation_type, quote_text, anchor_json, color, label, visibility, status, anchor_state,
  created_by_user_id, created_at, updated_at`;

export interface ReaderAnnotationOut {
  id: string;
  space_id: string;
  intake_item_id: string | null;
  artifact_id: string | null;
  source_snapshot_id: string | null;
  annotation_type: string;
  quote_text: string;
  anchor_json: Record<string, unknown>;
  color: string | null;
  label: string | null;
  visibility: string;
  status: string;
  anchor_state: string;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

function annotationOut(row: ReaderAnnotationRow): ReaderAnnotationOut {
  return {
    id: row.id,
    space_id: row.space_id,
    intake_item_id: row.intake_item_id,
    artifact_id: row.artifact_id,
    source_snapshot_id: row.source_snapshot_id,
    annotation_type: row.annotation_type,
    quote_text: row.quote_text,
    anchor_json: objectValue(row.anchor_json),
    color: row.color,
    label: row.label,
    visibility: row.visibility,
    status: row.status,
    anchor_state: row.anchor_state,
    created_by_user_id: row.created_by_user_id,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

// ── Document gate helpers ─────────────────────────────────────────────────────

function annotationDocumentTarget(
  ann: ReaderAnnotationRow,
): { documentType: string; documentId: string } | null {
  if (ann.intake_item_id) return { documentType: "intake_item", documentId: ann.intake_item_id };
  if (ann.artifact_id) return { documentType: "artifact", documentId: ann.artifact_id };
  if (ann.source_snapshot_id) return { documentType: "source_snapshot", documentId: ann.source_snapshot_id };
  return null;
}

// ── Document read gate (lightweight, no file I/O) ────────────────────────────

async function assertDocumentReadable(
  db: Queryable,
  identity: SpaceUserIdentity,
  documentType: string,
  documentId: string,
): Promise<void> {
  if (documentType === "intake_item") {
    const r = await db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [identity.spaceId, documentId],
    );
    if (!r.rows[0]) throw new HttpError(404, "Document not found");
    await enforceIntakeItemReadConsent({ db, identity, item: r.rows[0] });
    return;
  }
  if (documentType === "artifact") {
    await assertArtifactReadable(db, identity, documentId, "Document not found");
    return;
  }
  if (documentType === "source_snapshot") {
    const r = await db.query<{ intake_item_id: string | null; connection_id: string | null; artifact_id: string | null }>(
      `SELECT intake_item_id, connection_id, artifact_id FROM source_snapshots WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, documentId],
    );
    if (!r.rows[0]) throw new HttpError(404, "Document not found");
    if (r.rows[0].intake_item_id) {
      const itemR = await db.query<IntakeItemRow>(
        `SELECT ${ITEM_COLUMNS} FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
        [identity.spaceId, r.rows[0].intake_item_id],
      );
      if (itemR.rows[0]) {
        await enforceIntakeItemReadConsent({ db, identity, item: itemR.rows[0] });
      } else if (r.rows[0].connection_id) {
        // Item soft-deleted: fall back to connection gate so access is not silently opened.
        await enforceConnectionReadConsent(db, identity, r.rows[0].connection_id);
      } else {
        // Intake item referenced but no longer exists and no connection fallback: fail closed.
        throw new HttpError(404, "Not found");
      }
    } else if (r.rows[0].connection_id) {
      // Connection-only snapshot: enforce the connection's own consent gate.
      await enforceConnectionReadConsent(db, identity, r.rows[0].connection_id);
    }
    // Snapshot content comes from its artifact; verify the caller can read it.
    // This mirrors resolveSourceSnapshot so annotation gate matches document gate.
    if (r.rows[0].artifact_id) {
      await assertArtifactReadable(db, identity, r.rows[0].artifact_id, "Not found");
    }
    return;
  }
  throw new HttpError(400, `Unsupported document type: ${documentType}`);
}

/**
 * Tries to verify that normalizedText.slice(start, end) === quoteText using only
 * inline artifact content (no file I/O). Returns 'verified' on match, 'unverified'
 * if content is unavailable or the slice doesn't match.
 */
async function tryVerifyAnchorRange(
  db: Queryable,
  identity: SpaceUserIdentity,
  documentType: string,
  documentId: string,
  start: number,
  end: number,
  quoteText: string,
): Promise<"verified" | "unverified"> {
  try {
    let artifactId: string | null = null;
    let inlineText: string | null = null;

    if (documentType === "intake_item") {
      const r = await db.query<{ extracted_artifact_id: string | null; excerpt: string | null }>(
        `SELECT extracted_artifact_id, excerpt FROM intake_items WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
        [identity.spaceId, documentId],
      );
      if (!r.rows[0]) return "unverified";
      if (r.rows[0].extracted_artifact_id) {
        artifactId = r.rows[0].extracted_artifact_id;
      } else if (r.rows[0].excerpt) {
        inlineText = r.rows[0].excerpt;
      }
    } else if (documentType === "artifact") {
      artifactId = documentId;
    } else if (documentType === "source_snapshot") {
      const r = await db.query<{ artifact_id: string | null }>(
        `SELECT artifact_id FROM source_snapshots WHERE space_id = $1 AND id = $2`,
        [identity.spaceId, documentId],
      );
      artifactId = r.rows[0]?.artifact_id ?? null;
    }

    if (artifactId && !inlineText) {
      const r = await db.query<{ content: string | null; mime_type: string | null }>(
        `SELECT content, mime_type FROM artifacts WHERE id = $1 AND space_id = $2`,
        [artifactId, identity.spaceId],
      );
      if (!r.rows[0]?.content) return "unverified";
      const mimeType = r.rows[0].mime_type;
      if (mimeType && !mimeType.startsWith("text/") && mimeType !== "application/json") return "unverified";
      if (mimeType === "application/json") {
        const structured = parseStructuredReaderContent(r.rows[0].content);
        if (!structured) return "unverified";
        inlineText = structured.plain_text;
      } else {
        inlineText = r.rows[0].content;
      }
    }

    if (!inlineText) return "unverified";
    const normalizedText = normalizeReaderText(inlineText);
    // JS string indexing is UTF-16 code units, matching the anchor text_range.unit='utf16' contract.
    return normalizedText.slice(start, end) === quoteText ? "verified" : "unverified";
  } catch {
    return "unverified";
  }
}

export class PgAnnotationRepository {
  constructor(
    private readonly db: Queryable,
  ) {}

  async listAnnotations(
    identity: SpaceUserIdentity,
    documentType: string,
    documentId: string,
  ): Promise<ReaderAnnotationOut[]> {
    let col: string;
    if (documentType === "intake_item") col = "intake_item_id";
    else if (documentType === "artifact") col = "artifact_id";
    else if (documentType === "source_snapshot") col = "source_snapshot_id";
    else throw new HttpError(400, `Unsupported document type: ${documentType}`);

    // Verify caller can read the underlying document before returning any annotations.
    await assertDocumentReadable(this.db, identity, documentType, documentId);

    const result = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS}
         FROM reader_annotations
        WHERE space_id = $1
          AND ${col} = $2
          AND status = 'active'
          AND (visibility = 'space_shared' OR created_by_user_id = $3)
        ORDER BY created_at ASC`,
      [identity.spaceId, documentId, identity.userId],
    );
    return result.rows.map(annotationOut);
  }

  async createAnnotation(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
  ): Promise<ReaderAnnotationOut> {
    const annotationType = optionalString(body.annotation_type);
    if (!annotationType || !ANNOTATION_TYPES.has(annotationType)) {
      throw new HttpError(422, "annotation_type must be one of: highlight, comment, excerpt, bookmark");
    }
    const quoteText = optionalString(body.quote_text);
    if (!quoteText) throw new HttpError(422, "quote_text is required");

    const anchor = body.anchor_json;
    if (!anchor || typeof anchor !== "object" || Array.isArray(anchor)) {
      throw new HttpError(422, "anchor_json must be an object");
    }
    const anchorObj = anchor as Record<string, unknown>;
    if (anchorObj.schema_version !== 1) {
      throw new HttpError(422, "anchor_json.schema_version must be 1");
    }
    if (anchorObj.quote_text !== quoteText) {
      throw new HttpError(422, "anchor_json.quote_text must match quote_text");
    }
    const textRange = anchorObj.text_range as Record<string, unknown> | null | undefined;
    if (!textRange || typeof textRange.start !== "number" || typeof textRange.end !== "number" || textRange.unit !== "utf16") {
      throw new HttpError(422, "anchor_json.text_range must include start, end (numbers), and unit='utf16'");
    }
    const rangeStart = textRange.start as number;
    const rangeEnd = textRange.end as number;
    if (rangeStart < 0) throw new HttpError(422, "anchor_json.text_range.start must be >= 0");
    if (rangeEnd <= rangeStart) throw new HttpError(422, "anchor_json.text_range.end must be > start");

    if (anchorObj.before_context === undefined || anchorObj.after_context === undefined) {
      throw new HttpError(422, "anchor_json.before_context and after_context are required");
    }

    const intakeItemId = optionalString(body.intake_item_id);
    const artifactId = optionalString(body.artifact_id);
    const sourceSnapshotId = optionalString(body.source_snapshot_id);
    const nonNullCount = [intakeItemId, artifactId, sourceSnapshotId].filter(Boolean).length;
    if (nonNullCount !== 1) {
      throw new HttpError(422, "Exactly one of intake_item_id, artifact_id, source_snapshot_id must be provided");
    }

    // Verify the caller can read the target document before creating an annotation on it.
    const documentType = intakeItemId ? "intake_item" : artifactId ? "artifact" : "source_snapshot";
    const documentId = (intakeItemId ?? artifactId ?? sourceSnapshotId)!;
    await assertDocumentReadable(this.db, identity, documentType, documentId);

    // Attempt lightweight text verification using inline artifact content only (no file I/O).
    // Falls through to 'unverified' if content is not stored inline or doesn't match.
    const anchorState = await tryVerifyAnchorRange(
      this.db, identity, documentType, documentId, rangeStart, rangeEnd, quoteText,
    );

    const visibility = optionalString(body.visibility) ?? "private";
    if (!VISIBILITY_VALUES.has(visibility)) {
      throw new HttpError(422, "visibility must be 'private' or 'space_shared'");
    }

    const color = optionalString(body.color);
    const label = optionalString(body.label);
    const now = new Date().toISOString();
    const id = randomUUID();

    const result = await this.db.query<ReaderAnnotationRow>(
      `INSERT INTO reader_annotations (
         id, space_id, intake_item_id, artifact_id, source_snapshot_id,
         annotation_type, quote_text, anchor_json, color, label,
         visibility, status, anchor_state, created_by_user_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8::jsonb, $9, $10,
         $11, 'active', $12, $13, $14, $14
       ) RETURNING ${ANNOTATION_COLUMNS}`,
      [
        id, identity.spaceId, intakeItemId, artifactId, sourceSnapshotId,
        annotationType, quoteText, JSON.stringify(anchorObj), color, label,
        visibility, anchorState, identity.userId, now,
      ],
    );
    return annotationOut(result.rows[0]!);
  }

  async updateAnnotation(
    identity: SpaceUserIdentity,
    annotationId: string,
    body: Record<string, unknown>,
  ): Promise<ReaderAnnotationOut> {
    const row = await this.getAnnotationRow(identity.spaceId, annotationId);
    if (!row) throw new HttpError(404, "Annotation not found");
    if (row.created_by_user_id !== identity.userId) throw new HttpError(404, "Not found");

    const sets: string[] = [];
    const params: unknown[] = [identity.spaceId, annotationId];

    const color = optionalString(body.color);
    if (body.color !== undefined) { params.push(color); sets.push(`color = $${params.length}`); }

    const label = optionalString(body.label);
    if (body.label !== undefined) { params.push(label); sets.push(`label = $${params.length}`); }

    const visibility = optionalString(body.visibility);
    if (visibility !== null && visibility !== undefined) {
      if (!VISIBILITY_VALUES.has(visibility)) throw new HttpError(422, "Invalid visibility");
      params.push(visibility); sets.push(`visibility = $${params.length}`);
    }

    const status = optionalString(body.status);
    if (status !== null && status !== undefined) {
      if (status !== "active" && status !== "archived") throw new HttpError(422, "Invalid status");
      params.push(status); sets.push(`status = $${params.length}`);
    }

    if (sets.length === 0) throw new HttpError(422, "No fields to update");

    params.push(new Date().toISOString());
    sets.push(`updated_at = $${params.length}`);

    const result = await this.db.query<ReaderAnnotationRow>(
      `UPDATE reader_annotations SET ${sets.join(", ")}
        WHERE space_id = $1 AND id = $2 RETURNING ${ANNOTATION_COLUMNS}`,
      params,
    );
    return annotationOut(result.rows[0]!);
  }

  async archiveAnnotation(
    identity: SpaceUserIdentity,
    annotationId: string,
  ): Promise<void> {
    const row = await this.getAnnotationRow(identity.spaceId, annotationId);
    if (!row) throw new HttpError(404, "Annotation not found");
    if (row.created_by_user_id !== identity.userId) throw new HttpError(404, "Not found");
    await this.db.query(
      `UPDATE reader_annotations SET status = 'archived', updated_at = $3 WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, annotationId, new Date().toISOString()],
    );
  }

  private async getAnnotationRow(spaceId: string, annotationId: string): Promise<ReaderAnnotationRow | null> {
    const result = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2`,
      [spaceId, annotationId],
    );
    return result.rows[0] ?? null;
  }
}

// ── Comment/Thread repository ─────────────────────────────────────────────────

export interface ReaderCommentThreadRow {
  id: string;
  space_id: string;
  annotation_id: string;
  status: string;
  created_by_user_id: string;
  created_at: unknown;
  updated_at: unknown;
}

export interface ReaderCommentRow {
  id: string;
  space_id: string;
  thread_id: string;
  body: string;
  status: string;
  created_by_user_id: string;
  created_at: unknown;
  updated_at: unknown;
}

export interface ReaderCommentThreadOut {
  id: string;
  space_id: string;
  annotation_id: string;
  status: string;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
  comments: ReaderCommentOut[];
}

export interface ReaderCommentOut {
  id: string;
  space_id: string;
  thread_id: string;
  body: string;
  status: string;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

const THREAD_COLUMNS = `id, space_id, annotation_id, status, created_by_user_id, created_at, updated_at`;
const COMMENT_COLUMNS = `id, space_id, thread_id, body, status, created_by_user_id, created_at, updated_at`;
const THREAD_STATUSES = new Set(["open", "resolved", "archived"]);

function threadOut(row: ReaderCommentThreadRow, comments: ReaderCommentOut[]): ReaderCommentThreadOut {
  return {
    id: row.id,
    space_id: row.space_id,
    annotation_id: row.annotation_id,
    status: row.status,
    created_by_user_id: row.created_by_user_id,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
    comments,
  };
}

function commentOut(row: ReaderCommentRow): ReaderCommentOut {
  return {
    id: row.id,
    space_id: row.space_id,
    thread_id: row.thread_id,
    body: row.body,
    status: row.status,
    created_by_user_id: row.created_by_user_id,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

export class PgCommentRepository {
  constructor(
    private readonly db: Queryable,
  ) {}

  async listThreads(
    identity: SpaceUserIdentity,
    annotationId: string,
  ): Promise<ReaderCommentThreadOut[]> {
    // Verify annotation is visible to caller before exposing its threads.
    const annResult = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2 AND status = 'active'`,
      [identity.spaceId, annotationId],
    );
    const ann = annResult.rows[0];
    if (!ann) throw new HttpError(404, "Annotation not found");
    if (ann.visibility === "private" && ann.created_by_user_id !== identity.userId) {
      throw new HttpError(404, "Not found");
    }
    // Also verify the caller can still read the underlying document (e.g. space_shared
    // annotations remain accessible only while the document itself is accessible).
    const annDoc = annotationDocumentTarget(ann);
    if (annDoc) {
      await assertDocumentReadable(this.db, identity, annDoc.documentType, annDoc.documentId);
    }

    const threadResult = await this.db.query<ReaderCommentThreadRow>(
      `SELECT ${THREAD_COLUMNS} FROM reader_comment_threads
        WHERE space_id = $1 AND annotation_id = $2 AND status != 'archived'
        ORDER BY created_at ASC`,
      [identity.spaceId, annotationId],
    );
    const threads = threadResult.rows;
    if (threads.length === 0) return [];

    const threadIds = threads.map((t) => t.id);
    const placeholders = threadIds.map((_, i) => `$${i + 2}`).join(", ");
    const commentResult = await this.db.query<ReaderCommentRow>(
      `SELECT ${COMMENT_COLUMNS} FROM reader_comments
        WHERE space_id = $1 AND thread_id IN (${placeholders}) AND status = 'active'
        ORDER BY created_at ASC`,
      [identity.spaceId, ...threadIds],
    );

    const byThread = new Map<string, ReaderCommentOut[]>();
    for (const c of commentResult.rows) {
      const list = byThread.get(c.thread_id) ?? [];
      list.push(commentOut(c));
      byThread.set(c.thread_id, list);
    }

    return threads.map((t) => threadOut(t, byThread.get(t.id) ?? []));
  }

  async createComment(
    identity: SpaceUserIdentity,
    annotationId: string,
    body: Record<string, unknown>,
  ): Promise<{ thread: ReaderCommentThreadOut }> {
    const annotation = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2 AND status = 'active'`,
      [identity.spaceId, annotationId],
    );
    const ann = annotation.rows[0];
    if (!ann) throw new HttpError(404, "Annotation not found");

    if (ann.visibility === "private" && ann.created_by_user_id !== identity.userId) {
      throw new HttpError(404, "Not found");
    }
    const annDoc = annotationDocumentTarget(ann);
    if (annDoc) {
      await assertDocumentReadable(this.db, identity, annDoc.documentType, annDoc.documentId);
    }

    const commentBody = optionalString(body.body);
    if (!commentBody) throw new HttpError(422, "body is required");

    const now = new Date().toISOString();

    // Create or reuse open thread
    let threadRow: ReaderCommentThreadRow;
    const existingThread = await this.db.query<ReaderCommentThreadRow>(
      `SELECT ${THREAD_COLUMNS} FROM reader_comment_threads
        WHERE space_id = $1 AND annotation_id = $2 AND status = 'open' LIMIT 1`,
      [identity.spaceId, annotationId],
    );
    if (existingThread.rows[0]) {
      threadRow = existingThread.rows[0];
    } else {
      const threadResult = await this.db.query<ReaderCommentThreadRow>(
        `INSERT INTO reader_comment_threads (id, space_id, annotation_id, status, created_by_user_id, created_at, updated_at)
           VALUES ($1, $2, $3, 'open', $4, $5, $5) RETURNING ${THREAD_COLUMNS}`,
        [randomUUID(), identity.spaceId, annotationId, identity.userId, now],
      );
      threadRow = threadResult.rows[0]!;
    }

    await this.db.query(
      `INSERT INTO reader_comments (id, space_id, thread_id, body, status, created_by_user_id, created_at, updated_at)
         VALUES ($1, $2, $3, $4, 'active', $5, $6, $6)`,
      [randomUUID(), identity.spaceId, threadRow.id, commentBody, identity.userId, now],
    );

    await this.db.query(
      `UPDATE reader_comment_threads SET updated_at = $3 WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, threadRow.id, now],
    );

    const allComments = await this.db.query<ReaderCommentRow>(
      `SELECT ${COMMENT_COLUMNS} FROM reader_comments WHERE space_id = $1 AND thread_id = $2 AND status = 'active' ORDER BY created_at ASC`,
      [identity.spaceId, threadRow.id],
    );

    return { thread: threadOut(threadRow, allComments.rows.map(commentOut)) };
  }

  async updateComment(
    identity: SpaceUserIdentity,
    commentId: string,
    body: Record<string, unknown>,
  ): Promise<ReaderCommentOut> {
    const result = await this.db.query<ReaderCommentRow>(
      `SELECT ${COMMENT_COLUMNS} FROM reader_comments WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, commentId],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Comment not found");
    if (row.created_by_user_id !== identity.userId) throw new HttpError(404, "Not found");

    const newBody = optionalString(body.body);
    const status = optionalString(body.status);

    const sets: string[] = [];
    const params: unknown[] = [identity.spaceId, commentId];
    if (newBody !== null && newBody !== undefined) {
      params.push(newBody); sets.push(`body = $${params.length}`);
    }
    if (status !== null && status !== undefined) {
      if (status !== "active" && status !== "archived") throw new HttpError(422, "Invalid status");
      params.push(status); sets.push(`status = $${params.length}`);
    }
    if (sets.length === 0) throw new HttpError(422, "No fields to update");
    params.push(new Date().toISOString()); sets.push(`updated_at = $${params.length}`);

    const updated = await this.db.query<ReaderCommentRow>(
      `UPDATE reader_comments SET ${sets.join(", ")} WHERE space_id = $1 AND id = $2 RETURNING ${COMMENT_COLUMNS}`,
      params,
    );
    return commentOut(updated.rows[0]!);
  }

  async updateThread(
    identity: SpaceUserIdentity,
    threadId: string,
    body: Record<string, unknown>,
  ): Promise<ReaderCommentThreadOut> {
    const result = await this.db.query<ReaderCommentThreadRow>(
      `SELECT ${THREAD_COLUMNS} FROM reader_comment_threads WHERE space_id = $1 AND id = $2`,
      [identity.spaceId, threadId],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Thread not found");

    // Load full annotation to enforce visibility + document read gate.
    const annResult = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2 AND status = 'active'`,
      [identity.spaceId, row.annotation_id],
    );
    const ann = annResult.rows[0];
    if (!ann) throw new HttpError(404, "Not found");
    if (ann.visibility === "private" && ann.created_by_user_id !== identity.userId) {
      throw new HttpError(404, "Not found");
    }
    const annDoc = annotationDocumentTarget(ann);
    if (annDoc) {
      await assertDocumentReadable(this.db, identity, annDoc.documentType, annDoc.documentId);
    }
    // Only thread creator or annotation creator may change thread status.
    if (row.created_by_user_id !== identity.userId && ann.created_by_user_id !== identity.userId) {
      throw new HttpError(404, "Not found");
    }

    const status = optionalString(body.status);
    if (!status || !THREAD_STATUSES.has(status)) throw new HttpError(422, "status must be open, resolved, or archived");

    const now = new Date().toISOString();
    const updated = await this.db.query<ReaderCommentThreadRow>(
      `UPDATE reader_comment_threads SET status = $3, updated_at = $4 WHERE space_id = $1 AND id = $2 RETURNING ${THREAD_COLUMNS}`,
      [identity.spaceId, threadId, status, now],
    );

    const comments = await this.db.query<ReaderCommentRow>(
      `SELECT ${COMMENT_COLUMNS} FROM reader_comments WHERE space_id = $1 AND thread_id = $2 AND status = 'active' ORDER BY created_at ASC`,
      [identity.spaceId, threadId],
    );

    return threadOut(updated.rows[0]!, comments.rows.map(commentOut));
  }
}

// ── Reader action result types ─────────────────────────────────────────────────

export interface ReaderEvidenceResult {
  id: string;
  title: string;
  status: string;
  evidence_type: string;
  intake_item_id: string | null;
  source_object_type: string;
  source_object_id: string;
}

export interface ReaderProposalResult {
  id: string;
  proposal_type: string;
  status: string;
  title: string;
}

// ── Reader action helpers ──────────────────────────────────────────────────────

async function loadAnnotationConnectionPolicy(
  db: Queryable,
  spaceId: string,
  ann: ReaderAnnotationRow,
): Promise<Record<string, unknown> | null> {
  if (ann.intake_item_id) {
    const r = await db.query<{ policy_json: unknown }>(
      `SELECT sc.policy_json
         FROM intake_items ii
         JOIN source_connections sc ON sc.id = ii.connection_id
        WHERE ii.space_id = $1 AND ii.id = $2 AND ii.deleted_at IS NULL`,
      [spaceId, ann.intake_item_id],
    );
    return (r.rows[0]?.policy_json as Record<string, unknown>) ?? null;
  }
  if (ann.source_snapshot_id) {
    const r = await db.query<{ policy_json: unknown }>(
      `SELECT sc.policy_json
         FROM source_snapshots ss
         JOIN source_connections sc ON sc.id = ss.connection_id
        WHERE ss.space_id = $1 AND ss.id = $2`,
      [spaceId, ann.source_snapshot_id],
    );
    return (r.rows[0]?.policy_json as Record<string, unknown>) ?? null;
  }
  if (ann.artifact_id) {
    // Resolve connection by tracing artifact back to a source snapshot or intake item.
    const r = await db.query<{ policy_json: unknown }>(
      `SELECT sc.policy_json
         FROM (
           SELECT ss.connection_id FROM source_snapshots ss
            WHERE ss.space_id = $1 AND ss.artifact_id = $2
           UNION ALL
           SELECT ii.connection_id FROM intake_items ii
            WHERE ii.space_id = $1
              AND (ii.raw_artifact_id = $2 OR ii.extracted_artifact_id = $2)
              AND ii.deleted_at IS NULL
         ) agg
         JOIN source_connections sc ON sc.id = agg.connection_id
        LIMIT 1`,
      [spaceId, ann.artifact_id],
    );
    return (r.rows[0]?.policy_json as Record<string, unknown>) ?? null;
  }
  return null;
}

// ── Reader actions and project summaries ───────────────────────────────────────

export class PgReaderActionRepository {
  constructor(private readonly db: Queryable) {}

  async createEvidence(
    identity: SpaceUserIdentity,
    annotationId: string,
    body: Record<string, unknown>,
  ): Promise<ReaderEvidenceResult> {
    const annResult = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2 AND status = 'active'`,
      [identity.spaceId, annotationId],
    );
    const ann = annResult.rows[0];
    if (!ann) throw new HttpError(404, "Not found");
    if (ann.visibility === "private") {
      if (ann.created_by_user_id !== identity.userId) {
        // No-oracle: non-owner must not learn the annotation exists.
        throw new HttpError(404, "Not found");
      }
      // Private annotations must not generate space-scoped evidence — evidence
      // has no visibility field and is readable by all space members.
      throw new HttpError(422, "Cannot create evidence from a private annotation. Change visibility to space_shared first.");
    }
    const doc = annotationDocumentTarget(ann);
    if (doc) await assertDocumentReadable(this.db, identity, doc.documentType, doc.documentId);

    const policyJson = await loadAnnotationConnectionPolicy(this.db, identity.spaceId, ann);
    if (policyJson) enforceSourceDerivedImportTarget(policyJson, "source_artifact");

    const title = optionalString(body.title) || ann.quote_text.slice(0, 80);
    const now = new Date().toISOString();
    const contentHash = sha256Hex(ann.quote_text);

    interface EvidenceRow {
      id: string; title: string; status: string; evidence_type: string;
      intake_item_id: string | null; source_object_type: string; source_object_id: string;
    }
    const r = await this.db.query<EvidenceRow>(
      `INSERT INTO extracted_evidence (
         id, space_id, intake_item_id, source_object_type, source_object_id,
         evidence_type, title, content_excerpt, content_hash,
         trust_level, extraction_method, status, metadata_json,
         created_by_user_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, 'reader_annotation', $4,
         'excerpt', $5, $6, $7,
         'normal', 'manual', 'candidate', $8::jsonb,
         $9, $10, $10
       ) RETURNING id, title, status, evidence_type, intake_item_id, source_object_type, source_object_id`,
      [
        randomUUID(),
        identity.spaceId,
        ann.intake_item_id,
        annotationId,
        title,
        ann.quote_text,
        contentHash,
        JSON.stringify({
          annotation_id: ann.id,
          annotation_type: ann.annotation_type,
          document_type: doc?.documentType ?? null,
          document_id: doc?.documentId ?? null,
        }),
        identity.userId,
        now,
      ],
    );
    return r.rows[0]!;
  }

  async createProposal(
    identity: SpaceUserIdentity,
    annotationId: string,
    body: Record<string, unknown>,
  ): Promise<ReaderProposalResult> {
    const annResult = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${ANNOTATION_COLUMNS} FROM reader_annotations WHERE space_id = $1 AND id = $2 AND status = 'active'`,
      [identity.spaceId, annotationId],
    );
    const ann = annResult.rows[0];
    if (!ann) throw new HttpError(404, "Not found");
    if (ann.visibility === "private" && ann.created_by_user_id !== identity.userId) {
      throw new HttpError(404, "Not found");
    }
    const doc = annotationDocumentTarget(ann);
    if (doc) await assertDocumentReadable(this.db, identity, doc.documentType, doc.documentId);

    const proposalType = optionalString(body.proposal_type);
    if (proposalType !== "memory_create" && proposalType !== "knowledge_create") {
      throw new HttpError(422, "proposal_type must be memory_create or knowledge_create");
    }

    const policyJson = await loadAnnotationConnectionPolicy(this.db, identity.spaceId, ann);
    if (policyJson) {
      const target = proposalType === "memory_create" ? "memory_proposal" : "knowledge";
      enforceSourceDerivedImportTarget(policyJson, target as "memory_proposal" | "knowledge");
    }

    const title = optionalString(body.title) || ann.quote_text.slice(0, 80);
    const rationale = optionalString(body.rationale) ?? "Created from reader annotation.";
    const sourceRefs = [
      { source_type: "reader_annotation", source_id: ann.id, source_trust: "untrusted_external" },
      ...(doc ? [{ source_type: doc.documentType, source_id: doc.documentId, source_trust: "untrusted_external" }] : []),
    ];

    const payload = proposalType === "knowledge_create"
      ? {
          operation: "create",
          knowledge_kind: "summary",
          title,
          content: ann.quote_text,
          content_format: "plain",
          visibility: "space_shared",
          source_refs: sourceRefs,
        }
      : {
          operation: "create",
          proposed_content: ann.quote_text,
          memory_type: "experience",
          target_scope: "user",
          target_namespace: "intake.annotation",
          provenance_entries: sourceRefs,
        };

    const row = await insertProposalRow(this.db, {
      spaceId: identity.spaceId,
      proposalType,
      title,
      payload,
      rationale,
      createdByUserId: identity.userId,
      visibility: ann.visibility === "space_shared" ? "space_shared" : "private",
      riskLevel: "low",
    });

    return { id: row.id, proposal_type: row.proposal_type, status: row.status, title: row.title };
  }

  async listProjectAnnotations(
    identity: SpaceUserIdentity,
    projectId: string,
    limit: number,
  ): Promise<ReaderAnnotationOut[]> {
    if (!(await canAccessProject(this.db, identity.spaceId, projectId, identity.userId))) {
      throw new HttpError(404, "Project not found");
    }
    // Prefix all annotation columns with ra. to avoid ambiguity with joined tables.
    const cols = `ra.id, ra.space_id, ra.intake_item_id, ra.artifact_id, ra.source_snapshot_id,
  ra.annotation_type, ra.quote_text, ra.anchor_json, ra.color, ra.label, ra.visibility, ra.status, ra.anchor_state,
  ra.created_by_user_id, ra.created_at, ra.updated_at`;
    const r = await this.db.query<ReaderAnnotationRow>(
      `SELECT ${cols}
         FROM reader_annotations ra
         JOIN intake_items ii ON ii.id = ra.intake_item_id
              AND ii.space_id = $1 AND ii.deleted_at IS NULL
         JOIN source_connections sc ON sc.id = ii.connection_id
         JOIN workspace_source_bindings wsb
              ON wsb.source_connection_id = sc.id
              AND wsb.space_id = $1 AND wsb.project_id = $2 AND wsb.status = 'active'
        WHERE ra.space_id = $1
          AND ra.status = 'active'
          AND ra.visibility = 'space_shared'
          AND (
            sc.consent_json->>'owner_user_id' = $3
            OR sc.consent_json->'allowed_reader_user_ids' @> to_jsonb($3::text)
            OR (
              (sc.consent_json->>'allow_space_admins')::boolean = true
              AND EXISTS (
                SELECT 1 FROM space_memberships sm
                 WHERE sm.user_id = $3 AND sm.space_id = $1
                   AND sm.status = 'active' AND sm.role IN ('owner', 'admin')
              )
            )
          )
        ORDER BY ra.created_at DESC
        LIMIT $4`,
      [identity.spaceId, projectId, identity.userId, limit],
    );
    return r.rows.map(annotationOut);
  }
}

// ── Plain text strip helper ───────────────────────────────────────────────────

function stripToPlainText(input: string): string {
  // Remove common HTML tags
  return input
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}
