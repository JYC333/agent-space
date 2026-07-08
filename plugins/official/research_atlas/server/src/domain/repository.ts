import { randomUUID, createHash } from "node:crypto";
import type { Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type {
  AtlasEntityType,
  AuthorshipRow,
  ExternalIdRow,
  PaperListFilters,
  PaperMetadataInput,
  PaperRow,
  ScholarRow,
  SourceRecordRow,
  VenueRow,
} from "./types";
import type { ExternalIdType } from "./identifiers";

type PatchValue = string | number | boolean | null | string[] | Record<string, unknown>;

function now(): Date {
  return new Date();
}

function hashJson(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function jsonObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function mergeMetadata(current: unknown, next: unknown): Record<string, unknown> {
  return { ...jsonObject(current), ...jsonObject(next) };
}

function rowCount(result: { rowCount: number | null; rows: unknown[] }): number {
  return result.rowCount ?? result.rows.length;
}

export const researchAtlasRepository = {
  async findExternalId(
    db: Queryable,
    spaceId: string,
    idType: ExternalIdType,
    idValue: string,
  ): Promise<ExternalIdRow | null> {
    const result = await db.query<ExternalIdRow>(
      `SELECT *
         FROM research_atlas_external_ids
        WHERE space_id = $1
          AND id_type = $2
          AND id_value = $3
        LIMIT 1`,
      [spaceId, idType, idValue],
    );
    return result.rows[0] ?? null;
  },

  async insertPaper(
    db: Queryable,
    input: {
      spaceId: string;
      title: string;
      paperType?: string;
      doi?: string | null;
      arxivId?: string | null;
      rawAuthorNames?: string[];
      metadata?: Record<string, unknown>;
    },
  ): Promise<PaperRow> {
    const id = randomUUID();
    const result = await db.query<PaperRow>(
      `INSERT INTO research_atlas_papers (
         id, space_id, title, paper_type, doi, arxiv_id, raw_author_names, metadata_json, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $9)
       RETURNING *`,
      [
        id,
        input.spaceId,
        input.title,
        input.paperType ?? "other",
        input.doi ?? null,
        input.arxivId ?? null,
        JSON.stringify(input.rawAuthorNames ?? []),
        JSON.stringify(input.metadata ?? {}),
        now(),
      ],
    );
    return result.rows[0]!;
  },

  async findPaper(db: Queryable, spaceId: string, paperId: string): Promise<PaperRow | null> {
    const result = await db.query<PaperRow>(
      `SELECT *
         FROM research_atlas_papers
        WHERE space_id = $1
          AND id = $2
        LIMIT 1`,
      [spaceId, paperId],
    );
    return result.rows[0] ?? null;
  },

  async findCanonicalPaper(db: Queryable, spaceId: string, paperId: string): Promise<PaperRow | null> {
    const paper = await this.findPaper(db, spaceId, paperId);
    if (!paper) return null;
    if (!paper.merged_into_id) return paper;
    return this.findPaper(db, spaceId, paper.merged_into_id);
  },

  async listPapers(db: Queryable, spaceId: string, filters: PaperListFilters): Promise<PaperRow[]> {
    const clauses = ["p.space_id = $1", "p.merged_into_id IS NULL"];
    const params: unknown[] = [spaceId];
    if (filters.q) {
      params.push(`%${filters.q.toLowerCase()}%`);
      clauses.push(`(lower(p.title) LIKE $${params.length} OR lower(coalesce(p.abstract, '')) LIKE $${params.length})`);
    }
    if (filters.year) {
      params.push(filters.year);
      clauses.push(`p.publication_year = $${params.length}`);
    }
    if (filters.venueId) {
      params.push(filters.venueId);
      clauses.push(`p.venue_id = $${params.length}`);
    }
    if (filters.scholarId) {
      params.push(filters.scholarId);
      clauses.push(`EXISTS (
        SELECT 1 FROM research_atlas_authorships a
         WHERE a.paper_id = p.id AND a.scholar_id = $${params.length}
      )`);
    }
    params.push(filters.limit, filters.offset);
    const result = await db.query<PaperRow>(
      `SELECT p.*
         FROM research_atlas_papers p
        WHERE ${clauses.join(" AND ")}
        ORDER BY p.publication_year DESC NULLS LAST, p.updated_at DESC, p.id
        LIMIT $${params.length - 1} OFFSET $${params.length}`,
      params,
    );
    return result.rows;
  },

  async listPaperAuthorships(db: Queryable, spaceId: string, paperId: string): Promise<AuthorshipRow[]> {
    const result = await db.query<AuthorshipRow>(
      `SELECT *
         FROM research_atlas_authorships
        WHERE space_id = $1
          AND paper_id = $2
        ORDER BY author_position`,
      [spaceId, paperId],
    );
    return result.rows;
  },

  async listEntityExternalIds(
    db: Queryable,
    spaceId: string,
    entityType: AtlasEntityType,
    entityId: string,
  ): Promise<ExternalIdRow[]> {
    const result = await db.query<ExternalIdRow>(
      `SELECT *
         FROM research_atlas_external_ids
        WHERE space_id = $1
          AND entity_type = $2
          AND entity_id = $3
        ORDER BY is_primary DESC, id_type, id_value`,
      [spaceId, entityType, entityId],
    );
    return result.rows;
  },

  async listEntitySourceRecords(
    db: Queryable,
    spaceId: string,
    entityType: AtlasEntityType,
    entityId: string,
  ): Promise<SourceRecordRow[]> {
    const result = await db.query<SourceRecordRow>(
      `SELECT sr.*
         FROM research_atlas_source_records sr
         JOIN research_atlas_entity_sources es
           ON es.source_record_id = sr.id
        WHERE es.space_id = $1
          AND es.entity_type = $2
          AND es.entity_id = $3
        ORDER BY sr.fetched_at DESC`,
      [spaceId, entityType, entityId],
    );
    return result.rows;
  },

  async upsertExternalId(
    db: Queryable,
    input: {
      spaceId: string;
      entityType: AtlasEntityType;
      entityId: string;
      idType: ExternalIdType;
      idValue: string;
      isPrimary?: boolean;
      confidence?: number | null;
      sourceRecordId?: string | null;
    },
  ): Promise<ExternalIdRow> {
    const result = await db.query<ExternalIdRow>(
      `INSERT INTO research_atlas_external_ids (
         id, space_id, entity_type, entity_id, id_type, id_value, is_primary,
         confidence, source_record_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
       ON CONFLICT (space_id, id_type, id_value)
       DO UPDATE SET
         entity_type = EXCLUDED.entity_type,
         entity_id = EXCLUDED.entity_id,
         is_primary = research_atlas_external_ids.is_primary OR EXCLUDED.is_primary,
         confidence = COALESCE(EXCLUDED.confidence, research_atlas_external_ids.confidence),
         source_record_id = COALESCE(EXCLUDED.source_record_id, research_atlas_external_ids.source_record_id),
         updated_at = EXCLUDED.updated_at
       RETURNING *`,
      [
        randomUUID(),
        input.spaceId,
        input.entityType,
        input.entityId,
        input.idType,
        input.idValue,
        input.isPrimary ?? false,
        input.confidence ?? null,
        input.sourceRecordId ?? null,
        now(),
      ],
    );
    return result.rows[0]!;
  },

  async upsertSourceRecord(
    db: Queryable,
    input: {
      spaceId: string;
      connector: string;
      externalId: string;
      entityType: AtlasEntityType;
      payload: Record<string, unknown>;
      fetchStatus?: string;
      sourceItemId?: string | null;
      refreshAfter?: Date | null;
    },
  ): Promise<SourceRecordRow> {
    const contentHash = hashJson(input.payload);
    const fetchedAt = now();
    const result = await db.query<SourceRecordRow>(
      `INSERT INTO research_atlas_source_records (
         id, space_id, connector, external_id, entity_type, payload_json, content_hash,
         fetched_at, fetch_status, source_item_id, refresh_after, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $8, $8)
       ON CONFLICT (space_id, connector, external_id, entity_type)
       DO UPDATE SET
         payload_json = EXCLUDED.payload_json,
         content_hash = EXCLUDED.content_hash,
         fetched_at = EXCLUDED.fetched_at,
         fetch_status = EXCLUDED.fetch_status,
         source_item_id = COALESCE(EXCLUDED.source_item_id, research_atlas_source_records.source_item_id),
         refresh_after = EXCLUDED.refresh_after,
         updated_at = EXCLUDED.updated_at
       RETURNING *`,
      [
        randomUUID(),
        input.spaceId,
        input.connector,
        input.externalId,
        input.entityType,
        JSON.stringify(input.payload),
        contentHash,
        fetchedAt,
        input.fetchStatus ?? "ok",
        input.sourceItemId ?? null,
        input.refreshAfter ?? null,
      ],
    );
    return result.rows[0]!;
  },

  async linkEntitySource(
    db: Queryable,
    input: {
      spaceId: string;
      entityType: AtlasEntityType;
      entityId: string;
      sourceRecordId: string;
      role: "created" | "enriched" | "confirmed";
      confidence?: number | null;
    },
  ): Promise<void> {
    await db.query(
      `INSERT INTO research_atlas_entity_sources (
         id, space_id, entity_type, entity_id, source_record_id, role, confidence, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
       ON CONFLICT (entity_type, entity_id, source_record_id)
       DO UPDATE SET
         role = EXCLUDED.role,
         confidence = COALESCE(EXCLUDED.confidence, research_atlas_entity_sources.confidence),
         updated_at = EXCLUDED.updated_at`,
      [
        randomUUID(),
        input.spaceId,
        input.entityType,
        input.entityId,
        input.sourceRecordId,
        input.role,
        input.confidence ?? null,
        now(),
      ],
    );
  },

  async lockedFields(
    db: Queryable,
    spaceId: string,
    entityType: AtlasEntityType,
    entityId: string,
  ): Promise<Set<string>> {
    const result = await db.query<{ field: string }>(
      `SELECT field
         FROM research_atlas_curation_events
        WHERE space_id = $1
          AND entity_type = $2
          AND entity_id = $3
          AND locked
          AND field IS NOT NULL`,
      [spaceId, entityType, entityId],
    );
    return new Set(result.rows.map((row) => row.field));
  },

  async patchPaper(
    db: Queryable,
    paper: PaperRow,
    patch: Record<string, PatchValue>,
    actorUserId: string,
    options: { lock: boolean; actorType: "user" | "connector" | "agent"; reason?: string | null },
  ): Promise<PaperRow> {
    const entries = Object.entries(patch).filter(([, value]) => value !== undefined);
    if (entries.length === 0) return paper;

    const assignments: string[] = [];
    const params: unknown[] = [paper.space_id, paper.id];
    for (const [field, value] of entries) {
      params.push(Array.isArray(value) || (value && typeof value === "object")
        ? JSON.stringify(value)
        : value);
      const cast = Array.isArray(value) || (value && typeof value === "object") ? "::jsonb" : "";
      assignments.push(`${field} = $${params.length}${cast}`);
    }
    params.push(now());
    const result = await db.query<PaperRow>(
      `UPDATE research_atlas_papers
          SET ${assignments.join(", ")}, updated_at = $${params.length}
        WHERE space_id = $1
          AND id = $2
        RETURNING *`,
      params,
    );
    const updated = result.rows[0]!;

    for (const [field, value] of entries) {
      await this.insertCurationEvent(db, {
        spaceId: paper.space_id,
        entityType: "paper",
        entityId: paper.id,
        eventType: "field_correction",
        field,
        oldValue: (paper as unknown as Record<string, unknown>)[field] ?? null,
        newValue: value,
        locked: options.lock,
        actorType: options.actorType,
        actorUserId,
        reason: options.reason ?? null,
      });
    }
    return updated;
  },

  async insertCurationEvent(
    db: Queryable,
    input: {
      spaceId: string;
      entityType: AtlasEntityType;
      entityId: string;
      eventType: string;
      field?: string | null;
      oldValue?: unknown;
      newValue?: unknown;
      locked?: boolean;
      actorType: "user" | "agent" | "connector";
      actorUserId?: string | null;
      proposalId?: string | null;
      reason?: string | null;
    },
  ): Promise<void> {
    await db.query(
      `INSERT INTO research_atlas_curation_events (
         id, space_id, entity_type, entity_id, event_type, field, old_value, new_value,
         locked, actor_type, actor_user_id, proposal_id, reason, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13, $14, $14)`,
      [
        randomUUID(),
        input.spaceId,
        input.entityType,
        input.entityId,
        input.eventType,
        input.field ?? null,
        JSON.stringify(input.oldValue ?? null),
        JSON.stringify(input.newValue ?? null),
        input.locked ?? false,
        input.actorType,
        input.actorUserId ?? null,
        input.proposalId ?? null,
        input.reason ?? null,
        now(),
      ],
    );
  },

  async applyPaperMetadata(
    db: Queryable,
    paper: PaperRow,
    metadata: PaperMetadataInput,
    sourceRecordId: string | null,
  ): Promise<PaperRow> {
    const locked = await this.lockedFields(db, paper.space_id, "paper", paper.id);
    const patch: Record<string, PatchValue> = {};
    const maybeSet = (field: string, value: PatchValue | undefined) => {
      if (value !== undefined && !locked.has(field)) patch[field] = value;
    };

    maybeSet("title", metadata.title);
    maybeSet("abstract", metadata.abstract);
    maybeSet("publication_date", metadata.publication_date);
    maybeSet("publication_year", metadata.publication_year);
    maybeSet("paper_type", metadata.paper_type);
    maybeSet("doi", metadata.doi);
    maybeSet("arxiv_id", metadata.arxiv_id);
    maybeSet("oa_status", metadata.oa_status);
    maybeSet("best_oa_url", metadata.best_oa_url);
    maybeSet("cited_by_count", metadata.cited_by_count);
    maybeSet("reference_count", metadata.reference_count);
    maybeSet("raw_author_names", metadata.raw_author_names);
    maybeSet("metadata_json", mergeMetadata(paper.metadata_json, metadata.metadata_json));

    let updated = await this.patchPaper(db, paper, patch, "", {
      lock: false,
      actorType: "connector",
      reason: "connector_refresh",
    });

    if (metadata.venue_name && !locked.has("venue_id")) {
      const venue = await this.upsertVenue(db, {
        spaceId: paper.space_id,
        name: metadata.venue_name,
        venueType: metadata.venue_type ?? "other",
      });
      updated = await this.patchPaper(db, updated, { venue_id: venue.id }, "", {
        lock: false,
        actorType: "connector",
        reason: "connector_refresh",
      });
    }

    if (metadata.doi) {
      await this.upsertExternalId(db, {
        spaceId: paper.space_id,
        entityType: "paper",
        entityId: paper.id,
        idType: "doi",
        idValue: metadata.doi,
        isPrimary: true,
        confidence: 1,
        sourceRecordId,
      });
    }
    if (metadata.arxiv_id) {
      await this.upsertExternalId(db, {
        spaceId: paper.space_id,
        entityType: "paper",
        entityId: paper.id,
        idType: "arxiv",
        idValue: metadata.arxiv_id,
        isPrimary: true,
        confidence: 1,
        sourceRecordId,
      });
    }

    if (metadata.authors) {
      await this.replaceAuthorships(db, paper.space_id, paper.id, metadata.authors, sourceRecordId);
    }
    return updated;
  },

  async upsertVenue(
    db: Queryable,
    input: { spaceId: string; name: string; venueType?: string | null; issns?: string[] },
  ): Promise<VenueRow> {
    const existing = await db.query<VenueRow>(
      `SELECT *
         FROM research_atlas_venues
        WHERE space_id = $1
          AND lower(name) = lower($2)
          AND merged_into_id IS NULL
        LIMIT 1`,
      [input.spaceId, input.name],
    );
    if (existing.rows[0]) return existing.rows[0];
    const result = await db.query<VenueRow>(
      `INSERT INTO research_atlas_venues (
         id, space_id, name, venue_type, issns, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $6)
       RETURNING *`,
      [
        randomUUID(),
        input.spaceId,
        input.name,
        input.venueType ?? "other",
        JSON.stringify(input.issns ?? []),
        now(),
      ],
    );
    return result.rows[0]!;
  },

  async upsertScholar(
    db: Queryable,
    input: { spaceId: string; displayName: string; orcid?: string | null },
  ): Promise<ScholarRow> {
    if (input.orcid) {
      const byOrcid = await db.query<ScholarRow>(
        `SELECT *
           FROM research_atlas_scholars
          WHERE space_id = $1
            AND orcid = $2
            AND merged_into_id IS NULL
          LIMIT 1`,
        [input.spaceId, input.orcid],
      );
      if (byOrcid.rows[0]) return byOrcid.rows[0];
    }
    const byName = await db.query<ScholarRow>(
      `SELECT *
         FROM research_atlas_scholars
        WHERE space_id = $1
          AND lower(display_name) = lower($2)
          AND merged_into_id IS NULL
        LIMIT 1`,
      [input.spaceId, input.displayName],
    );
    if (byName.rows[0]) return byName.rows[0];

    const result = await db.query<ScholarRow>(
      `INSERT INTO research_atlas_scholars (
         id, space_id, display_name, orcid, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $5)
       RETURNING *`,
      [randomUUID(), input.spaceId, input.displayName, input.orcid ?? null, now()],
    );
    return result.rows[0]!;
  },

  async replaceAuthorships(
    db: Queryable,
    spaceId: string,
    paperId: string,
    authors: Array<{ name: string; orcid?: string | null; affiliation?: string | null }>,
    sourceRecordId: string | null,
  ): Promise<void> {
    await db.query("DELETE FROM research_atlas_authorships WHERE space_id = $1 AND paper_id = $2", [
      spaceId,
      paperId,
    ]);
    let position = 1;
    for (const author of authors) {
      const scholar = await this.upsertScholar(db, {
        spaceId,
        displayName: author.name,
        orcid: author.orcid ?? null,
      });
      if (author.orcid) {
        await this.upsertExternalId(db, {
          spaceId,
          entityType: "scholar",
          entityId: scholar.id,
          idType: "orcid",
          idValue: author.orcid,
          isPrimary: true,
          confidence: 1,
          sourceRecordId,
        });
      }
      await db.query(
        `INSERT INTO research_atlas_authorships (
           id, space_id, paper_id, scholar_id, author_position, raw_author_name,
           raw_affiliation_text, confidence, source, created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)`,
        [
          randomUUID(),
          spaceId,
          paperId,
          scholar.id,
          position,
          author.name,
          author.affiliation ?? null,
          author.orcid ? 0.95 : 0.7,
          "connector",
          now(),
        ],
      );
      position += 1;
    }
  },

  async search(db: Queryable, spaceId: string, q: string, limit: number): Promise<Array<Record<string, unknown>>> {
    const needle = `%${q.toLowerCase()}%`;
    const result = await db.query<Record<string, unknown>>(
      `(SELECT 'paper' AS entity_type, id, title AS label, publication_year::text AS detail
          FROM research_atlas_papers
         WHERE space_id = $1 AND merged_into_id IS NULL AND lower(title) LIKE $2
         ORDER BY updated_at DESC
         LIMIT $3)
       UNION ALL
       (SELECT 'scholar' AS entity_type, id, display_name AS label, orcid AS detail
          FROM research_atlas_scholars
         WHERE space_id = $1 AND merged_into_id IS NULL AND lower(display_name) LIKE $2
         ORDER BY updated_at DESC
         LIMIT $3)
       UNION ALL
       (SELECT 'institution' AS entity_type, id, name AS label, country_code AS detail
          FROM research_atlas_institutions
         WHERE space_id = $1 AND merged_into_id IS NULL AND lower(name) LIKE $2
         ORDER BY updated_at DESC
         LIMIT $3)
       UNION ALL
       (SELECT 'venue' AS entity_type, id, name AS label, venue_type AS detail
          FROM research_atlas_venues
         WHERE space_id = $1 AND merged_into_id IS NULL AND lower(name) LIKE $2
         ORDER BY updated_at DESC
         LIMIT $3)
       LIMIT $3`,
      [spaceId, needle, limit],
    );
    return result.rows;
  },

  async findScholar(db: Queryable, spaceId: string, scholarId: string): Promise<ScholarRow | null> {
    const result = await db.query<ScholarRow>(
      `SELECT *
         FROM research_atlas_scholars
        WHERE space_id = $1
          AND id = $2
        LIMIT 1`,
      [spaceId, scholarId],
    );
    return result.rows[0] ?? null;
  },

  async listScholarPapers(db: Queryable, spaceId: string, scholarId: string): Promise<PaperRow[]> {
    const result = await db.query<PaperRow>(
      `SELECT p.*
         FROM research_atlas_papers p
         JOIN research_atlas_authorships a ON a.paper_id = p.id
        WHERE p.space_id = $1
          AND a.scholar_id = $2
          AND p.merged_into_id IS NULL
        ORDER BY p.publication_year DESC NULLS LAST, p.updated_at DESC`,
      [spaceId, scholarId],
    );
    return result.rows;
  },

  async mergeEntity(
    db: Queryable,
    input: {
      spaceId: string;
      entityType: AtlasEntityType;
      winnerId: string;
      loserId: string;
      actorUserId: string;
      reason?: string | null;
    },
  ): Promise<void> {
    const table = tableForEntity(input.entityType);
    const winner = await db.query(`SELECT id FROM ${table} WHERE space_id = $1 AND id = $2`, [
      input.spaceId,
      input.winnerId,
    ]);
    const loser = await db.query(`SELECT id FROM ${table} WHERE space_id = $1 AND id = $2`, [
      input.spaceId,
      input.loserId,
    ]);
    if (rowCount(winner) === 0 || rowCount(loser) === 0) {
      throw new Error("entity not found");
    }
    if (input.entityType === "scholar") {
      await db.query(
        `UPDATE research_atlas_authorships
            SET scholar_id = $3, updated_at = $4
          WHERE space_id = $1
            AND scholar_id = $2`,
        [input.spaceId, input.loserId, input.winnerId, now()],
      );
    }
    if (input.entityType === "institution") {
      await db.query(
        `UPDATE research_atlas_authorships
            SET institution_id = $3, updated_at = $4
          WHERE space_id = $1
            AND institution_id = $2`,
        [input.spaceId, input.loserId, input.winnerId, now()],
      );
    }
    await db.query(
      `UPDATE research_atlas_external_ids
          SET entity_id = $4, updated_at = $5
        WHERE space_id = $1
          AND entity_type = $2
          AND entity_id = $3`,
      [input.spaceId, input.entityType, input.loserId, input.winnerId, now()],
    );
    await db.query(
      `UPDATE ${table}
          SET merged_into_id = $3, updated_at = $4
        WHERE space_id = $1
          AND id = $2`,
      [input.spaceId, input.loserId, input.winnerId, now()],
    );
    await this.insertCurationEvent(db, {
      spaceId: input.spaceId,
      entityType: input.entityType,
      entityId: input.winnerId,
      eventType: "merge",
      oldValue: { loser_id: input.loserId },
      newValue: { winner_id: input.winnerId },
      actorType: "user",
      actorUserId: input.actorUserId,
      reason: input.reason ?? null,
    });
  },
};

function tableForEntity(entityType: AtlasEntityType): string {
  switch (entityType) {
    case "paper":
      return "research_atlas_papers";
    case "scholar":
      return "research_atlas_scholars";
    case "institution":
      return "research_atlas_institutions";
    case "venue":
      return "research_atlas_venues";
    default:
      throw new Error(`merge is not supported for ${entityType}`);
  }
}
