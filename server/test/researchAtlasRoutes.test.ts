import { describe, expect, it, beforeAll, afterAll, beforeEach } from "vitest";
import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { validateProposalPayload } from "../src/modules/proposals/payloadSchemas";
import { loadProtocol } from "../src/modules/providers/protocolRuntime";
import { loadResearchAtlasRuntime } from "./researchAtlasRuntime";

const {
  plugin: { researchAtlasPlugin },
  routes: { registerResearchAtlasRoutes },
  service: { researchAtlasService },
  jobs: { buildResearchAtlasEnrichEntityHandler },
  proposalAppliers: {
    PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION,
    applyResearchAtlasCuration,
  },
} = loadResearchAtlasRuntime();

let container: StartedPostgreSqlContainer | null = null;
let pool: Pool | null = null;
let app: FastifyInstance | null = null;
let enqueuedJobs: Array<{ jobType: string; payload: Record<string, unknown> }> = [];
let available = false;

const guardState = {
  enabled: true,
  spaceId: "space-research-atlas-routes",
  userId: "user-research-atlas-routes",
};

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
  } catch (err) {
    console.warn(
      `[research-atlas-routes] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return;
  }
  for (const migration of researchAtlasPlugin.migrations!) {
    await pool.query(migration.sql);
  }
  await pool.query(
    `CREATE TABLE source_items (
       id varchar(36) NOT NULL PRIMARY KEY,
       space_id varchar(36) NOT NULL,
       connection_id varchar(36),
       item_type varchar(64) NOT NULL,
       title varchar(1024) NOT NULL,
       source_external_id varchar(512),
       author varchar(512),
       excerpt varchar(2048),
       source_uri text,
       canonical_uri text,
       metadata_json jsonb,
       created_at timestamptz NOT NULL,
       updated_at timestamptz NOT NULL,
       deleted_at timestamptz
     )`,
  );
  await pool.query(
    `CREATE TABLE projects (
       id varchar(36) NOT NULL PRIMARY KEY,
       space_id varchar(36) NOT NULL,
       owner_user_id varchar(36),
       deleted_at timestamptz
     )`,
  );
  await pool.query(
    `CREATE TABLE project_members (
       id varchar(36) NOT NULL PRIMARY KEY,
       space_id varchar(36) NOT NULL,
       project_id varchar(36) NOT NULL,
       user_id varchar(36) NOT NULL,
       role varchar(32) NOT NULL,
       status varchar(32) NOT NULL
     )`,
  );
  await pool.query(
    `CREATE TABLE space_memberships (
       id varchar(36) NOT NULL PRIMARY KEY,
       space_id varchar(36) NOT NULL,
       user_id varchar(36) NOT NULL,
       role varchar(32) NOT NULL,
       status varchar(32) NOT NULL
     )`,
  );
  await pool.query(
    `CREATE TABLE workspace_source_bindings (
       id varchar(36) NOT NULL PRIMARY KEY,
       space_id varchar(36) NOT NULL,
       project_id varchar(36) NOT NULL,
       source_connection_id varchar(36) NOT NULL,
       status varchar(32) NOT NULL
     )`,
  );

  app = Fastify();
  const fakeCtx = {
    pluginId: "research_atlas",
    fastify: app,
    db: pool,
    config: {},
    isEnabled: async () => guardState.enabled,
    http: {
      resolveIdentity: async () => identity(),
      pluginGuard: async (_request: FastifyRequest, reply: FastifyReply) => {
        if (!guardState.enabled) {
          reply.code(403).send({ detail: "plugin research_atlas is disabled" });
          return null;
        }
        return identity();
      },
      sendError: (reply: FastifyReply, err: unknown) => {
        reply.code(500).send({ detail: err instanceof Error ? err.message : "error" });
      },
      parseJsonBody: (request: FastifyRequest) =>
        (request.body ?? {}) as Record<string, unknown>,
    },
    jobs: {
      register: () => {},
      enqueue: async (jobType: string, payload: Record<string, unknown>) => {
        enqueuedJobs.push({ jobType, payload });
        return { jobId: `job-${enqueuedJobs.length}` };
      },
    },
    scheduler: { register: () => {} },
    proposals: { register: () => {} },
  };
  registerResearchAtlasRoutes(app, pool, fakeCtx);
  await app.ready();
  available = true;
}, 60_000);

afterAll(async () => {
  await app?.close();
  await pool?.end();
  await container?.stop();
});

beforeEach(async (context) => {
  if (!available || !pool) {
    context.skip();
    return;
  }
  guardState.enabled = true;
  enqueuedJobs = [];
  await pool.query(
     `TRUNCATE TABLE
       workspace_source_bindings,
       project_members,
       projects,
       space_memberships,
       source_items,
       research_atlas_sync_cursors,
       research_atlas_saved_views,
       research_atlas_project_groups,
       research_atlas_project_scholars,
       research_atlas_scholar_topics,
       research_atlas_paper_topics,
       research_atlas_group_memberships,
       research_atlas_citation_edges,
       research_atlas_affiliations,
       research_atlas_research_groups,
       research_atlas_topics,
       research_atlas_departments,
       research_atlas_project_papers,
       research_atlas_curation_events,
       research_atlas_entity_sources,
       research_atlas_external_ids,
       research_atlas_authorships,
       research_atlas_source_records,
       research_atlas_papers,
       research_atlas_scholars,
       research_atlas_institutions,
       research_atlas_venues
     CASCADE`,
  );
});

function identity() {
  return { userId: guardState.userId, spaceId: guardState.spaceId };
}

describe("research atlas routes", () => {
  it("fails closed when the plugin is disabled", async () => {
    guardState.enabled = false;
    const response = await app!.inject({ method: "GET", url: "/api/v1/atlas/status" });
    expect(response.statusCode).toBe(403);
    expect(response.json().detail).toContain("disabled");
  });

  it("returns guarded plugin status", async () => {
    const response = await app!.inject({ method: "GET", url: "/api/v1/atlas/status" });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      ok: true,
      plugin_id: "research_atlas",
      version: "0.1.0",
      scope: "space",
      space_id: guardState.spaceId,
    });
  });

  it("imports BibTeX exports through the file import endpoint", async () => {
    const response = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import-file",
      payload: {
        format: "bibtex",
        content: `
          @article{atlas2026,
            title = {Atlas from BibTeX},
            author = {Ada Lovelace and Grace Hopper},
            year = {2026},
            doi = {10.7777/bibtex-atlas},
            journal = {Journal of Test Graphs}
          }
        `,
      },
    });
    expect(response.statusCode).toBe(200);
    expect(response.json().count).toBe(1);
    expect(response.json().imported[0].paper.title).toBe("Atlas from BibTeX");

    const authors = await pool!.query<{ raw_author_name: string }>(
      "SELECT raw_author_name FROM research_atlas_authorships ORDER BY author_position",
    );
    expect(authors.rows.map((row) => row.raw_author_name)).toEqual(["Ada Lovelace", "Grace Hopper"]);
  });

  it("syncs arXiv source items with a cursor and source provenance", async () => {
    await pool!.query(
      `INSERT INTO source_items (
         id, space_id, item_type, title, source_external_id, author, excerpt,
         source_uri, canonical_uri, metadata_json, created_at, updated_at
       ) VALUES ($1, $2, 'feed_entry', $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $10)`,
      [
        "source-arxiv-1",
        guardState.spaceId,
        "A synced arXiv paper",
        "2401.00001",
        "Ada Lovelace, Grace Hopper",
        "An arXiv abstract",
        "https://arxiv.org/abs/2401.00001",
        "https://arxiv.org/abs/2401.00001",
        JSON.stringify({
          arxiv_id: "2401.00001v2",
          authors: ["Ada Lovelace", "Grace Hopper"],
          categories: ["cs.AI"],
          pdf_url: "https://arxiv.org/pdf/2401.00001",
        }),
        new Date("2026-07-04T00:00:00Z"),
      ],
    );

    const sync = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/sync/sources",
    });
    expect(sync.statusCode).toBe(200);
    expect(sync.json()).toEqual({ imported: 1, scanned: 1, last_error: null });

    const detail = await app!.inject({ method: "GET", url: "/api/v1/atlas/papers?q=synced" });
    expect(detail.json().papers).toEqual([
      expect.objectContaining({
        title: "A synced arXiv paper",
        arxiv_id: "2401.00001",
      }),
    ]);

    const source = await pool!.query<{ source_item_id: string }>(
      "SELECT source_item_id FROM research_atlas_source_records WHERE connector = 'source'",
    );
    expect(source.rows[0]!.source_item_id).toBe("source-arxiv-1");

    const status = await app!.inject({ method: "GET", url: "/api/v1/atlas/settings" });
    expect(status.statusCode).toBe(200);
    expect(status.json().cursors).toEqual([
      expect.objectContaining({ cursor_key: "source_items", last_error: null }),
    ]);

    const again = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/sync/sources",
    });
    expect(again.statusCode).toBe(200);
    expect(again.json()).toEqual({ imported: 0, scanned: 0, last_error: null });
  });

  it("imports a DOI idempotently, then lists, searches, and reads detail", async () => {
    const first = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "https://doi.org/10.5555/Atlas.Test" },
    });
    expect(first.statusCode).toBe(201);
    expect(first.json().status).toBe("created");
    expect(first.json().paper.doi).toBe("10.5555/atlas.test");
    expect(first.json().job_id).toBe("job-1");
    expect(enqueuedJobs).toEqual([
      expect.objectContaining({
        jobType: "research_atlas_enrich_entity",
        payload: expect.objectContaining({ connector: "crossref" }),
      }),
    ]);

    const second = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.5555/ATLAS.TEST" },
    });
    expect(second.statusCode).toBe(200);
    expect(second.json().status).toBe("matched");
    expect(second.json().paper.id).toBe(first.json().paper.id);

    const count = await pool!.query<{ count: string }>("SELECT count(*)::text FROM research_atlas_papers");
    expect(count.rows[0]!.count).toBe("1");

    const list = await app!.inject({ method: "GET", url: "/api/v1/atlas/papers?q=atlas" });
    expect(list.statusCode).toBe(200);
    expect(list.json().papers).toHaveLength(1);

    const search = await app!.inject({ method: "GET", url: "/api/v1/atlas/search?q=atlas" });
    expect(search.statusCode).toBe(200);
    expect(search.json().results).toEqual([
      expect.objectContaining({ entity_type: "paper", id: first.json().paper.id }),
    ]);

    const detail = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${first.json().paper.id}`,
    });
    expect(detail.statusCode).toBe(200);
    expect(detail.json().external_ids).toEqual([
      expect.objectContaining({ id_type: "doi", id_value: "10.5555/atlas.test" }),
    ]);
  });

  it("keeps locked title corrections through connector refresh and exposes scholars", async () => {
    const imported = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.4242/locked-title" },
    });
    const paperId = imported.json().paper.id as string;

    const patched = await app!.inject({
      method: "PATCH",
      url: `/api/v1/atlas/papers/${paperId}`,
      payload: { title: "Curated title" },
    });
    expect(patched.statusCode).toBe(200);
    expect(patched.json().paper.title).toBe("Curated title");

    const refreshed = await researchAtlasService.refreshPaperFromConnector(pool, {
      spaceId: guardState.spaceId,
      paperId,
      connector: "crossref",
      metadata: {
        title: "Connector title",
        abstract: "Connector abstract",
        publication_year: 2026,
        raw_author_names: ["Ada Lovelace"],
        authors: [{ name: "Ada Lovelace", orcid: "0000-0001-0002-0003" }],
      },
    });
    expect(refreshed.refreshed).toBe(true);
    expect(refreshed.paper.title).toBe("Curated title");
    expect(refreshed.paper.abstract).toBe("Connector abstract");

    const author = await pool!.query<{ scholar_id: string }>(
      "SELECT scholar_id FROM research_atlas_authorships WHERE paper_id = $1",
      [paperId],
    );
    const scholarId = author.rows[0]!.scholar_id;
    const scholar = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/scholars/${scholarId}`,
    });
    expect(scholar.statusCode).toBe(200);
    expect(scholar.json().scholar.display_name).toBe("Ada Lovelace");
    expect(scholar.json().papers).toEqual([
      expect.objectContaining({ id: paperId, title: "Curated title" }),
    ]);
  });

  it("merges duplicate papers and resolves the loser id to the winner", async () => {
    const winner = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.1111/winner" },
    });
    const loser = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { arxiv_id: "2401.12345v2" },
    });

    const merged = await app!.inject({
      method: "POST",
      url: `/api/v1/atlas/entities/paper/${winner.json().paper.id}/merge`,
      payload: { loser_id: loser.json().paper.id },
    });
    expect(merged.statusCode).toBe(200);
    expect(merged.json()).toEqual({
      merged: true,
      winner_id: winner.json().paper.id,
      loser_id: loser.json().paper.id,
    });

    const loserDetail = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${loser.json().paper.id}`,
    });
    expect(loserDetail.statusCode).toBe(200);
    expect(loserDetail.json().paper.id).toBe(winner.json().paper.id);
  });

  it("serves citation neighborhoods, graph data, and incremental NDJSON export", async () => {
    const center = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.5555/graph-center" },
    });
    const referenced = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.5555/graph-reference" },
    });
    const citing = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.5555/graph-citation" },
    });
    const centerId = center.json().paper.id as string;
    const referencedId = referenced.json().paper.id as string;
    const citingId = citing.json().paper.id as string;

    await app!.inject({
      method: "PATCH",
      url: `/api/v1/atlas/papers/${centerId}`,
      payload: { title: "Center graph paper" },
    });
    await app!.inject({
      method: "PATCH",
      url: `/api/v1/atlas/papers/${referencedId}`,
      payload: { title: "Referenced graph paper" },
    });
    await app!.inject({
      method: "PATCH",
      url: `/api/v1/atlas/papers/${citingId}`,
      payload: { title: "Citing graph paper" },
    });
    await pool!.query(
      `INSERT INTO research_atlas_citation_edges
         (id, space_id, citing_paper_id, cited_paper_id, source, confidence)
       VALUES
         ($1, $2, $3, $4, 'manual', 1),
         ($5, $2, $6, $3, 'manual', 0.8)`,
      ["edge-reference", guardState.spaceId, centerId, referencedId, "edge-citation", citingId],
    );

    const references = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${centerId}/references`,
    });
    expect(references.statusCode).toBe(200);
    expect(references.json().papers).toEqual([
      expect.objectContaining({ id: referencedId, title: "Referenced graph paper" }),
    ]);

    const citations = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${centerId}/citations`,
    });
    expect(citations.statusCode).toBe(200);
    expect(citations.json().papers).toEqual([
      expect.objectContaining({ id: citingId, title: "Citing graph paper" }),
    ]);

    const related = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${centerId}/related`,
    });
    expect(related.statusCode).toBe(200);
    expect(related.json().references).toEqual([
      expect.objectContaining({ id: referencedId }),
    ]);
    expect(related.json().citations).toEqual([
      expect.objectContaining({ id: citingId }),
    ]);

    const graph = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/graph?paper_id=${centerId}`,
    });
    expect(graph.statusCode).toBe(200);
    const protocol = await loadProtocol();
    const parsedGraph = protocol.GraphProjectionSchema.parse(graph.json());
    expect(parsedGraph.view).toMatchObject({
      mode: "local",
      rootId: `paper:${centerId}`,
      depth: 1,
      limit: 100,
    });
    expect(parsedGraph.layout).toEqual({ mode: "force" });
    expect(parsedGraph.nodes).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: `paper:${centerId}`,
        kind: "paper",
        label: "Center graph paper",
        metadata: expect.objectContaining({ paperId: centerId, root: true }),
      }),
      expect.objectContaining({ id: `paper:${referencedId}`, kind: "paper", label: "Referenced graph paper" }),
      expect.objectContaining({ id: `paper:${citingId}`, kind: "paper", label: "Citing graph paper" }),
    ]));
    expect(parsedGraph.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: `references:${centerId}:${referencedId}`,
        source: `paper:${centerId}`,
        target: `paper:${referencedId}`,
        kind: "references",
        metadata: expect.objectContaining({ direction: "reference" }),
      }),
      expect.objectContaining({
        id: `references:${citingId}:${centerId}`,
        source: `paper:${citingId}`,
        target: `paper:${centerId}`,
        kind: "references",
        metadata: expect.objectContaining({ direction: "citation" }),
      }),
    ]));

    const missingGraph = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/graph?paper_id=missing-paper",
    });
    expect(missingGraph.statusCode).toBe(404);

    const handler = buildResearchAtlasEnrichEntityHandler(pool);
    const fillResult = await handler({
      job_id: "job-s2-citations",
      job_type: "research_atlas_enrich_entity",
      attempt_number: 1,
      payload: {
        space_id: guardState.spaceId,
        user_id: guardState.userId,
        paper_id: centerId,
        connector: "s2",
        metadata: {
          references: [{ doi: "10.5555/s2-reference", title: "S2 Reference", year: 2026 }],
          citations: [{ doi: "10.5555/s2-citation", title: "S2 Citation", year: 2026 }],
        },
      },
    });
    expect(fillResult).toEqual(expect.objectContaining({
      refreshed: true,
      paper_id: centerId,
      citation_fill: { references: 1, citations: 1 },
    }));

    const filledReferences = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${centerId}/references`,
    });
    expect(filledReferences.json().papers).toEqual(expect.arrayContaining([
      expect.objectContaining({ doi: "10.5555/s2-reference", title: "S2 Reference" }),
    ]));
    const filledCitations = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/papers/${centerId}/citations`,
    });
    expect(filledCitations.json().papers).toEqual(expect.arrayContaining([
      expect.objectContaining({ doi: "10.5555/s2-citation", title: "S2 Citation" }),
    ]));

    await pool!.query(
      `UPDATE research_atlas_papers
          SET merged_into_id = $1
        WHERE space_id = $2
          AND id = $3`,
      [centerId, guardState.spaceId, referencedId],
    );

    const firstExportPage = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/export/entities?type=paper&limit=1",
    });
    expect(firstExportPage.statusCode).toBe(200);
    expect(firstExportPage.headers["x-next-cursor"]).toEqual(expect.any(String));
    const firstExportLine = JSON.parse(firstExportPage.body.trim());
    expect(firstExportLine.cursor).toEqual(expect.objectContaining({
      id: firstExportLine.data.id,
      updated_at: expect.any(String),
    }));

    const secondExportPage = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/export/entities?type=paper&limit=10&cursor=${encodeURIComponent(String(firstExportPage.headers["x-next-cursor"]))}`,
    });
    expect(secondExportPage.statusCode).toBe(200);
    const secondExportLines = secondExportPage.body.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
    expect(secondExportLines.map((line) => line.data.id)).not.toContain(firstExportLine.data.id);

    const exported = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/export/entities?type=paper",
    });
    expect(exported.statusCode).toBe(200);
    expect(exported.headers["content-type"]).toContain("application/x-ndjson");
    const lines = exported.body.trim().split("\n").map((line) => JSON.parse(line));
    expect(lines.find((line) => line.data.id === referencedId)).toEqual(expect.objectContaining({
      tombstone: { kind: "merge", merged_into_id: centerId },
      data: expect.objectContaining({ merged_into_id: centerId }),
    }));
    expect(lines).toEqual(expect.arrayContaining([
      expect.objectContaining({
        schema_version: 1,
        entity_type: "paper",
        cursor: expect.objectContaining({ id: centerId, updated_at: expect.any(String) }),
        tombstone: null,
        data: expect.objectContaining({ id: centerId, title: "Center graph paper" }),
      }),
    ]));

    const activeOnlyExport = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/export/entities?type=paper&active_only=true",
    });
    expect(activeOnlyExport.statusCode).toBe(200);
    const activeOnlyLines = activeOnlyExport.body.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
    expect(activeOnlyLines.map((line) => line.data.id)).not.toContain(referencedId);
  });

  it("curates research groups through routes and the proposal applier", async () => {
    await pool!.query(
      `INSERT INTO research_atlas_institutions (id, space_id, name)
       VALUES ($1, $2, $3)`,
      ["institution-atlas", guardState.spaceId, "Atlas University"],
    );
    await pool!.query(
      `INSERT INTO research_atlas_departments (id, space_id, institution_id, name)
       VALUES ($1, $2, $3, $4)`,
      ["department-atlas", guardState.spaceId, "institution-atlas", "Computer Science"],
    );
    await pool!.query(
      `INSERT INTO research_atlas_scholars (id, space_id, display_name)
       VALUES ($1, $2, $3), ($4, $2, $5)`,
      ["scholar-pi", guardState.spaceId, "Ada Lovelace", "scholar-member", "Grace Hopper"],
    );
    await pool!.query(
      `INSERT INTO research_atlas_papers (id, space_id, title, paper_type, oa_status)
       VALUES ($1, $2, $3, 'article', 'unknown')`,
      ["paper-coauthor", guardState.spaceId, "Coauthored graph paper"],
    );
    await pool!.query(
      `INSERT INTO research_atlas_authorships
         (id, space_id, paper_id, scholar_id, author_position, raw_author_name)
       VALUES
         ($1, $2, $3, $4, 1, $5),
         ($6, $2, $3, $7, 2, $8)`,
      [
        "authorship-pi",
        guardState.spaceId,
        "paper-coauthor",
        "scholar-pi",
        "Ada Lovelace",
        "authorship-member",
        "scholar-member",
        "Grace Hopper",
      ],
    );
    await pool!.query(
      `INSERT INTO research_atlas_affiliations
         (id, space_id, scholar_id, institution_id, department_id, role, source, confidence)
       VALUES ($1, $2, $3, $4, $5, $6, 'manual', 1)`,
      [
        "affiliation-member",
        guardState.spaceId,
        "scholar-member",
        "institution-atlas",
        "department-atlas",
        "faculty",
      ],
    );

    const created = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/groups",
      payload: {
        name: "Atlas Lab",
        aliases: ["AL"],
        pi_scholar_id: "scholar-pi",
        confidence: 0.9,
      },
    });
    expect(created.statusCode).toBe(201);
    const groupId = created.json().group.id as string;
    expect(created.json().group).toEqual(expect.objectContaining({
      name: "Atlas Lab",
      aliases: ["AL"],
      pi_scholar_id: "scholar-pi",
    }));

    const listed = await app!.inject({ method: "GET", url: "/api/v1/atlas/groups" });
    expect(listed.statusCode).toBe(200);
    expect(listed.json().groups).toEqual([
      expect.objectContaining({ id: groupId, name: "Atlas Lab", member_count: 0 }),
    ]);

    const manualMember = await app!.inject({
      method: "POST",
      url: `/api/v1/atlas/groups/${groupId}/members`,
      payload: { scholar_id: "scholar-pi", role: "pi", confidence: 1 },
    });
    expect(manualMember.statusCode).toBe(201);
    expect(manualMember.json().membership).toEqual(expect.objectContaining({
      group_id: groupId,
      scholar_id: "scholar-pi",
      role: "pi",
      source: "manual",
    }));

    expect(() => validateProposalPayload(PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION, {
      action: "add_group_membership",
      group_id: groupId,
      scholar_id: "scholar-member",
      role: "phd_student",
    })).not.toThrow();
    await applyResearchAtlasCuration({
      proposal: {
        id: "proposal-atlas-membership",
        proposal_type: PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION,
        space_id: guardState.spaceId,
        user_id: guardState.userId,
        payload: {
          action: "add_group_membership",
          group_id: groupId,
          scholar_id: "scholar-member",
          role: "phd_student",
          confidence: 0.82,
        },
      },
      db: pool,
      config: {},
    });
    await applyResearchAtlasCuration({
      proposal: {
        id: "proposal-atlas-membership-repeat",
        proposal_type: PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION,
        space_id: guardState.spaceId,
        user_id: guardState.userId,
        payload: {
          action: "add_group_membership",
          group_id: groupId,
          scholar_id: "scholar-member",
          role: "phd_student",
          confidence: 0.9,
        },
      },
      db: pool,
      config: {},
    });

    const group = await app!.inject({
      method: "GET",
      url: `/api/v1/atlas/groups/${groupId}`,
    });
    expect(group.statusCode).toBe(200);
    expect(group.json().members).toEqual(expect.arrayContaining([
      expect.objectContaining({
        scholar_id: "scholar-member",
        role: "phd_student",
        source: "agent_proposal",
        confidence: 0.9,
        scholar: expect.objectContaining({ display_name: "Grace Hopper" }),
      }),
    ]));
    const membershipCount = await pool!.query<{ count: string }>(
      `SELECT count(*)::text
         FROM research_atlas_group_memberships
        WHERE group_id = $1
          AND scholar_id = 'scholar-member'
          AND role = 'phd_student'`,
      [groupId],
    );
    expect(membershipCount.rows[0]!.count).toBe("1");

    const scholar = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/scholars/scholar-member",
    });
    expect(scholar.statusCode).toBe(200);
    expect(scholar.json().coauthors).toEqual([
      expect.objectContaining({ id: "scholar-pi", shared_paper_count: 1 }),
    ]);
    expect(scholar.json().affiliations).toEqual([
      expect.objectContaining({
        scholar_id: "scholar-member",
        institution: expect.objectContaining({ name: "Atlas University" }),
        department: expect.objectContaining({ name: "Computer Science" }),
      }),
    ]);
  });

  it("manages a project literature workspace with authority checks", async () => {
    await seedProject("project-atlas-1", guardState.userId);
    const imported = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/papers/import",
      payload: { doi: "10.4444/project-paper" },
    });
    const paperId = imported.json().paper.id as string;

    const add = await app!.inject({
      method: "POST",
      url: "/api/v1/atlas/projects/project-atlas-1/papers",
      payload: { paper_id: paperId, status: "shortlist" },
    });
    expect(add.statusCode).toBe(201);
    expect(add.json().project_paper).toEqual(expect.objectContaining({
      project_id: "project-atlas-1",
      paper_id: paperId,
      status: "shortlist",
    }));

    const update = await app!.inject({
      method: "PATCH",
      url: `/api/v1/atlas/projects/project-atlas-1/papers/${paperId}`,
      payload: {
        status: "reading",
        read_status: "skimmed",
        rating: 4,
        tags: ["core", "todo"],
        note: "Read methods section",
        pinned: true,
      },
    });
    expect(update.statusCode).toBe(200);
    expect(update.json().project_paper).toEqual(expect.objectContaining({
      status: "reading",
      read_status: "skimmed",
      rating: 4,
      pinned: true,
    }));

    const list = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/projects/project-atlas-1/papers",
    });
    expect(list.statusCode).toBe(200);
    expect(list.json().papers).toEqual([
      expect.objectContaining({
        paper_id: paperId,
        source_item_id: null,
        paper: expect.objectContaining({ id: paperId }),
      }),
    ]);

    guardState.userId = "project-outsider";
    const hidden = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/projects/project-atlas-1/papers",
    });
    expect(hidden.statusCode).toBe(404);
    guardState.userId = "user-research-atlas-routes";

    const remove = await app!.inject({
      method: "DELETE",
      url: `/api/v1/atlas/projects/project-atlas-1/papers/${paperId}`,
    });
    expect(remove.statusCode).toBe(200);
    expect(remove.json()).toEqual({ deleted: true });
  });

  it("auto-adds source-synced papers as project candidates for bound sources", async () => {
    await seedProject("project-atlas-sync", guardState.userId);
    await pool!.query(
      `INSERT INTO workspace_source_bindings
         (id, space_id, project_id, source_connection_id, status)
       VALUES ($1, $2, $3, $4, 'active')`,
      ["binding-1", guardState.spaceId, "project-atlas-sync", "source-arxiv-1"],
    );
    await pool!.query(
      `INSERT INTO source_items (
         id, space_id, connection_id, item_type, title, source_external_id, author, excerpt,
         source_uri, canonical_uri, metadata_json, created_at, updated_at
       ) VALUES ($1, $2, $3, 'feed_entry', $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $11)`,
      [
        "source-arxiv-project",
        guardState.spaceId,
        "source-arxiv-1",
        "A project-bound arXiv paper",
        "2401.00002",
        "Ada Lovelace",
        "A project abstract",
        "https://arxiv.org/abs/2401.00002",
        "https://arxiv.org/abs/2401.00002",
        JSON.stringify({ arxiv_id: "2401.00002" }),
        new Date("2026-07-04T00:10:00Z"),
      ],
    );

    const sync = await app!.inject({ method: "POST", url: "/api/v1/atlas/sync/sources" });
    expect(sync.statusCode).toBe(200);
    const list = await app!.inject({
      method: "GET",
      url: "/api/v1/atlas/projects/project-atlas-sync/papers",
    });
    expect(list.statusCode).toBe(200);
    expect(list.json().papers).toEqual([
      expect.objectContaining({
        status: "candidate",
        source: "source_sync",
        source_item_id: "source-arxiv-project",
        paper: expect.objectContaining({ title: "A project-bound arXiv paper" }),
      }),
    ]);
  });
});

async function seedProject(projectId: string, ownerUserId: string): Promise<void> {
  await pool!.query(
    "INSERT INTO projects (id, space_id, owner_user_id) VALUES ($1, $2, $3)",
    [projectId, guardState.spaceId, ownerUserId],
  );
  await pool!.query(
    "INSERT INTO space_memberships (id, space_id, user_id, role, status) VALUES ($1, $2, $3, $4, 'active')",
    [`space-member-${projectId}`, guardState.spaceId, ownerUserId, "owner"],
  );
  await pool!.query(
    "INSERT INTO project_members (id, space_id, project_id, user_id, role, status) VALUES ($1, $2, $3, $4, $5, 'active')",
    [`project-member-${projectId}`, guardState.spaceId, projectId, ownerUserId, "owner"],
  );
}
