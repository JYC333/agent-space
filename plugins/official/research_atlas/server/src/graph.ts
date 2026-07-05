import { Buffer } from "node:buffer";
import { randomUUID } from "node:crypto";
import type { FastifyReply } from "fastify";
import type {
  GraphProjection,
  GraphProjectionEdge,
  GraphProjectionNode,
  Queryable,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import { AtlasRequestError } from "./domain/service";

const LIBRARY_PAPER_LIMIT = 250;
const LIBRARY_AUTHOR_EDGE_LIMIT = 800;
const LIBRARY_CITATION_EDGE_LIMIT = 800;

export async function listPaperReferences(db: Queryable, spaceId: string, paperId: string): Promise<{ papers: PaperGraphRow[] }> {
  return listCitationNeighbors(db, spaceId, paperId, "references");
}

export async function listPaperCitations(db: Queryable, spaceId: string, paperId: string): Promise<{ papers: PaperGraphRow[] }> {
  return listCitationNeighbors(db, spaceId, paperId, "citations");
}

export async function listPaperRelated(db: Queryable, spaceId: string, paperId: string) {
  const references = await listPaperReferences(db, spaceId, paperId);
  const citations = await listPaperCitations(db, spaceId, paperId);
  const coauthors = await db.query(
    `SELECT DISTINCT s.id, s.display_name
       FROM research_atlas_authorships a
       JOIN research_atlas_authorships same_paper ON same_paper.paper_id = a.paper_id
       JOIN research_atlas_scholars s ON s.id = same_paper.scholar_id
      WHERE a.space_id = $1
        AND a.paper_id = $2
        AND same_paper.scholar_id IS NOT NULL
      ORDER BY s.display_name
      LIMIT 25`,
    [spaceId, paperId],
  );
  return {
    references: references.papers,
    citations: citations.papers,
    coauthors: coauthors.rows,
  };
}

export async function getScholarGraphContext(db: Queryable, spaceId: string, scholarId: string) {
  const coauthors = await db.query(
    `SELECT s.id, s.display_name, count(DISTINCT self.paper_id)::int AS shared_paper_count
       FROM research_atlas_authorships self
       JOIN research_atlas_authorships other
         ON other.space_id = self.space_id
        AND other.paper_id = self.paper_id
        AND other.scholar_id IS NOT NULL
        AND other.scholar_id <> self.scholar_id
       JOIN research_atlas_scholars s
         ON s.space_id = other.space_id
        AND s.id = other.scholar_id
      WHERE self.space_id = $1
        AND self.scholar_id = $2
      GROUP BY s.id, s.display_name
      ORDER BY shared_paper_count DESC, s.display_name
      LIMIT 25`,
    [spaceId, scholarId],
  );
  const affiliations = await db.query(
    `SELECT a.*, row_to_json(i.*) AS institution, row_to_json(d.*) AS department
       FROM research_atlas_affiliations a
       JOIN research_atlas_institutions i
         ON i.space_id = a.space_id
        AND i.id = a.institution_id
       LEFT JOIN research_atlas_departments d
         ON d.space_id = a.space_id
        AND d.id = a.department_id
      WHERE a.space_id = $1
        AND a.scholar_id = $2
      ORDER BY a.end_date DESC NULLS FIRST, a.start_date DESC NULLS LAST, i.name
      LIMIT 50`,
    [spaceId, scholarId],
  );
  return { coauthors: coauthors.rows, affiliations: affiliations.rows };
}

export async function listTopics(db: Queryable, spaceId: string) {
  const result = await db.query(
    `SELECT *
       FROM research_atlas_topics
      WHERE space_id = $1
        AND merged_into_id IS NULL
      ORDER BY taxonomy, label
      LIMIT 200`,
    [spaceId],
  );
  return { topics: result.rows };
}

export async function listGroups(db: Queryable, spaceId: string) {
  const result = await db.query(
    `SELECT g.*, COALESCE(counts.member_count, 0)::int AS member_count
       FROM research_atlas_research_groups g
       LEFT JOIN LATERAL (
         SELECT count(*)::int AS member_count
           FROM research_atlas_group_memberships gm
          WHERE gm.space_id = g.space_id
            AND gm.group_id = g.id
       ) counts ON true
      WHERE g.space_id = $1
        AND g.merged_into_id IS NULL
      ORDER BY g.updated_at DESC, g.name
      LIMIT 100`,
    [spaceId],
  );
  return { groups: result.rows };
}

export async function getGroup(db: Queryable, spaceId: string, groupId: string) {
  const group = await db.query(
    `SELECT *
       FROM research_atlas_research_groups
      WHERE space_id = $1
        AND id = $2
      LIMIT 1`,
    [spaceId, groupId],
  );
  if (!group.rows[0]) throw new AtlasRequestError(404, "group not found");
  const members = await db.query(
    `SELECT gm.*, row_to_json(s.*) AS scholar
       FROM research_atlas_group_memberships gm
       JOIN research_atlas_scholars s
         ON s.space_id = gm.space_id
        AND s.id = gm.scholar_id
      WHERE gm.space_id = $1
        AND gm.group_id = $2
      ORDER BY gm.role, s.display_name`,
    [spaceId, groupId],
  );
  return { group: group.rows[0], members: members.rows };
}

export async function createGroup(
  db: Queryable,
  input: {
    spaceId: string;
    name: string;
    aliases?: string[];
    piScholarId?: string | null;
    confidence?: number | null;
  },
) {
  const result = await db.query(
    `INSERT INTO research_atlas_research_groups (
       id, space_id, name, aliases, pi_scholar_id, status, confidence, curation_status, created_at, updated_at
     ) VALUES ($1, $2, $3, $4::jsonb, $5, 'unknown', $6, 'user_curated', $7, $7)
     RETURNING *`,
    [
      randomUUID(),
      input.spaceId,
      input.name,
      JSON.stringify(input.aliases ?? []),
      input.piScholarId ?? null,
      input.confidence ?? null,
      new Date(),
    ],
  );
  return result.rows[0]!;
}

export async function addGroupMembership(
  db: Queryable,
  input: {
    spaceId: string;
    groupId: string;
    scholarId: string;
    role?: string | null;
    source?: string | null;
    confidence?: number | null;
  },
) {
  const result = await db.query(
    `INSERT INTO research_atlas_group_memberships (
       id, space_id, group_id, scholar_id, role, source, confidence, created_at, updated_at
     ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
     ON CONFLICT (group_id, scholar_id, role)
     DO UPDATE SET
       source = EXCLUDED.source,
       confidence = COALESCE(EXCLUDED.confidence, research_atlas_group_memberships.confidence),
       updated_at = EXCLUDED.updated_at
     RETURNING *`,
    [
      randomUUID(),
      input.spaceId,
      input.groupId,
      input.scholarId,
      input.role ?? "unknown",
      input.source ?? "manual",
      input.confidence ?? null,
      new Date(),
    ],
  );
  return result.rows[0]!;
}

interface PaperGraphRow {
  id: string;
  title: string;
  publication_year: number | null;
  paper_type: string;
  doi: string | null;
  arxiv_id: string | null;
  cited_by_count: number | null;
  reference_count: number | null;
  updated_at: Date | string | null;
  venue_id?: string | null;
  venue_name?: string | null;
  venue_type?: string | null;
  citation_source?: string | null;
  citation_confidence?: number | null;
}

interface AuthorshipGraphRow {
  id: string;
  scholar_id: string | null;
  raw_author_name: string;
  author_position: number;
  confidence: number | null;
  display_name: string | null;
  orcid: string | null;
  h_index: number | null;
  works_count: number | null;
}

interface LibraryAuthorshipGraphRow extends AuthorshipGraphRow {
  paper_id: string;
}

interface LibraryCitationGraphRow {
  citing_paper_id: string;
  cited_paper_id: string;
  source: string | null;
  confidence: number | null;
}

export async function graphForLibrary(db: Queryable, spaceId: string): Promise<GraphProjection> {
  const generatedAt = new Date().toISOString();
  const nodes = new Map<string, GraphProjectionNode>();
  const edges = new Map<string, GraphProjectionEdge>();
  const totalPapers = await db.query<{ count: string }>(
    `SELECT count(*)::text AS count
       FROM research_atlas_papers
      WHERE space_id = $1
        AND merged_into_id IS NULL`,
    [spaceId],
  );
  const papers = await db.query<PaperGraphRow>(
    `SELECT p.id,
            p.title,
            p.publication_year,
            p.paper_type,
            p.doi,
            p.arxiv_id,
            p.cited_by_count,
            p.reference_count,
            p.updated_at,
            v.id AS venue_id,
            v.name AS venue_name,
            v.venue_type
       FROM research_atlas_papers p
       LEFT JOIN research_atlas_venues v
         ON v.space_id = p.space_id
        AND v.id = p.venue_id
        AND v.merged_into_id IS NULL
      WHERE p.space_id = $1
        AND p.merged_into_id IS NULL
      ORDER BY
        COALESCE(p.cited_by_count, 0) DESC,
        p.updated_at DESC,
        p.title
      LIMIT $2`,
    [spaceId, LIBRARY_PAPER_LIMIT],
  );

  for (const paper of papers.rows) addPaperNode(nodes, paper);

  const paperIds = papers.rows.map((paper) => paper.id);
  let authorEdgesTruncated = false;
  let citationEdgesTruncated = false;
  if (paperIds.length > 0) {
    const authors = await db.query<LibraryAuthorshipGraphRow>(
      `SELECT a.id,
              a.paper_id,
              a.scholar_id,
              a.raw_author_name,
              a.author_position,
              a.confidence,
              s.display_name,
              s.orcid,
              s.h_index,
              s.works_count
         FROM research_atlas_authorships a
         LEFT JOIN research_atlas_scholars s
           ON s.space_id = a.space_id
          AND s.id = a.scholar_id
          AND s.merged_into_id IS NULL
        WHERE a.space_id = $1
          AND a.paper_id = ANY($2::varchar[])
          AND a.scholar_id IS NOT NULL
          AND a.author_position <= 8
        ORDER BY a.paper_id, a.author_position
        LIMIT $3`,
      [spaceId, paperIds, LIBRARY_AUTHOR_EDGE_LIMIT],
    );
    authorEdgesTruncated = authors.rows.length >= LIBRARY_AUTHOR_EDGE_LIMIT;
    for (const author of authors.rows) {
      if (!author.scholar_id) continue;
      nodes.set(`scholar:${author.scholar_id}`, {
        id: `scholar:${author.scholar_id}`,
        kind: "scholar",
        label: author.display_name ?? author.raw_author_name,
        subtitle: author.orcid ?? undefined,
        size: author.author_position <= 3 ? 28 : 22,
        clusterId: "cluster:scholars",
        metadata: {
          scholarId: author.scholar_id,
          rawAuthorName: author.raw_author_name,
          authorPosition: author.author_position,
          confidence: author.confidence,
          hIndex: author.h_index,
          worksCount: author.works_count,
        },
      });
      addEdge(edges, {
        id: `authored_by:${author.paper_id}:${author.scholar_id}`,
        source: `paper:${author.paper_id}`,
        target: `scholar:${author.scholar_id}`,
        kind: "authored_by",
        label: "author",
        weight: author.author_position <= 3 ? 2 : 1,
        metadata: {
          authorshipId: author.id,
          authorPosition: author.author_position,
          confidence: author.confidence,
        },
      });
    }

    for (const paper of papers.rows) {
      if (!paper.venue_id || !paper.venue_name) continue;
      nodes.set(`venue:${paper.venue_id}`, {
        id: `venue:${paper.venue_id}`,
        kind: "venue",
        label: paper.venue_name,
        subtitle: paper.venue_type ?? undefined,
        size: 30,
        clusterId: "cluster:venues",
        metadata: {
          venueId: paper.venue_id,
          venueType: paper.venue_type,
        },
      });
      addEdge(edges, {
        id: `published_in:${paper.id}:${paper.venue_id}`,
        source: `paper:${paper.id}`,
        target: `venue:${paper.venue_id}`,
        kind: "published_in",
        label: "venue",
      });
    }

    const citations = await db.query<LibraryCitationGraphRow>(
      `SELECT citing_paper_id, cited_paper_id, source, confidence
         FROM research_atlas_citation_edges
        WHERE space_id = $1
          AND citing_paper_id = ANY($2::varchar[])
          AND cited_paper_id = ANY($2::varchar[])
        ORDER BY COALESCE(confidence, 0) DESC, updated_at DESC
        LIMIT $3`,
      [spaceId, paperIds, LIBRARY_CITATION_EDGE_LIMIT],
    );
    citationEdgesTruncated = citations.rows.length >= LIBRARY_CITATION_EDGE_LIMIT;
    for (const citation of citations.rows) {
      addEdge(edges, {
        id: `references:${citation.citing_paper_id}:${citation.cited_paper_id}`,
        source: `paper:${citation.citing_paper_id}`,
        target: `paper:${citation.cited_paper_id}`,
        kind: "references",
        label: "references",
        weight: citation.confidence ?? undefined,
        metadata: {
          source: citation.source,
          confidence: citation.confidence,
        },
      });
    }
  }

  const totalPaperCount = Number(totalPapers.rows[0]?.count ?? 0);
  const truncated = totalPaperCount > papers.rows.length ||
    authorEdgesTruncated ||
    citationEdgesTruncated;
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    view: {
      mode: "global",
      limit: LIBRARY_PAPER_LIMIT,
      generatedAt,
      truncated,
      totalNodeCount: totalPaperCount,
    },
    layout: { mode: "clustered" },
  };
}

export async function graphForPaper(db: Queryable, spaceId: string, paperId: string): Promise<GraphProjection> {
  const nodes = new Map<string, GraphProjectionNode>();
  const edges = new Map<string, GraphProjectionEdge>();
  const generatedAt = new Date().toISOString();
  const center = await db.query<PaperGraphRow>(
    `SELECT p.id,
            p.title,
            p.publication_year,
            p.paper_type,
            p.doi,
            p.arxiv_id,
            p.cited_by_count,
            p.reference_count,
            p.updated_at,
            v.id AS venue_id,
            v.name AS venue_name,
            v.venue_type
       FROM research_atlas_papers p
       LEFT JOIN research_atlas_venues v
         ON v.space_id = p.space_id
        AND v.id = p.venue_id
        AND v.merged_into_id IS NULL
      WHERE p.space_id = $1
        AND p.id = $2
        AND p.merged_into_id IS NULL`,
    [spaceId, paperId],
  );

  const root = center.rows[0];
  if (!root) throw new AtlasRequestError(404, "paper not found");

  const related = await listPaperRelated(db, spaceId, paperId);
  addPaperNode(nodes, root, { root: true });
  for (const paper of related.references) {
    addPaperNode(nodes, paper);
    addEdge(edges, {
      id: `references:${paperId}:${paper.id}`,
      source: `paper:${paperId}`,
      target: `paper:${paper.id}`,
      kind: "references",
      label: "references",
      weight: paper.citation_confidence ?? undefined,
      metadata: {
        direction: "reference",
        source: paper.citation_source,
        confidence: paper.citation_confidence,
      },
    });
  }
  for (const paper of related.citations) {
    addPaperNode(nodes, paper);
    addEdge(edges, {
      id: `references:${paper.id}:${paperId}`,
      source: `paper:${paper.id}`,
      target: `paper:${paperId}`,
      kind: "references",
      label: "references",
      weight: paper.citation_confidence ?? undefined,
      metadata: {
        direction: "citation",
        source: paper.citation_source,
        confidence: paper.citation_confidence,
      },
    });
  }

  const authors = await db.query<AuthorshipGraphRow>(
    `SELECT a.id,
            a.scholar_id,
            a.raw_author_name,
            a.author_position,
            a.confidence,
            s.display_name,
            s.orcid,
            s.h_index,
            s.works_count
       FROM research_atlas_authorships a
       LEFT JOIN research_atlas_scholars s
         ON s.space_id = a.space_id
        AND s.id = a.scholar_id
        AND s.merged_into_id IS NULL
      WHERE a.space_id = $1
        AND a.paper_id = $2
      ORDER BY a.author_position
      LIMIT 25`,
    [spaceId, paperId],
  );
  for (const author of authors.rows) {
    if (!author.scholar_id) continue;
    nodes.set(`scholar:${author.scholar_id}`, {
      id: `scholar:${author.scholar_id}`,
      kind: "scholar",
      label: author.display_name ?? author.raw_author_name,
      subtitle: author.orcid ?? undefined,
      size: author.author_position <= 3 ? 30 : 24,
      metadata: {
        scholarId: author.scholar_id,
        rawAuthorName: author.raw_author_name,
        authorPosition: author.author_position,
        confidence: author.confidence,
        hIndex: author.h_index,
        worksCount: author.works_count,
      },
    });
    addEdge(edges, {
      id: `authored_by:${paperId}:${author.scholar_id}`,
      source: `paper:${paperId}`,
      target: `scholar:${author.scholar_id}`,
      kind: "authored_by",
      label: "author",
      weight: author.author_position <= 3 ? 2 : 1,
      metadata: {
        authorshipId: author.id,
        authorPosition: author.author_position,
        confidence: author.confidence,
      },
    });
  }

  if (root.venue_id && root.venue_name) {
    nodes.set(`venue:${root.venue_id}`, {
      id: `venue:${root.venue_id}`,
      kind: "venue",
      label: root.venue_name,
      subtitle: root.venue_type ?? undefined,
      size: 32,
      metadata: {
        venueId: root.venue_id,
        venueType: root.venue_type,
      },
    });
    addEdge(edges, {
      id: `published_in:${paperId}:${root.venue_id}`,
      source: `paper:${paperId}`,
      target: `venue:${root.venue_id}`,
      kind: "published_in",
      label: "venue",
    });
  }

  const allNodes = [...nodes.values()];
  const visibleNodes = allNodes.slice(0, 100);
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = [...edges.values()]
    .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    .slice(0, 150);
  const truncated = allNodes.length > visibleNodes.length || edges.size > visibleEdges.length;

  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    view: {
      mode: "local",
      rootId: `paper:${paperId}`,
      depth: 1,
      limit: 100,
      generatedAt,
      truncated,
      totalNodeCount: allNodes.length,
    },
    layout: { mode: "force" },
  };
}

function addPaperNode(
  nodes: Map<string, GraphProjectionNode>,
  paper: PaperGraphRow,
  options: { root?: boolean } = {},
): void {
  nodes.set(`paper:${paper.id}`, {
    id: `paper:${paper.id}`,
    kind: "paper",
    label: paper.title,
    subtitle: paper.publication_year ? `${paper.publication_year} · ${paper.paper_type}` : paper.paper_type,
    size: options.root ? 44 : 30,
    degree: (paper.cited_by_count ?? 0) + (paper.reference_count ?? 0),
    metadata: {
      paperId: paper.id,
      publicationYear: paper.publication_year,
      paperType: paper.paper_type,
      doi: paper.doi,
      arxivId: paper.arxiv_id,
      citedByCount: paper.cited_by_count,
      referenceCount: paper.reference_count,
      updatedAt: timestampString(paper.updated_at),
      root: options.root === true,
    },
  });
}

function addEdge(edges: Map<string, GraphProjectionEdge>, edge: GraphProjectionEdge): void {
  edges.set(edge.id, edge);
}

function timestampString(value: Date | string | null): string | undefined {
  if (value instanceof Date) return value.toISOString();
  return value ?? undefined;
}

export async function sendEntityExport(
  db: Queryable,
  reply: FastifyReply,
  input: {
    spaceId: string;
    entityType: string;
    since?: string | null;
    cursor?: string | null;
    limit?: number;
    includeMerged?: boolean;
  },
): Promise<void> {
  const table = exportTable(input.entityType);
  const limit = exportLimit(input.limit);
  const cursor = decodeExportCursor(input.cursor);
  const params: unknown[] = [input.spaceId];
  let cursorSql = "";
  if (cursor) {
    params.push(cursor.updated_at, cursor.id);
    cursorSql = `AND (updated_at, id) > ($${params.length - 1}::timestamptz, $${params.length})`;
  } else if (input.since) {
    params.push(input.since);
    cursorSql = `AND updated_at > $${params.length}::timestamptz`;
  }
  const tombstoneSql = input.includeMerged === false ? "AND merged_into_id IS NULL" : "";
  params.push(limit + 1);
  const result = await db.query<ExportEntityRow>(
    `SELECT *
       FROM ${table}
      WHERE space_id = $1
        ${cursorSql}
        ${tombstoneSql}
      ORDER BY updated_at, id
      LIMIT $${params.length}`,
    params,
  );
  const rows = result.rows.slice(0, limit);
  const nextCursor = result.rows.length > limit && rows.length
    ? encodeExportCursor(exportCursorForRow(rows[rows.length - 1]!))
    : null;
  const lines = rows.map((row) => JSON.stringify({
    schema_version: 1,
    entity_type: input.entityType,
    cursor: exportCursorForRow(row),
    tombstone: exportTombstoneForRow(row),
    data: row,
  })).join("\n");
  if (nextCursor) reply.header("x-next-cursor", nextCursor);
  reply.header("content-type", "application/x-ndjson").send(lines ? `${lines}\n` : "");
}

interface ExportEntityRow {
  id: string;
  updated_at: Date | string;
  merged_into_id?: string | null;
  [key: string]: unknown;
}

interface ExportCursor {
  updated_at: string;
  id: string;
}

interface ExportTombstone {
  kind: "merge";
  merged_into_id: string;
}

function exportLimit(value: number | undefined): number {
  if (value === undefined) return 1000;
  return Number.isInteger(value) && value > 0 ? Math.min(value, 1000) : 1000;
}

function exportCursorForRow(row: ExportEntityRow): ExportCursor {
  return {
    updated_at: timestampString(row.updated_at) ?? new Date(0).toISOString(),
    id: row.id,
  };
}

function exportTombstoneForRow(row: ExportEntityRow): ExportTombstone | null {
  return row.merged_into_id
    ? { kind: "merge", merged_into_id: row.merged_into_id }
    : null;
}

function encodeExportCursor(cursor: ExportCursor): string {
  return Buffer.from(JSON.stringify(cursor), "utf8").toString("base64url");
}

function decodeExportCursor(value: string | null | undefined): ExportCursor | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf8")) as Partial<ExportCursor>;
    if (typeof parsed.updated_at !== "string" || typeof parsed.id !== "string") {
      throw new AtlasRequestError(400, "invalid export cursor");
    }
    return { updated_at: parsed.updated_at, id: parsed.id };
  } catch {
    throw new AtlasRequestError(400, "invalid export cursor");
  }
}

async function listCitationNeighbors(
  db: Queryable,
  spaceId: string,
  paperId: string,
  direction: "references" | "citations",
): Promise<{ papers: PaperGraphRow[] }> {
  const joinColumn = direction === "references" ? "citing_paper_id" : "cited_paper_id";
  const targetColumn = direction === "references" ? "cited_paper_id" : "citing_paper_id";
  const result = await db.query<PaperGraphRow>(
    `SELECT p.*, ce.source AS citation_source, ce.confidence AS citation_confidence
       FROM research_atlas_citation_edges ce
       JOIN research_atlas_papers p
         ON p.space_id = ce.space_id
        AND p.id = ce.${targetColumn}
      WHERE ce.space_id = $1
        AND ce.${joinColumn} = $2
        AND p.merged_into_id IS NULL
      ORDER BY p.publication_year DESC NULLS LAST, p.title
      LIMIT 200`,
    [spaceId, paperId],
  );
  return { papers: result.rows };
}

function exportTable(entityType: string): string {
  switch (entityType) {
    case "paper":
    case "papers":
      return "research_atlas_papers";
    case "scholar":
    case "scholars":
      return "research_atlas_scholars";
    case "institution":
    case "institutions":
      return "research_atlas_institutions";
    case "venue":
    case "venues":
      return "research_atlas_venues";
    case "group":
    case "groups":
      return "research_atlas_research_groups";
    case "topic":
    case "topics":
      return "research_atlas_topics";
    default:
      throw new AtlasRequestError(400, "unsupported export entity type");
  }
}
