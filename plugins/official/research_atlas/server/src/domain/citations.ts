import { randomUUID } from "node:crypto";
import type { Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { normalizeArxivId, normalizeDoi, nonEmptyString } from "./identifiers";
import { researchAtlasService } from "./service";

export interface CitationPaperRef {
  title?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  publication_year?: number | null;
}

export interface CitationFillMetadata {
  references?: CitationPaperRef[];
  citations?: CitationPaperRef[];
}

interface SemanticScholarPaper {
  title?: string;
  year?: number;
  externalIds?: {
    DOI?: string;
    ArXiv?: string;
  };
}

interface SemanticScholarResponse {
  references?: SemanticScholarPaper[];
  citations?: SemanticScholarPaper[];
}

interface OpenCitationsRow {
  citing?: string;
  cited?: string;
}

export async function fetchCitationMetadataByConnector(
  connector: string | null,
  doi: string,
): Promise<CitationFillMetadata | null> {
  if (connector === "s2") return fetchSemanticScholarCitationMetadata(doi);
  if (connector === "opencitations") return fetchOpenCitationsMetadata(doi);
  return null;
}

export async function fillCitationEdgesFromMetadata(
  db: Queryable,
  input: {
    spaceId: string;
    userId: string;
    paperId: string;
    connector: string;
    metadata: Record<string, unknown>;
  },
): Promise<{ references: number; citations: number }> {
  const citationMetadata = citationMetadataFromPayload(input.metadata);
  const references = await importLinkedPapers(db, input, citationMetadata.references ?? [], "references");
  const citations = await importLinkedPapers(db, input, citationMetadata.citations ?? [], "citations");
  return { references, citations };
}

async function fetchSemanticScholarCitationMetadata(doi: string): Promise<CitationFillMetadata | null> {
  const url = new URL(
    `https://api.semanticscholar.org/graph/v1/paper/DOI:${encodeURIComponent(normalizeDoi(doi))}`,
  );
  url.searchParams.set(
    "fields",
    "references.title,references.year,references.externalIds,citations.title,citations.year,citations.externalIds",
  );
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Semantic Scholar returned ${response.status}`);
  const payload = await response.json() as SemanticScholarResponse;
  return {
    references: (payload.references ?? []).map(semanticScholarPaperRef).filter(hasCitationIdentifier),
    citations: (payload.citations ?? []).map(semanticScholarPaperRef).filter(hasCitationIdentifier),
  };
}

async function fetchOpenCitationsMetadata(doi: string): Promise<CitationFillMetadata | null> {
  const normalized = encodeURIComponent(normalizeDoi(doi));
  const [references, citations] = await Promise.all([
    fetchOpenCitationsRows(`https://opencitations.net/index/coci/api/v1/references/${normalized}`),
    fetchOpenCitationsRows(`https://opencitations.net/index/coci/api/v1/citations/${normalized}`),
  ]);
  return {
    references: references.map((row) => ({ doi: row.cited ?? null })).filter(hasCitationIdentifier),
    citations: citations.map((row) => ({ doi: row.citing ?? null })).filter(hasCitationIdentifier),
  };
}

async function fetchOpenCitationsRows(url: string): Promise<OpenCitationsRow[]> {
  const response = await fetch(url);
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`OpenCitations returned ${response.status}`);
  const payload = await response.json();
  return Array.isArray(payload) ? payload as OpenCitationsRow[] : [];
}

async function importLinkedPapers(
  db: Queryable,
  input: {
    spaceId: string;
    userId: string;
    paperId: string;
    connector: string;
  },
  papers: CitationPaperRef[],
  direction: "references" | "citations",
): Promise<number> {
  let inserted = 0;
  for (const paper of papers.slice(0, 50)) {
    const linked = await importCitationPaper(db, input, paper);
    if (!linked) continue;
    if (direction === "references") {
      await upsertCitationEdge(db, input.spaceId, input.paperId, linked.paper.id, input.connector);
    } else {
      await upsertCitationEdge(db, input.spaceId, linked.paper.id, input.paperId, input.connector);
    }
    inserted += 1;
  }
  return inserted;
}

async function importCitationPaper(
  db: Queryable,
  input: { spaceId: string; userId: string; connector: string },
  paper: CitationPaperRef,
) {
  const rawDoi = nonEmptyString(paper.doi);
  const rawArxivId = nonEmptyString(paper.arxiv_id);
  const doi = rawDoi ? normalizeDoi(rawDoi) : null;
  const arxivId = rawArxivId ? normalizeArxivId(rawArxivId) : null;
  if (!doi && !arxivId) return null;
  const title = nonEmptyString(paper.title) ?? (doi ? `DOI ${doi}` : `arXiv ${arxivId}`);
  return researchAtlasService.importPaperMetadata(db, {
    spaceId: input.spaceId,
    userId: input.userId,
    connector: input.connector,
    paper: {
      title,
      doi,
      arxiv_id: arxivId,
      publication_year: paper.publication_year ?? null,
      paper_type: "article",
      raw_author_names: [],
      metadata_json: { citation_seed: true },
    },
  });
}

async function upsertCitationEdge(
  db: Queryable,
  spaceId: string,
  citingPaperId: string,
  citedPaperId: string,
  source: string,
): Promise<void> {
  if (citingPaperId === citedPaperId) return;
  await db.query(
    `INSERT INTO research_atlas_citation_edges (
       id, space_id, citing_paper_id, cited_paper_id, source, confidence, created_at, updated_at
     ) VALUES ($1, $2, $3, $4, $5, 0.8, $6, $6)
     ON CONFLICT (citing_paper_id, cited_paper_id)
     DO UPDATE SET
       source = EXCLUDED.source,
       confidence = GREATEST(
         COALESCE(research_atlas_citation_edges.confidence, 0),
         COALESCE(EXCLUDED.confidence, 0)
       ),
       updated_at = EXCLUDED.updated_at`,
    [randomUUID(), spaceId, citingPaperId, citedPaperId, source, new Date()],
  );
}

function citationMetadataFromPayload(payload: Record<string, unknown>): CitationFillMetadata {
  return {
    references: citationPaperRefs(payload.references ?? payload.referenced_papers),
    citations: citationPaperRefs(payload.citations ?? payload.citing_papers),
  };
}

function citationPaperRefs(value: unknown): CitationPaperRef[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return { doi: item };
    if (!item || typeof item !== "object") return {};
    const record = item as Record<string, unknown>;
    return {
      title: nonEmptyString(record.title),
      doi: nonEmptyString(record.doi) ?? nonEmptyString(record.DOI),
      arxiv_id: nonEmptyString(record.arxiv_id) ?? nonEmptyString(record.arxivId),
      publication_year: yearValue(record.publication_year ?? record.year),
    };
  }).filter(hasCitationIdentifier);
}

function semanticScholarPaperRef(paper: SemanticScholarPaper): CitationPaperRef {
  return {
    title: nonEmptyString(paper.title),
    doi: nonEmptyString(paper.externalIds?.DOI),
    arxiv_id: nonEmptyString(paper.externalIds?.ArXiv),
    publication_year: yearValue(paper.year),
  };
}

function hasCitationIdentifier(paper: CitationPaperRef): boolean {
  return Boolean(nonEmptyString(paper.doi) || nonEmptyString(paper.arxiv_id));
}

function yearValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1000 && parsed <= 3000 ? parsed : null;
}
