import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { __setAuthIdentityForTests } from "../src/modules/auth";
import { type Queryable } from "../src/modules/routeUtils/common";
import { PgReaderRepository, PgReaderActionRepository, PgAnnotationRepository, PgCommentRepository } from "../src/modules/intake/readerRepository";
import type { IntakeItemRow } from "../src/modules/intake/intakeRepositoryRows";

// ── Test helpers ──────────────────────────────────────────────────────────────

const SPACE = "space-1";
const USER = "user-1";
const identity = { spaceId: SPACE, userId: USER };

function config() {
  return loadConfig({ SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space" });
}

/** Annotation row with space_shared visibility and no connection gate. */
function fakeAnnotation(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "ann-1",
    space_id: SPACE,
    intake_item_id: "item-1",
    artifact_id: null,
    source_snapshot_id: null,
    annotation_type: "excerpt",
    quote_text: "The quick brown fox jumps over the lazy dog.",
    anchor_json: { schema_version: 1, normalizer: "plain_text_v1", quote_text: "fox" },
    color: null,
    label: null,
    visibility: "space_shared",
    status: "active",
    anchor_state: "unverified",
    created_by_user_id: USER,
    created_at: "2026-06-30T10:00:00.000Z",
    updated_at: "2026-06-30T10:00:00.000Z",
    ...overrides,
  };
}

/** IntakeItem with connection_id=null so no connection consent gate is applied. */
function fakeItem(overrides: Partial<IntakeItemRow> = {}): IntakeItemRow {
  return {
    id: "item-1",
    space_id: SPACE,
    connection_id: null,
    item_type: "article",
    source_object_type: null,
    source_object_id: null,
    title: "Test article",
    source_uri: null,
    canonical_uri: null,
    source_domain: null,
    source_external_id: null,
    author: null,
    occurred_at: null,
    first_seen_at: null,
    last_seen_at: null,
    content_hash: null,
    excerpt: null,
    status: "candidate",
    read_status: "unread",
    content_state: "pending",
    retention_policy: "metadata_only",
    relevance_score: null,
    novelty_score: null,
    raw_artifact_id: null,
    extracted_artifact_id: null,
    summary_artifact_id: null,
    search_index_ref: null,
    embedding_index_ref: null,
    metadata_json: null,
    created_at: "2026-06-30T10:00:00.000Z",
    updated_at: "2026-06-30T10:00:00.000Z",
    ...overrides,
  };
}

function fakeEvidenceRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "evidence-1",
    title: "The quick brown fox jumps over the lazy dog.",
    status: "candidate",
    evidence_type: "excerpt",
    intake_item_id: "item-1",
    source_object_type: "reader_annotation",
    source_object_id: "ann-1",
    ...overrides,
  };
}

function fakeArtifact(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "artifact-1",
    space_id: SPACE,
    artifact_type: "intake_extracted_text",
    title: "Extracted article",
    content: "Full article text.",
    storage_path: null,
    mime_type: "text/plain",
    visibility: "space_shared",
    owner_user_id: null,
    ...overrides,
  };
}

function fakeProposalRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "proposal-1",
    space_id: SPACE,
    created_by_user_id: USER,
    workspace_id: null,
    created_by_run_id: null,
    proposal_type: "memory_create",
    status: "pending",
    risk_level: "low",
    urgency: "normal",
    preview: false,
    title: "The quick brown fox",
    payload_json: {},
    rationale: "Created from reader annotation.",
    visibility: "space_shared",
    review_deadline: null,
    expires_at: null,
    created_at: "2026-06-30T10:00:00.000Z",
    reviewed_at: null,
    project_id: null,
    egress_approval_id: null,
    egress_approval_status: null,
    ...overrides,
  };
}

// ── Sequential fake DB ────────────────────────────────────────────────────────

interface CapturedQuery {
  sql: string;
  params: readonly unknown[];
}

/**
 * Returns a fake Queryable that hands back `rowSets[0]` on the first .query()
 * call, `rowSets[1]` on the second, and [] for any call beyond the provided
 * sets. Captures all calls in `calls` for assertion.
 */
function sequentialDb(
  rowSets: unknown[][],
): { db: Queryable; calls: CapturedQuery[] } {
  const calls: CapturedQuery[] = [];
  let idx = 0;
  const db: Queryable = {
    async query<Row>(sql: string, params: readonly unknown[] = []) {
      calls.push({ sql, params });
      const rows = (rowSets[idx++] ?? []) as Row[];
      return { rows, rowCount: rows.length };
    },
  };
  return { db, calls };
}

// ── Route validation tests ────────────────────────────────────────────────────

let app: FastifyInstance | undefined;

afterEach(async () => {
  __setAuthIdentityForTests(null);
  await app?.close();
  app = undefined;
});

describe("intake reader routes — auth and input validation", () => {
  it("returns 401 to unauthenticated requests on the reader document endpoint", async () => {
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/intake/reader/documents/intake_item/item-1",
    });

    expect(res.statusCode).toBe(401);
  });

  it("returns 400 when project_id is missing from GET /intake/reader/annotations", async () => {
    __setAuthIdentityForTests({ spaceId: SPACE, userId: USER });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/intake/reader/annotations",
    });

    expect(res.statusCode).toBe(400);
    expect(res.json().detail).toMatch(/project_id/);
  });

  it("returns 401 to unauthenticated requests on POST /intake/reader/annotations", async () => {
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/intake/reader/annotations",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ annotation_type: "excerpt", quote_text: "x" }),
    });

    expect(res.statusCode).toBe(401);
  });
});

// ── PgReaderRepository unit tests ─────────────────────────────────────────────

describe("PgReaderRepository.getDocument", () => {
  it("reads artifact text without filtering on a non-existent artifacts.deleted_at column", async () => {
    const { db, calls } = sequentialDb([
      [fakeArtifact()],
      [{ title: "Extracted article" }],
    ]);
    const repo = new PgReaderRepository(db, config());

    const result = await repo.getDocument(identity, "artifact", "artifact-1");

    expect(result?.plain_text).toBe("Full article text.");
    const artifactQueries = calls.filter((call) => call.sql.includes("FROM artifacts"));
    expect(artifactQueries.length).toBeGreaterThan(0);
    expect(artifactQueries.some((call) => call.sql.includes("deleted_at"))).toBe(false);
  });

  it("reads structured reader document artifacts without flattening content_json", async () => {
    const structured = {
      schema_version: 1,
      kind: "reader_document",
      extraction_method: "structured_html_v1",
      image_policy: "remote_reference",
      title: "Structured article",
      source_uri: "https://example.test/read",
      plain_text: "Structured heading\n\nParagraph text.",
      content_json: {
        type: "doc",
        content: [
          { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Structured heading" }] },
          { type: "paragraph", content: [{ type: "text", text: "Paragraph text." }] },
          { type: "image", attrs: { src: "https://example.test/image.png", alt: "Remote image" } },
        ],
      },
      image_count: 1,
    };
    const { db } = sequentialDb([
      [fakeArtifact({
        artifact_type: "intake_reader_document",
        content: JSON.stringify(structured),
        mime_type: "application/json",
      })],
      [{ title: "Stored artifact title" }],
    ]);
    const repo = new PgReaderRepository(db, config());

    const result = await repo.getDocument(identity, "artifact", "artifact-1");

    expect(result?.plain_text).toBe(structured.plain_text);
    expect(result?.content_json.content).toEqual(structured.content_json.content);
    expect(result?.normalized_text).toBe("Structured heading Paragraph text.");
  });
});

describe("PgAnnotationRepository.createAnnotation", () => {
  it("verifies anchor ranges against structured reader document plain_text", async () => {
    const structured = {
      schema_version: 1,
      kind: "reader_document",
      extraction_method: "structured_html_v1",
      image_policy: "remote_reference",
      title: "Structured article",
      source_uri: "https://example.test/read",
      plain_text: "Structured heading\n\nParagraph text.",
      content_json: {
        type: "doc",
        content: [
          { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Structured heading" }] },
          { type: "paragraph", content: [{ type: "text", text: "Paragraph text." }] },
        ],
      },
      image_count: 0,
    };
    const { db, calls } = sequentialDb([
      [fakeArtifact({
        artifact_type: "intake_reader_document",
        content: JSON.stringify(structured),
        mime_type: "application/json",
      })],
      [{ content: JSON.stringify(structured), mime_type: "application/json" }],
      [fakeAnnotation({
        intake_item_id: null,
        artifact_id: "artifact-1",
        annotation_type: "highlight",
        quote_text: "Paragraph text.",
        anchor_state: "verified",
      })],
    ]);
    const repo = new PgAnnotationRepository(db);

    const result = await repo.createAnnotation(identity, {
      annotation_type: "highlight",
      quote_text: "Paragraph text.",
      anchor_json: {
        schema_version: 1,
        quote_text: "Paragraph text.",
        text_range: { start: 19, end: 34, unit: "utf16" },
        before_context: "Structured heading ",
        after_context: "",
      },
      artifact_id: "artifact-1",
    });

    const insert = calls.find((call) => call.sql.includes("INSERT INTO reader_annotations"));
    expect(insert?.params).toContain("verified");
    expect(result.anchor_state).toBe("verified");
  });
});

// ── PgReaderActionRepository unit tests ──────────────────────────────────────

describe("PgReaderActionRepository.createEvidence", () => {
  it("throws 422 when the caller owns the private annotation (no-oracle: owner sees 422, not 404)", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → private, owned by the caller
      [fakeAnnotation({ visibility: "private", created_by_user_id: USER })],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createEvidence(identity, "ann-1", {}),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("throws 404 when a non-owner attempts evidence from a private annotation (no-oracle)", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → private, owned by a different user
      [fakeAnnotation({ visibility: "private", created_by_user_id: "other-user" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createEvidence(identity, "ann-1", {}),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("throws 404 when the annotation is not found", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → empty
      [],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createEvidence(identity, "ann-1", {}),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("creates evidence with status=candidate for a space_shared annotation", async () => {
    const { db, calls } = sequentialDb([
      // SELECT annotation
      [fakeAnnotation({ visibility: "space_shared" })],
      // assertDocumentReadable → SELECT intake_items
      [fakeItem()],
      // loadAnnotationConnectionPolicy → SELECT policy (empty, no connection)
      [],
      // INSERT INTO extracted_evidence RETURNING
      [fakeEvidenceRow()],
    ]);
    const repo = new PgReaderActionRepository(db);

    const result = await repo.createEvidence(identity, "ann-1", {});

    expect(result.status).toBe("candidate");
    expect(result.evidence_type).toBe("excerpt");
    expect(result.source_object_type).toBe("reader_annotation");

    const evidenceInsert = calls.find((c) => c.sql.includes("INSERT INTO extracted_evidence"));
    expect(evidenceInsert).toBeDefined();
    // Verify it was inserted with 'candidate' status (in params, not inlined into SQL)
    expect(evidenceInsert?.sql).toContain("'candidate'");
  });

  it("does not write to memory_entries or knowledge_items", async () => {
    const { db, calls } = sequentialDb([
      [fakeAnnotation({ visibility: "space_shared" })],
      [fakeItem()],
      [],
      [fakeEvidenceRow()],
    ]);
    const repo = new PgReaderActionRepository(db);

    await repo.createEvidence(identity, "ann-1", {});

    const writes = calls.filter((c) => c.sql.startsWith("INSERT INTO"));
    expect(writes.length).toBe(1);
    expect(writes[0]!.sql).toContain("extracted_evidence");
    expect(calls.some((c) => c.sql.includes("memory_entries"))).toBe(false);
    expect(calls.some((c) => c.sql.includes("knowledge_items"))).toBe(false);
  });

  it("uses the supplied title when provided", async () => {
    const { db, calls } = sequentialDb([
      [fakeAnnotation({ visibility: "space_shared" })],
      [fakeItem()],
      [],
      [fakeEvidenceRow({ title: "Custom title" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    const result = await repo.createEvidence(identity, "ann-1", { title: "Custom title" });

    const insert = calls.find((c) => c.sql.includes("INSERT INTO extracted_evidence"));
    // title is passed as a param — verify the param value appears
    expect(insert?.params).toContain("Custom title");
    expect(result.title).toBe("Custom title");
  });
});

describe("PgReaderActionRepository.createProposal", () => {
  it("throws 422 for an unsupported proposal_type", async () => {
    const { db } = sequentialDb([
      // SELECT annotation
      [fakeAnnotation()],
      // assertDocumentReadable → SELECT intake_items
      [fakeItem()],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createProposal(identity, "ann-1", { proposal_type: "direct_write" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("creates a memory_create proposal with status=pending", async () => {
    const { db, calls } = sequentialDb([
      // SELECT annotation
      [fakeAnnotation({ visibility: "space_shared" })],
      // assertDocumentReadable → SELECT intake_items
      [fakeItem()],
      // loadAnnotationConnectionPolicy → empty (no connection)
      [],
      // INSERT INTO proposals RETURNING
      [fakeProposalRow({ proposal_type: "memory_create", status: "pending" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    const result = await repo.createProposal(identity, "ann-1", {
      proposal_type: "memory_create",
    });

    expect(result.status).toBe("pending");
    expect(result.proposal_type).toBe("memory_create");

    const proposalInsert = calls.find((c) => c.sql.includes("INSERT INTO proposals"));
    expect(proposalInsert).toBeDefined();
    // status is passed as $5 param (index 4), defaulting to "pending"
    expect(proposalInsert?.params[4]).toBe("pending");
  });

  it("creates a knowledge_create proposal with status=pending", async () => {
    const { db, calls } = sequentialDb([
      [fakeAnnotation({ visibility: "space_shared" })],
      [fakeItem()],
      [],
      [fakeProposalRow({ proposal_type: "knowledge_create", status: "pending" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    const result = await repo.createProposal(identity, "ann-1", {
      proposal_type: "knowledge_create",
    });

    expect(result.status).toBe("pending");
    expect(result.proposal_type).toBe("knowledge_create");

    const proposalInsert = calls.find((c) => c.sql.includes("INSERT INTO proposals"));
    expect(proposalInsert).toBeDefined();
    expect(proposalInsert?.params[4]).toBe("pending");
  });

  it("does not write to memory_entries or knowledge_items", async () => {
    const { db, calls } = sequentialDb([
      [fakeAnnotation({ visibility: "space_shared" })],
      [fakeItem()],
      [],
      [fakeProposalRow()],
    ]);
    const repo = new PgReaderActionRepository(db);

    await repo.createProposal(identity, "ann-1", { proposal_type: "memory_create" });

    const writes = calls.filter((c) => c.sql.startsWith("INSERT INTO"));
    expect(writes.length).toBe(1);
    expect(writes[0]!.sql).toContain("proposals");
    expect(calls.some((c) => c.sql.includes("memory_entries"))).toBe(false);
    expect(calls.some((c) => c.sql.includes("knowledge_items"))).toBe(false);
  });

  it("throws 404 when annotation is not found", async () => {
    const { db } = sequentialDb([[]]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createProposal(identity, "ann-1", { proposal_type: "memory_create" }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("throws 404 for a private annotation when caller is not the creator", async () => {
    const { db } = sequentialDb([
      // SELECT annotation — private, owned by a different user
      [fakeAnnotation({ visibility: "private", created_by_user_id: "other-user" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.createProposal(identity, "ann-1", { proposal_type: "memory_create" }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });
});

describe("PgReaderActionRepository.listProjectAnnotations", () => {
  it("throws 404 when canAccessProject returns false", async () => {
    const { db } = sequentialDb([
      // canAccessProject → SELECT FROM project_members or projects → empty
      [],
    ]);
    const repo = new PgReaderActionRepository(db);

    await expect(
      repo.listProjectAnnotations(identity, "project-1", 10),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("filters annotations using a source connection consent check in SQL", async () => {
    // canAccessProject makes 2 queries: SELECT projects, then SELECT spaces.
    // A "personal" space short-circuits to true immediately without a 3rd query.
    const { db, calls } = sequentialDb([
      // canAccessProject #1: SELECT projects → project exists, owned by USER
      [{ owner_user_id: USER }],
      // canAccessProject #2: SELECT spaces → personal space (short-circuits to true)
      [{ type: "personal" }],
      // listProjectAnnotations SELECT → returns one annotation
      [fakeAnnotation({ visibility: "space_shared" })],
    ]);
    const repo = new PgReaderActionRepository(db);

    const results = await repo.listProjectAnnotations(identity, "project-1", 10);
    expect(results.length).toBe(1);

    // The query must inline the consent gate (not a separate query per annotation)
    const listQuery = calls.find((c) => c.sql.includes("reader_annotations"));
    expect(listQuery).toBeDefined();
    expect(listQuery!.sql).toContain("consent_json->>'owner_user_id'");
    expect(listQuery!.sql).toContain("allowed_reader_user_ids");
    expect(listQuery!.sql).toContain("allow_space_admins");
    // anchor_state must be included so the ReaderAnnotation contract is satisfied
    expect(listQuery!.sql).toContain("anchor_state");
    // Project members alone must not unlock consent — the check must reference the user param
    expect(listQuery!.params).toContain(USER);
  });

  it("returns only space_shared annotations", async () => {
    const { db, calls } = sequentialDb([
      // canAccessProject
      [{ owner_user_id: USER }],
      [{ type: "personal" }],
      // list query → empty (no results pass consent filter)
      [],
    ]);
    const repo = new PgReaderActionRepository(db);

    const results = await repo.listProjectAnnotations(identity, "project-1", 10);
    expect(results).toEqual([]);

    const listQuery = calls.find((c) => c.sql.includes("reader_annotations"));
    expect(listQuery!.sql).toContain("'space_shared'");
  });
});

// ── Document gate and annotation/thread visibility ─────────────────────────────

describe("PgAnnotationRepository.listAnnotations — document gate", () => {
  it("throws 404 when the intake_item document is not found", async () => {
    const { db } = sequentialDb([
      // assertDocumentReadable → SELECT intake_items → not found
      [],
    ]);
    const repo = new PgAnnotationRepository(db);

    await expect(
      repo.listAnnotations(identity, "intake_item", "item-1"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("throws 404 when a source_snapshot's intake_item is soft-deleted and has no connection fallback", async () => {
    const { db } = sequentialDb([
      // assertDocumentReadable → SELECT source_snapshots → found with intake_item_id but no connection
      [{ intake_item_id: "item-1", connection_id: null, artifact_id: null }],
      // SELECT intake_items → empty (soft-deleted)
      [],
    ]);
    const repo = new PgAnnotationRepository(db);

    await expect(
      repo.listAnnotations(identity, "source_snapshot", "snap-1"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("returns annotations after passing the document gate", async () => {
    const { db } = sequentialDb([
      // assertDocumentReadable → SELECT intake_items → found (no connection, no consent gate)
      [fakeItem()],
      // SELECT reader_annotations → two rows pass the SQL filter
      [
        fakeAnnotation({ visibility: "space_shared" }),
        fakeAnnotation({ id: "ann-2", visibility: "private", created_by_user_id: USER }),
      ],
    ]);
    const repo = new PgAnnotationRepository(db);

    const results = await repo.listAnnotations(identity, "intake_item", "item-1");
    expect(results).toHaveLength(2);
    expect(results[0]!.visibility).toBe("space_shared");
    expect(results[1]!.visibility).toBe("private");
  });

  it("SQL filter includes both space_shared and own-user conditions, parameterized on user id", async () => {
    const { db, calls } = sequentialDb([
      [fakeItem()],
      [],
    ]);
    const repo = new PgAnnotationRepository(db);

    await repo.listAnnotations(identity, "intake_item", "item-1");

    const listQuery = calls.find((c) => c.sql.includes("reader_annotations") && c.sql.includes("SELECT"));
    expect(listQuery!.sql).toContain("'space_shared'");
    expect(listQuery!.sql).toContain("created_by_user_id");
    // User id must be a query param, not inlined
    expect(listQuery!.params).toContain(USER);
  });
});

describe("PgCommentRepository.listThreads — annotation visibility gate", () => {
  it("throws 404 for a private annotation owned by another user", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → private, other user
      [fakeAnnotation({ visibility: "private", created_by_user_id: "other-user" })],
    ]);
    const repo = new PgCommentRepository(db);

    await expect(
      repo.listThreads(identity, "ann-1"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("allows the annotation owner to list threads on their own private annotation", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → private, owned by USER
      [fakeAnnotation({ visibility: "private", created_by_user_id: USER })],
      // assertDocumentReadable → SELECT intake_items → found
      [fakeItem()],
      // SELECT reader_comment_threads → empty
      [],
    ]);
    const repo = new PgCommentRepository(db);

    const result = await repo.listThreads(identity, "ann-1");
    expect(result).toEqual([]);
  });

  it("throws 404 for a space_shared annotation whose document is no longer accessible", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → space_shared (passes visibility check)
      [fakeAnnotation({ visibility: "space_shared" })],
      // assertDocumentReadable → SELECT intake_items → empty (document gone)
      [],
    ]);
    const repo = new PgCommentRepository(db);

    await expect(
      repo.listThreads(identity, "ann-1"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("throws 404 when the annotation itself is not found", async () => {
    const { db } = sequentialDb([
      // SELECT annotation → empty
      [],
    ]);
    const repo = new PgCommentRepository(db);

    await expect(
      repo.listThreads(identity, "ann-1"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });
});

describe("POST /intake/reader/annotations — anchor range validation", () => {
  it("returns 422 when text_range.start is negative", async () => {
    __setAuthIdentityForTests({ spaceId: SPACE, userId: USER });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/intake/reader/annotations",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({
        annotation_type: "excerpt",
        quote_text: "fox",
        anchor_json: {
          schema_version: 1,
          normalizer: "plain_text_v1",
          quote_text: "fox",
          text_range: { start: -1, end: 3, unit: "utf16" },
          before_context: "",
          after_context: "",
        },
        intake_item_id: "item-1",
      }),
    });

    expect(res.statusCode).toBe(422);
    expect(res.json().detail).toMatch(/start must be >= 0/);
  });

  it("returns 422 when text_range.end is not greater than start", async () => {
    __setAuthIdentityForTests({ spaceId: SPACE, userId: USER });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/intake/reader/annotations",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({
        annotation_type: "excerpt",
        quote_text: "fox",
        anchor_json: {
          schema_version: 1,
          normalizer: "plain_text_v1",
          quote_text: "fox",
          text_range: { start: 5, end: 5, unit: "utf16" },
          before_context: "",
          after_context: "",
        },
        intake_item_id: "item-1",
      }),
    });

    expect(res.statusCode).toBe(422);
    expect(res.json().detail).toMatch(/end must be > start/);
  });
});
