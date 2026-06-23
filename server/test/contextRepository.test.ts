import { describe, expect, it } from "vitest";
import { PgRunContextRepository } from "../src/modules/context/repository";
import type { Queryable } from "../src/modules/memory/repository";

class CapturingDb implements Queryable {
  queries: Array<{ sql: string; params: readonly unknown[] }> = [];
  projectOwnerUserId: string | null = null;
  spaceType = "household";
  artifacts: Record<string, unknown>[] = [];
  contextArtifactRevocations: Record<string, unknown>[] = [];
  accessibleWorkspaceIds = new Set<string>();
  sourceSnapshotRows: Record<string, unknown>[] = [];
  viewerRole: string | null = "member";

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: Row[]; rowCount: number | null }> {
    this.queries.push({ sql, params });
    const norm = sql.replace(/\s+/g, " ").trim();
    if (norm.includes("FROM source_connections")) {
      return { rows: this.sourceSnapshotRows as Row[], rowCount: this.sourceSnapshotRows.length };
    }
    if (norm.includes("FROM space_memberships")) {
      const rows = this.viewerRole ? [{ role: this.viewerRole }] : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (norm.includes("FROM context_artifact_revocations")) {
      const artifactIds = Array.isArray(params[1]) ? new Set(params[1] as string[]) : null;
      const rows = this.contextArtifactRevocations.filter((revocation) => {
        if (revocation.deleted_at) return false;
        if (revocation.space_id !== params[0]) return false;
        if (artifactIds && !artifactIds.has(String(revocation.artifact_id))) return false;
        return true;
      });
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (norm.includes("FROM artifacts")) {
      const userId = params[2] as string | null;
      const workspaceId = params[3] as string | null;
      const rows = this.artifacts.filter((artifact) => {
        const visibility = String(artifact.visibility ?? "");
        const ownerUserId = typeof artifact.owner_user_id === "string" ? artifact.owner_user_id : null;
        if (visibility === "space_shared" || visibility === "public_template") return true;
        if (visibility === "workspace_shared") {
          return Boolean(
            artifact.workspace_id
            && workspaceId
            && artifact.workspace_id === workspaceId
            && this.accessibleWorkspaceIds.has(workspaceId),
          );
        }
        if (ownerUserId === null && !["workspace_shared", "restricted", "selected_users"].includes(visibility)) {
          return true;
        }
        return ownerUserId === userId;
      });
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (norm.includes("FROM projects")) {
      const rows = this.projectOwnerUserId === null
        ? []
        : [{ owner_user_id: this.projectOwnerUserId }];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (norm.includes("FROM workspaces")) {
      const rows = this.accessibleWorkspaceIds.has(String(params[1])) ? [{ one: 1 }] : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (norm.includes("FROM spaces")) {
      return { rows: [{ type: this.spaceType }] as Row[], rowCount: 1 };
    }
    return { rows: [], rowCount: 0 };
  }
}

describe("PgRunContextRepository digest source revalidation", () => {
  it("excludes project-scoped memory from shared digest consumption", async () => {
    const db = new CapturingDb();
    await new PgRunContextRepository(db).filterEligibleDigestMemoryIds({
      spaceId: "space-1",
      scopeType: "workspace",
      scopeId: "ws-1",
      memoryIds: ["mem-1"],
    });

    const sql = db.queries[0]?.sql ?? "";
    expect(sql).toContain("project_id IS NULL");
  });

  it("does not select project-linked evidence when the viewer lacks project access", async () => {
    const db = new CapturingDb();
    db.projectOwnerUserId = "other-user";

    await new PgRunContextRepository(db).selectEvidenceForContext({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: null,
      projectId: "project-1",
      runId: null,
    });

    const evidenceQuery = db.queries.find((query) =>
      query.sql.includes("FROM extracted_evidence"),
    );
    expect(evidenceQuery?.params).not.toContain("project");
    expect(evidenceQuery?.params).not.toContain("project-1");
  });

  it("selects explicit artifact evidence packs as bounded context attachments", async () => {
    const db = new CapturingDb();
    db.sourceSnapshotRows = [
      {
        id: "source-1",
        owner_user_id: "user-1",
        consent_json: {
          schema_version: 1,
          owner_user_id: "user-1",
          allowed_reader_user_ids: ["user-2"],
          allowed_agent_ids: [],
          allow_space_admins: true,
          allow_local_provider_egress: true,
          allow_external_model_egress: false,
        },
        policy_json: {
          schema_version: 1,
          source_egress_class: "local_provider_allowed",
        },
      },
    ];
    db.artifacts = [
      {
        id: "brief-1",
        artifact_type: "retrieval_brief",
        title: "Context Brief: alpha",
        content: JSON.stringify({ raw_secret: "should not be copied" }),
        metadata_json: {
          kind: "retrieval_brief",
          surface: "knowledge_brief",
          query: "alpha",
          answer: "Use the cited alpha plan.",
          citations: [{ title: "Alpha Plan" }],
          egress_policy_snapshot: { external_egress_enabled: false },
          settings_snapshot: { default_search_mode: "hybrid" },
          source_refs: [{ source_connection_id: "source-1" }],
        },
        visibility: "private",
        owner_user_id: "user-1",
        project_id: null,
        workspace_id: null,
        created_at: "2026-06-25T00:00:00.000Z",
      },
      {
        id: "generic-1",
        artifact_type: "generic_report",
        title: "Generic",
        content: "not attachable",
        metadata_json: {},
        visibility: "private",
        owner_user_id: "user-1",
        project_id: null,
        workspace_id: null,
        created_at: "2026-06-25T00:00:00.000Z",
      },
      {
        id: "explain-1",
        artifact_type: "retrieval_explain_report",
        title: "Explain",
        content: null,
        metadata_json: {
          kind: "retrieval_explain_report",
          diagnostic_codes: ["target_not_returned"],
          target: {
            id: "secret-target-id",
            object_id: "secret-object-id",
            object_type: "claim",
            title: "Target title should not be expanded into raw JSON",
            returned: false,
            visibility: "space_shared",
            status: "active",
          },
          match: {
            id: "secret-match-id",
            score: 0.812345,
            rank: 3,
            matched_fields: ["title", "summary"],
            reasons: ["lexical overlap"],
            nested_candidate_payload: { secret: "should not leak" },
          },
        },
        visibility: "private",
        owner_user_id: "user-1",
        project_id: null,
        workspace_id: null,
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-1",
      artifactIds: ["brief-1", "missing-1", "generic-1", "explain-1"],
    });

    expect(selections).toHaveLength(4);
    expect(selections[0].item).toMatchObject({
      attachment_type: "artifact_evidence_pack",
      artifact_id: "brief-1",
      artifact_type: "retrieval_brief",
      domain_label: "knowledge_brief",
      approved: true,
      policy_snapshot: {
        content_mode: "bounded_summary",
        raw_artifact_content_included: false,
      },
      source_policy_snapshot: {
        egress_policy_snapshot: { external_egress_enabled: false },
        settings_snapshot: { default_search_mode: "hybrid" },
        source_ref_count: 1,
        source_connection_ids: ["source-1"],
        source_connection_count: 1,
        source_policy_snapshots: {
          "source-1": expect.objectContaining({
            id: "source-1",
            ownerUserId: "user-1",
            allowSpaceAdmins: true,
            sourceEgressClass: "local_provider_allowed",
          }),
        },
        current_reader_gate: expect.objectContaining({
          evaluated: true,
          enforced_for_attachment: false,
          allowed: true,
        }),
      },
    });
    expect(String(selections[0].item.resolved_content)).toContain("Answer: Use the cited alpha plan.");
    expect(String(selections[0].item.resolved_content)).toContain("- Alpha Plan");
    expect(String(selections[0].item.resolved_content)).not.toContain("should not be copied");
    expect(selections[0].ref).toMatchObject({
      source_type: "artifact",
      source_id: "brief-1",
      included: true,
      content_mode: "bounded_summary",
      raw_artifact_content_included: false,
    });
    expect(selections[1].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact not found or not visible",
    });
    expect(selections[2].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact type is not attachable to context",
    });
    expect(selections[3].item).toMatchObject({
      approved: true,
      artifact_id: "explain-1",
      artifact_type: "retrieval_explain_report",
      domain_label: "knowledge.retrieval.explain",
    });
    const explainContent = String(selections[3].item.resolved_content);
    expect(explainContent).toContain("Target type: claim");
    expect(explainContent).toContain("Target returned: no");
    expect(explainContent).toContain("Match rank: 3");
    expect(explainContent).toContain("Matched fields: title, summary");
    expect(explainContent).not.toContain("secret-target-id");
    expect(explainContent).not.toContain("secret-match-id");
    expect(explainContent).not.toContain("nested_candidate_payload");
    const artifactQuery = db.queries.find((query) => query.sql.includes("FROM artifacts"));
    expect(artifactQuery?.sql).toContain("visibility = 'workspace_shared'");
    expect(artifactQuery?.sql).toContain("project_workspaces");
    expect(artifactQuery?.sql).toContain("project_members");
    expect(artifactQuery?.sql).not.toContain("visibility IN ('space_shared', 'workspace_shared'");
    expect(artifactQuery?.params).toContain("ws-1");
  });

  it("only attaches workspace_shared artifacts with matching workspace context", async () => {
    const db = new CapturingDb();
    db.accessibleWorkspaceIds.add("ws-1");
    db.artifacts = [
      {
        id: "brief-1",
        artifact_type: "retrieval_brief",
        title: "Workspace Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "Workspace scoped answer.",
        },
        visibility: "workspace_shared",
        owner_user_id: "other-user",
        project_id: null,
        workspace_id: "ws-1",
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];
    const repository = new PgRunContextRepository(db);

    const withoutWorkspace = await repository.selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: null,
      artifactIds: ["brief-1"],
    });
    const withWorkspace = await repository.selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-1",
      artifactIds: ["brief-1"],
    });
    const withDifferentWorkspace = await repository.selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-2",
      artifactIds: ["brief-1"],
    });

    expect(withoutWorkspace[0].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact not found or not visible",
    });
    expect(withWorkspace[0].item).toMatchObject({
      approved: true,
      artifact_id: "brief-1",
      artifact_type: "retrieval_brief",
    });
    expect(withDifferentWorkspace[0].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact not found or not visible",
    });
  });

  it("blocks context artifact attachments revoked for the current workspace or project", async () => {
    const db = new CapturingDb();
    db.accessibleWorkspaceIds.add("ws-1");
    db.projectOwnerUserId = "user-1";
    db.artifacts = [
      {
        id: "brief-1",
        artifact_type: "retrieval_brief",
        title: "Context Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "Should not attach.",
        },
        visibility: "private",
        owner_user_id: "user-1",
        project_id: null,
        workspace_id: "ws-1",
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];
    db.contextArtifactRevocations = [
      {
        id: "revocation-1",
        space_id: "space-1",
        artifact_id: "brief-1",
        scope_type: "project",
        scope_id: "project-1",
        reason: "superseded by newer brief",
        created_by_user_id: "user-1",
        created_at: "2026-06-26T00:00:00.000Z",
        deleted_at: null,
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-1",
      projectId: "project-1",
      artifactIds: ["brief-1"],
    });

    expect(selections[0].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact is revoked for this project context: superseded by newer brief",
    });
  });

  it("re-gates a non-owner attaching a source-derived brief the viewer's source policy denies (G3)", async () => {
    const db = new CapturingDb();
    db.viewerRole = "member";
    db.sourceSnapshotRows = [
      {
        id: "src-denied",
        owner_user_id: "owner-2",
        consent_json: {
          schema_version: 1,
          owner_user_id: "owner-2",
          allowed_reader_user_ids: [],
          allowed_agent_ids: [],
          allow_space_admins: false,
          allow_local_provider_egress: true,
          allow_external_model_egress: false,
        },
        policy_json: { schema_version: 1, source_egress_class: "local_provider_allowed" },
      },
    ];
    db.artifacts = [
      {
        id: "brief-shared",
        artifact_type: "retrieval_brief",
        title: "Shared Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "Derived from a restricted source.",
          source_connection_ids: ["src-denied"],
        },
        visibility: "space_shared",
        owner_user_id: "other-user",
        project_id: null,
        workspace_id: null,
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: null,
      artifactIds: ["brief-shared"],
    });

    expect(selections[0].item.approved).toBe(false);
    expect(String(selections[0].item.rejection_reason)).toContain("source policy");
  });

  it("re-gates workspace_shared source-derived briefs after workspace visibility passes (G3)", async () => {
    const db = new CapturingDb();
    db.viewerRole = "member";
    db.accessibleWorkspaceIds.add("ws-1");
    db.sourceSnapshotRows = [
      {
        id: "src-denied",
        owner_user_id: "owner-2",
        consent_json: {
          schema_version: 1,
          owner_user_id: "owner-2",
          allowed_reader_user_ids: [],
          allowed_agent_ids: [],
          allow_space_admins: false,
          allow_local_provider_egress: true,
          allow_external_model_egress: false,
        },
        policy_json: { schema_version: 1, source_egress_class: "local_provider_allowed" },
      },
    ];
    db.artifacts = [
      {
        id: "brief-workspace",
        artifact_type: "retrieval_brief",
        title: "Workspace Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "Derived from a restricted source.",
          source_connection_ids: ["src-denied"],
        },
        visibility: "workspace_shared",
        owner_user_id: "other-user",
        project_id: null,
        workspace_id: "ws-1",
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-1",
      artifactIds: ["brief-workspace"],
    });

    expect(selections[0].item.approved).toBe(false);
    expect(String(selections[0].item.rejection_reason)).toContain("source policy");
  });

  it("does not re-gate the owner attaching their own source-derived brief (G3)", async () => {
    const db = new CapturingDb();
    db.artifacts = [
      {
        id: "brief-own",
        artifact_type: "retrieval_brief",
        title: "Own Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "My own answer.",
          source_connection_ids: ["src-denied"],
        },
        visibility: "private",
        owner_user_id: "user-1",
        project_id: null,
        workspace_id: null,
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: null,
      artifactIds: ["brief-own"],
    });

    expect(selections[0].item.approved).toBe(true);
    expect(selections[0].item.source_policy_snapshot).toMatchObject({
      source_connection_ids: ["src-denied"],
      current_reader_gate: expect.objectContaining({
        enforced_for_attachment: false,
      }),
    });
  });

  it("blocks workspace_shared artifact attachments without inherited project workspace access", async () => {
    const db = new CapturingDb();
    db.artifacts = [
      {
        id: "brief-1",
        artifact_type: "retrieval_brief",
        title: "Workspace Brief",
        content: null,
        metadata_json: {
          kind: "retrieval_brief",
          answer: "Workspace scoped answer.",
        },
        visibility: "workspace_shared",
        owner_user_id: "other-user",
        project_id: null,
        workspace_id: "ws-1",
        created_at: "2026-06-25T00:00:00.000Z",
      },
    ];

    const selections = await new PgRunContextRepository(db).selectArtifactAttachments({
      spaceId: "space-1",
      userId: "user-1",
      workspaceId: "ws-1",
      artifactIds: ["brief-1"],
    });

    expect(selections[0].item).toMatchObject({
      approved: false,
      rejection_reason: "artifact not found or not visible",
    });
  });
});
