import type { Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { fetchCrossrefWork } from "./crossref";
import {
  normalizeArxivId,
  normalizeDoi,
  normalizeExternalId,
  nonEmptyString,
  type ExternalIdType,
} from "./identifiers";
import { researchAtlasRepository } from "./repository";
import type { AtlasEntityType, ImportFilePaperInput, PaperMetadataInput, PaperRow } from "./types";

export class AtlasRequestError extends Error {
  constructor(readonly statusCode: number, message: string) {
    super(message);
  }
}

interface ImportPaperResult {
  paper: PaperRow;
  status: "created" | "matched";
  job_id: string | null;
}

const PATCHABLE_PAPER_FIELDS = new Set([
  "title",
  "abstract",
  "publication_date",
  "publication_year",
  "paper_type",
  "language",
  "doi",
  "arxiv_id",
  "oa_status",
  "best_oa_url",
  "cited_by_count",
  "reference_count",
  "raw_author_names",
  "metadata_json",
]);

export const researchAtlasService = {
  async importPaper(
    db: Queryable,
    input: {
      spaceId: string;
      userId: string;
      body: Record<string, unknown>;
      enqueue?: (paperId: string, connector: string) => Promise<{ jobId: string }>;
    },
  ): Promise<ImportPaperResult> {
    const doi = nonEmptyString(input.body.doi);
    const arxivId = nonEmptyString(input.body.arxiv_id);
    if (!doi && !arxivId) {
      throw new AtlasRequestError(400, "doi or arxiv_id is required");
    }
    const idType: ExternalIdType = doi ? "doi" : "arxiv";
    const idValue = idType === "doi" ? normalizeDoi(doi!) : normalizeArxivId(arxivId!);
    if (!idValue) throw new AtlasRequestError(400, `${idType} is invalid`);

    const existing = await researchAtlasRepository.findExternalId(db, input.spaceId, idType, idValue);
    if (existing && existing.entity_type === "paper") {
      const paper = await researchAtlasRepository.findCanonicalPaper(db, input.spaceId, existing.entity_id);
      if (!paper) throw new AtlasRequestError(404, "paper not found");
      return { paper, status: "matched", job_id: null };
    }

    const paper = await researchAtlasRepository.insertPaper(db, {
      spaceId: input.spaceId,
      title: idType === "doi" ? `DOI ${idValue}` : `arXiv ${idValue}`,
      paperType: idType === "arxiv" ? "preprint" : "article",
      doi: idType === "doi" ? idValue : null,
      arxivId: idType === "arxiv" ? idValue : null,
      metadata: { imported_by_user_id: input.userId },
    });
    await researchAtlasRepository.upsertExternalId(db, {
      spaceId: input.spaceId,
      entityType: "paper",
      entityId: paper.id,
      idType,
      idValue,
      isPrimary: true,
      confidence: 1,
    });

    let jobId: string | null = null;
    if (input.enqueue) {
      const connector = idType === "doi" ? "crossref" : "arxiv";
      const queued = await input.enqueue(paper.id, connector);
      jobId = queued.jobId;
    }
    return { paper, status: "created", job_id: jobId };
  },

  async listPapers(db: Queryable, spaceId: string, query: Record<string, unknown>) {
    const limit = clampNumber(query.limit, 1, 100, 50);
    const offset = Math.max(0, Number(query.cursor ?? 0) || 0);
    const papers = await researchAtlasRepository.listPapers(db, spaceId, {
      q: nonEmptyString(query.q),
      year: query.year ? Number(query.year) : null,
      venueId: nonEmptyString(query.venue_id),
      scholarId: nonEmptyString(query.scholar_id),
      limit,
      offset,
    });
    return {
      papers,
      next_cursor: papers.length === limit ? String(offset + limit) : null,
    };
  },

  async getPaperDetail(db: Queryable, spaceId: string, paperId: string) {
    const paper = await researchAtlasRepository.findCanonicalPaper(db, spaceId, paperId);
    if (!paper) throw new AtlasRequestError(404, "paper not found");
    const [authorships, externalIds, provenance] = await Promise.all([
      researchAtlasRepository.listPaperAuthorships(db, spaceId, paper.id),
      researchAtlasRepository.listEntityExternalIds(db, spaceId, "paper", paper.id),
      researchAtlasRepository.listEntitySourceRecords(db, spaceId, "paper", paper.id),
    ]);
    return { paper, authorships, external_ids: externalIds, provenance };
  },

  async patchPaper(
    db: Queryable,
    input: {
      spaceId: string;
      userId: string;
      paperId: string;
      body: Record<string, unknown>;
    },
  ) {
    const paper = await researchAtlasRepository.findCanonicalPaper(db, input.spaceId, input.paperId);
    if (!paper) throw new AtlasRequestError(404, "paper not found");
    const patch: Record<string, string | number | boolean | null | string[] | Record<string, unknown>> = {};
    for (const [field, value] of Object.entries(input.body)) {
      if (!PATCHABLE_PAPER_FIELDS.has(field)) continue;
      patch[field] = normalizePatchValue(field, value);
    }
    if (Object.keys(patch).length === 0) {
      throw new AtlasRequestError(400, "no supported paper fields provided");
    }
    if (typeof patch.doi === "string") patch.doi = normalizeDoi(patch.doi);
    if (typeof patch.arxiv_id === "string") patch.arxiv_id = normalizeArxivId(patch.arxiv_id);
    const updated = await researchAtlasRepository.patchPaper(db, paper, patch, input.userId, {
      lock: true,
      actorType: "user",
      reason: nonEmptyString(input.body.reason),
    });
    if (typeof patch.doi === "string") {
      await researchAtlasRepository.upsertExternalId(db, {
        spaceId: input.spaceId,
        entityType: "paper",
        entityId: paper.id,
        idType: "doi",
        idValue: patch.doi,
        isPrimary: true,
        confidence: 1,
      });
    }
    if (typeof patch.arxiv_id === "string") {
      await researchAtlasRepository.upsertExternalId(db, {
        spaceId: input.spaceId,
        entityType: "paper",
        entityId: paper.id,
        idType: "arxiv",
        idValue: patch.arxiv_id,
        isPrimary: true,
        confidence: 1,
      });
    }
    return { paper: updated };
  },

  async search(db: Queryable, spaceId: string, query: Record<string, unknown>) {
    const q = nonEmptyString(query.q);
    if (!q) return { results: [] };
    const limit = clampNumber(query.limit, 1, 50, 20);
    return { results: await researchAtlasRepository.search(db, spaceId, q, limit) };
  },

  async getScholar(db: Queryable, spaceId: string, scholarId: string) {
    const scholar = await researchAtlasRepository.findScholar(db, spaceId, scholarId);
    if (!scholar) throw new AtlasRequestError(404, "scholar not found");
    const papers = await researchAtlasRepository.listScholarPapers(db, spaceId, scholarId);
    const externalIds = await researchAtlasRepository.listEntityExternalIds(db, spaceId, "scholar", scholarId);
    return { scholar, papers, external_ids: externalIds };
  },

  async mergeEntity(
    db: Queryable,
    input: {
      spaceId: string;
      userId: string;
      entityType: AtlasEntityType;
      winnerId: string;
      loserId: string;
      reason?: string | null;
    },
  ) {
    if (input.winnerId === input.loserId) {
      throw new AtlasRequestError(400, "winner and loser must be different");
    }
    await researchAtlasRepository.mergeEntity(db, {
      spaceId: input.spaceId,
      entityType: input.entityType,
      winnerId: input.winnerId,
      loserId: input.loserId,
      actorUserId: input.userId,
      reason: input.reason ?? null,
    });
    return { merged: true, winner_id: input.winnerId, loser_id: input.loserId };
  },

  async refreshPaperFromConnector(
    db: Queryable,
    input: {
      spaceId: string;
      paperId: string;
      connector?: string | null;
      metadata?: PaperMetadataInput | null;
      connectorEmail?: string | null;
      sourceItemId?: string | null;
    },
  ) {
    const paper = await researchAtlasRepository.findCanonicalPaper(db, input.spaceId, input.paperId);
    if (!paper) throw new AtlasRequestError(404, "paper not found");
    const connector = input.connector ?? (paper.doi ? "crossref" : "manual");
    let metadata = input.metadata ?? null;
    if (!metadata && connector === "crossref" && paper.doi) {
      metadata = await fetchCrossrefWork(paper.doi, input.connectorEmail);
    }
    if (!metadata) return { paper, refreshed: false };
    const externalId = connector === "crossref" && paper.doi
      ? paper.doi
      : paper.id;
    const sourceRecord = await researchAtlasRepository.upsertSourceRecord(db, {
      spaceId: input.spaceId,
      connector,
      externalId,
      entityType: "paper",
      payload: metadata as Record<string, unknown>,
      sourceItemId: input.sourceItemId ?? null,
      refreshAfter: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
    });
    await researchAtlasRepository.linkEntitySource(db, {
      spaceId: input.spaceId,
      entityType: "paper",
      entityId: paper.id,
      sourceRecordId: sourceRecord.id,
      role: "enriched",
      confidence: connector === "crossref" ? 0.95 : 0.7,
    });
    const updated = await researchAtlasRepository.applyPaperMetadata(db, paper, metadata, sourceRecord.id);
    return { paper: updated, refreshed: true };
  },

  async importPaperMetadata(
    db: Queryable,
    input: {
      spaceId: string;
      userId: string;
      paper: ImportFilePaperInput;
      connector: string;
      sourceItemId?: string | null;
      enqueue?: (paperId: string, connector: string) => Promise<{ jobId: string }>;
    },
  ) {
    const doi = input.paper.doi ? normalizeDoi(input.paper.doi) : null;
    const arxivId = input.paper.arxiv_id ? normalizeArxivId(input.paper.arxiv_id) : null;
    const imported = await this.importPaper(db, {
      spaceId: input.spaceId,
      userId: input.userId,
      body: doi ? { doi } : { arxiv_id: arxivId },
      enqueue: input.enqueue,
    });
    const refreshed = await this.refreshPaperFromConnector(db, {
      spaceId: input.spaceId,
      paperId: imported.paper.id,
      connector: input.connector,
      metadata: {
        ...input.paper,
        doi,
        arxiv_id: arxivId,
      },
      sourceItemId: input.sourceItemId ?? null,
    });
    return {
      paper: refreshed.paper,
      status: imported.status,
      job_id: imported.job_id,
    };
  },
};

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function normalizePatchValue(field: string, value: unknown): string | number | boolean | null | string[] | Record<string, unknown> {
  if (value === null) return null;
  if (field === "publication_year" || field === "cited_by_count" || field === "reference_count") {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) throw new AtlasRequestError(400, `${field} must be a number`);
    return Math.trunc(parsed);
  }
  if (field === "raw_author_names") {
    if (!Array.isArray(value)) throw new AtlasRequestError(400, "raw_author_names must be an array");
    return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
  }
  if (field === "metadata_json") {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new AtlasRequestError(400, "metadata_json must be an object");
    }
    return value as Record<string, unknown>;
  }
  const text = nonEmptyString(value);
  if (!text) throw new AtlasRequestError(400, `${field} must be a non-empty string or null`);
  if (field === "doi") return normalizeExternalId("doi", text);
  if (field === "arxiv_id") return normalizeExternalId("arxiv", text);
  return text;
}
