import { randomUUID } from "node:crypto";
import type { PoolClient } from "../../db/pool";
import { countFromRow, HttpError, type Queryable } from "../routeUtils/common";
import { contentOwnerFilterSql, contentReadSql } from "../access/contentAccessSql";
import { contentOwnerFromDb } from "../access/contentAccessQuery";

export interface RelationPersonRow {
  object_id: string;
  space_id: string;
  title: string;
  summary: string | null;
  status: string;
  pronouns: string | null;
  headline: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface RelationOrganizationRow {
  object_id: string;
  space_id: string;
  title: string;
  summary: string | null;
  status: string;
  org_type: string;
  homepage_url: string | null;
  parent_organization_object_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface RelationIdentityRow {
  id: string;
  space_id: string;
  object_id: string;
  id_type: string;
  id_value: string;
  is_primary: boolean;
  confidence: number | null;
  source: string;
  created_at: unknown;
  updated_at: unknown;
}

export interface RelationAffiliationRow {
  id: string;
  space_id: string;
  person_object_id: string;
  organization_object_id: string;
  role: string | null;
  title: string | null;
  status: string;
  start_date: unknown;
  end_date: unknown;
  confidence: number | null;
  source: string;
  object_relation_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface RelationNoteRow {
  id: string;
  space_id: string;
  object_id: string;
  body: string;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface RelationSourceLinkRow {
  id: string;
  space_id: string;
  object_id: string;
  link_type: string;
  activity_id: string | null;
  source_item_id: string | null;
  evidence_id: string | null;
  external_ref: string | null;
  note: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_at: unknown;
}

const PERSON_COLUMNS = `
  so.id AS object_id, so.space_id, so.title, so.summary, so.status,
  rp.pronouns, rp.headline, rp.created_at, rp.updated_at
`;

const ORGANIZATION_COLUMNS = `
  so.id AS object_id, so.space_id, so.title, so.summary, so.status,
  ro.org_type, ro.homepage_url, ro.parent_organization_object_id,
  ro.created_at, ro.updated_at
`;

const IDENTITY_COLUMNS = `
  id, space_id, object_id, id_type, id_value, is_primary, confidence, source, created_at, updated_at
`;

const AFFILIATION_COLUMNS = `
  id, space_id, person_object_id, organization_object_id, role, title, status,
  start_date, end_date, confidence, source, object_relation_id, created_at, updated_at
`;
const AFFILIATION_COLUMNS_ALIASED = `
  ra.id, ra.space_id, ra.person_object_id, ra.organization_object_id, ra.role, ra.title, ra.status,
  ra.start_date, ra.end_date, ra.confidence, ra.source, ra.object_relation_id, ra.created_at, ra.updated_at
`;

const NOTE_COLUMNS = `
  id, space_id, object_id, body, created_by_user_id, created_by_agent_id, created_at, updated_at
`;

const SOURCE_LINK_COLUMNS = `
  id, space_id, object_id, link_type, activity_id, source_item_id, evidence_id,
  external_ref, note, created_by_user_id, created_by_agent_id, created_at
`;

export class RelationsRepository {
  constructor(private readonly db: Queryable) {}

  async createPerson(
    client: PoolClient,
    input: {
      spaceId: string;
      title: string;
      summary: string | null;
      pronouns: string | null;
      headline: string | null;
      createdByUserId: string | null;
    },
  ): Promise<RelationPersonRow> {
    const objectId = randomUUID();
    const now = new Date().toISOString();
    await client.query(
      `INSERT INTO space_objects (
         id, space_id, object_type, title, summary, status, visibility, access_level,
         owner_user_id, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, 'person', $3, $4, 'active', 'space_shared', 'full', $5, $5, $6, $6)`,
      [objectId, input.spaceId, input.title, input.summary, input.createdByUserId, now],
    );
    await client.query(
      `INSERT INTO relation_people (object_id, space_id, pronouns, headline, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $5)`,
      [objectId, input.spaceId, input.pronouns, input.headline, now],
    );
    const created = await this.getPerson(client, input.spaceId, objectId, input.createdByUserId ?? "");
    if (!created) throw new HttpError(500, "Failed to create relation person");
    return created;
  }

  async getPerson(db: Queryable, spaceId: string, objectId: string, userId: string): Promise<RelationPersonRow | null> {
    const result = await db.query<RelationPersonRow>(
      `SELECT ${PERSON_COLUMNS}
         FROM space_objects so
         JOIN relation_people rp ON rp.object_id = so.id AND rp.space_id = so.space_id
        WHERE so.id = $1 AND so.space_id = $2 AND so.status <> 'deleted'
          AND ${contentReadSql("space_object", "so", "$3")}
        LIMIT 1`,
      [objectId, spaceId, userId],
    );
    return result.rows[0] ?? null;
  }

  async listPeople(
    spaceId: string,
    userId: string,
    filters: { q: string | null; limit: number; offset: number },
  ): Promise<{ rows: RelationPersonRow[]; total: number }> {
    const params: unknown[] = [spaceId, userId];
    const clauses = ["so.space_id = $1", "so.status <> 'deleted'", contentReadSql("space_object", "so", "$2")];
    if (filters.q) {
      params.push(`%${filters.q}%`);
      clauses.push(`so.title ILIKE $${params.length}`);
    }
    const where = clauses.join(" AND ");
    const limitParamIndex = params.length + 1;
    const offsetParamIndex = params.length + 2;
    const [rows, total] = await Promise.all([
      this.db.query<RelationPersonRow>(
        `SELECT ${PERSON_COLUMNS}
           FROM space_objects so
           JOIN relation_people rp ON rp.object_id = so.id AND rp.space_id = so.space_id
          WHERE ${where}
          ORDER BY so.title ASC
          LIMIT $${limitParamIndex} OFFSET $${offsetParamIndex}`,
        [...params, filters.limit, filters.offset],
      ),
      this.db.query<{ total: string }>(
        `SELECT COUNT(*)::text AS total
           FROM space_objects so
           JOIN relation_people rp ON rp.object_id = so.id AND rp.space_id = so.space_id
          WHERE ${where}`,
        params,
      ),
    ]);
    return { rows: rows.rows, total: countFromRow(total.rows[0]) };
  }

  async updatePerson(
    spaceId: string,
    objectId: string,
    userId: string,
    patch: {
      title?: string;
      summary?: string | null;
      pronouns?: string | null;
      headline?: string | null;
    },
  ): Promise<RelationPersonRow | null> {
    const now = new Date().toISOString();
    if (patch.title !== undefined || patch.summary !== undefined) {
      await this.db.query(
        `UPDATE space_objects
            SET title = COALESCE($3, title), summary = CASE WHEN $4 THEN $5 ELSE summary END, updated_at = $6
          WHERE id = $1 AND space_id = $2`,
        [objectId, spaceId, patch.title ?? null, patch.summary !== undefined, patch.summary ?? null, now],
      );
    }
    if (patch.pronouns !== undefined || patch.headline !== undefined) {
      await this.db.query(
        `UPDATE relation_people
            SET pronouns = CASE WHEN $3 THEN $4 ELSE pronouns END,
                headline = CASE WHEN $5 THEN $6 ELSE headline END,
                updated_at = $7
          WHERE object_id = $1 AND space_id = $2`,
        [
          objectId,
          spaceId,
          patch.pronouns !== undefined,
          patch.pronouns ?? null,
          patch.headline !== undefined,
          patch.headline ?? null,
          now,
        ],
      );
    }
    return this.getPerson(this.db, spaceId, objectId, userId);
  }

  async archivePerson(spaceId: string, objectId: string): Promise<void> {
    await this.db.query(
      `UPDATE space_objects SET status = 'archived', archived_at = $3, updated_at = $3 WHERE id = $1 AND space_id = $2`,
      [objectId, spaceId, new Date().toISOString()],
    );
  }

  async createOrganization(
    client: PoolClient,
    input: {
      spaceId: string;
      title: string;
      summary: string | null;
      orgType: string;
      homepageUrl: string | null;
      parentOrganizationObjectId: string | null;
      createdByUserId: string | null;
    },
  ): Promise<RelationOrganizationRow> {
    const objectId = randomUUID();
    const now = new Date().toISOString();
    await client.query(
      `INSERT INTO space_objects (
         id, space_id, object_type, title, summary, status, visibility, access_level,
         owner_user_id, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, 'organization', $3, $4, 'active', 'space_shared', 'full', $5, $5, $6, $6)`,
      [objectId, input.spaceId, input.title, input.summary, input.createdByUserId, now],
    );
    await client.query(
      `INSERT INTO relation_organizations (
         object_id, space_id, org_type, homepage_url, parent_organization_object_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $6)`,
      [objectId, input.spaceId, input.orgType, input.homepageUrl, input.parentOrganizationObjectId, now],
    );
    const created = await this.getOrganization(client, input.spaceId, objectId, input.createdByUserId ?? "");
    if (!created) throw new HttpError(500, "Failed to create relation organization");
    return created;
  }

  async getOrganization(db: Queryable, spaceId: string, objectId: string, userId: string): Promise<RelationOrganizationRow | null> {
    const result = await db.query<RelationOrganizationRow>(
      `SELECT ${ORGANIZATION_COLUMNS}
         FROM space_objects so
         JOIN relation_organizations ro ON ro.object_id = so.id AND ro.space_id = so.space_id
        WHERE so.id = $1 AND so.space_id = $2 AND so.status <> 'deleted'
          AND ${contentReadSql("space_object", "so", "$3")}
        LIMIT 1`,
      [objectId, spaceId, userId],
    );
    return result.rows[0] ?? null;
  }

  async listOrganizations(
    spaceId: string,
    userId: string,
    filters: { q: string | null; limit: number; offset: number },
  ): Promise<{ rows: RelationOrganizationRow[]; total: number }> {
    const params: unknown[] = [spaceId, userId];
    const clauses = ["so.space_id = $1", "so.status <> 'deleted'", contentReadSql("space_object", "so", "$2")];
    if (filters.q) {
      params.push(`%${filters.q}%`);
      clauses.push(`so.title ILIKE $${params.length}`);
    }
    const where = clauses.join(" AND ");
    const limitParamIndex = params.length + 1;
    const offsetParamIndex = params.length + 2;
    const [rows, total] = await Promise.all([
      this.db.query<RelationOrganizationRow>(
        `SELECT ${ORGANIZATION_COLUMNS}
           FROM space_objects so
           JOIN relation_organizations ro ON ro.object_id = so.id AND ro.space_id = so.space_id
          WHERE ${where}
          ORDER BY so.title ASC
          LIMIT $${limitParamIndex} OFFSET $${offsetParamIndex}`,
        [...params, filters.limit, filters.offset],
      ),
      this.db.query<{ total: string }>(
        `SELECT COUNT(*)::text AS total
           FROM space_objects so
           JOIN relation_organizations ro ON ro.object_id = so.id AND ro.space_id = so.space_id
          WHERE ${where}`,
        params,
      ),
    ]);
    return { rows: rows.rows, total: countFromRow(total.rows[0]) };
  }

  async createIdentity(
    spaceId: string,
    input: {
      objectId: string;
      idType: string;
      idValue: string;
      isPrimary: boolean;
      confidence: number | null;
      source: string;
      createdByUserId: string | null;
    },
  ): Promise<RelationIdentityRow> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<RelationIdentityRow>(
      `INSERT INTO relation_identities (
         id, space_id, object_id, id_type, id_value, is_primary, confidence, source,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
       RETURNING ${IDENTITY_COLUMNS}`,
      [
        id,
        spaceId,
        input.objectId,
        input.idType,
        input.idValue,
        input.isPrimary,
        input.confidence,
        input.source,
        input.createdByUserId,
        now,
      ],
    );
    return result.rows[0]!;
  }

  async listIdentities(spaceId: string, objectId: string): Promise<RelationIdentityRow[]> {
    const result = await this.db.query<RelationIdentityRow>(
      `SELECT ${IDENTITY_COLUMNS}
         FROM relation_identities
        WHERE space_id = $1 AND object_id = $2
        ORDER BY is_primary DESC, created_at ASC`,
      [spaceId, objectId],
    );
    return result.rows;
  }

  async createAffiliation(
    client: PoolClient,
    input: {
      spaceId: string;
      personObjectId: string;
      organizationObjectId: string;
      role: string | null;
      title: string | null;
      startDate: string | null;
      endDate: string | null;
      confidence: number | null;
      source: string;
      createdByUserId: string | null;
    },
  ): Promise<RelationAffiliationRow> {
    const id = randomUUID();
    const relationId = randomUUID();
    const now = new Date().toISOString();
    await client.query(
      `INSERT INTO object_relations (
         id, space_id, from_object_id, to_object_id, relation_type, status,
         confidence, metadata_json, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'affiliated_with', 'active', $5, '{}'::jsonb, $6, $7, $7)`,
      [relationId, input.spaceId, input.personObjectId, input.organizationObjectId, input.confidence, input.createdByUserId, now],
    );
    const result = await client.query<RelationAffiliationRow>(
      `INSERT INTO relation_affiliations (
         id, space_id, person_object_id, organization_object_id, role, title, status,
         start_date, end_date, confidence, source, object_relation_id,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, $8, $9, $10, $11, $12, $13, $13)
       RETURNING ${AFFILIATION_COLUMNS}`,
      [
        id,
        input.spaceId,
        input.personObjectId,
        input.organizationObjectId,
        input.role,
        input.title,
        input.startDate,
        input.endDate,
        input.confidence,
        input.source,
        relationId,
        input.createdByUserId,
        now,
      ],
    );
    return result.rows[0]!;
  }

  async listAffiliations(
    spaceId: string,
    userId: string,
    filters: { personObjectId: string | null; organizationObjectId: string | null },
  ): Promise<RelationAffiliationRow[]> {
    const params: unknown[] = [spaceId, userId];
    const clauses = [
      "ra.space_id = $1",
      contentReadSql("space_object", "person_so", "$2"),
      contentReadSql("space_object", "organization_so", "$2"),
    ];
    if (filters.personObjectId) {
      params.push(filters.personObjectId);
      clauses.push(`ra.person_object_id = $${params.length}`);
    }
    if (filters.organizationObjectId) {
      params.push(filters.organizationObjectId);
      clauses.push(`ra.organization_object_id = $${params.length}`);
    }
    const result = await this.db.query<RelationAffiliationRow>(
      `SELECT ${AFFILIATION_COLUMNS_ALIASED}
         FROM relation_affiliations ra
         JOIN space_objects person_so
           ON person_so.id = ra.person_object_id AND person_so.space_id = ra.space_id
         JOIN space_objects organization_so
           ON organization_so.id = ra.organization_object_id AND organization_so.space_id = ra.space_id
        WHERE ${clauses.join(" AND ")}
        ORDER BY ra.start_date DESC NULLS LAST, ra.created_at DESC`,
      params,
    );
    return result.rows;
  }

  async endAffiliation(client: PoolClient, spaceId: string, affiliationId: string, endDate: string | null): Promise<RelationAffiliationRow | null> {
    const now = new Date().toISOString();
    const result = await client.query<RelationAffiliationRow>(
      `UPDATE relation_affiliations
          SET status = 'past', end_date = COALESCE($3, end_date, $4), updated_at = $4
        WHERE id = $1 AND space_id = $2
        RETURNING ${AFFILIATION_COLUMNS}`,
      [affiliationId, spaceId, endDate, now],
    );
    const affiliation = result.rows[0] ?? null;
    if (affiliation?.object_relation_id) {
      await client.query(`UPDATE object_relations SET status = 'archived', updated_at = $2 WHERE id = $1`, [
        affiliation.object_relation_id,
        now,
      ]);
    }
    return affiliation;
  }

  async affiliationPersonObjectId(spaceId: string, affiliationId: string): Promise<string | null> {
    const result = await this.db.query<{ person_object_id: string }>(
      `SELECT person_object_id
         FROM relation_affiliations
        WHERE id = $1 AND space_id = $2
        LIMIT 1`,
      [affiliationId, spaceId],
    );
    return result.rows[0]?.person_object_id ?? null;
  }

  async createNote(input: {
    spaceId: string;
    objectId: string;
    body: string;
    createdByUserId: string | null;
    createdByAgentId: string | null;
  }): Promise<RelationNoteRow> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<RelationNoteRow>(
      `INSERT INTO relation_notes (
         id, space_id, object_id, body, created_by_user_id, created_by_agent_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
       RETURNING ${NOTE_COLUMNS}`,
      [id, input.spaceId, input.objectId, input.body, input.createdByUserId, input.createdByAgentId, now],
    );
    return result.rows[0]!;
  }

  async listNotes(spaceId: string, objectId: string): Promise<RelationNoteRow[]> {
    const result = await this.db.query<RelationNoteRow>(
      `SELECT ${NOTE_COLUMNS}
         FROM relation_notes
        WHERE space_id = $1 AND object_id = $2
        ORDER BY created_at DESC`,
      [spaceId, objectId],
    );
    return result.rows;
  }

  async createSourceLink(input: {
    spaceId: string;
    objectId: string;
    linkType: string;
    activityId: string | null;
    sourceItemId: string | null;
    evidenceId: string | null;
    externalRef: string | null;
    note: string | null;
    createdByUserId: string | null;
    createdByAgentId: string | null;
  }): Promise<RelationSourceLinkRow> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<RelationSourceLinkRow>(
      `INSERT INTO relation_source_links (
         id, space_id, object_id, link_type, activity_id, source_item_id, evidence_id,
         external_ref, note, created_by_user_id, created_by_agent_id, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
       RETURNING ${SOURCE_LINK_COLUMNS}`,
      [
        id,
        input.spaceId,
        input.objectId,
        input.linkType,
        input.activityId,
        input.sourceItemId,
        input.evidenceId,
        input.externalRef,
        input.note,
        input.createdByUserId,
        input.createdByAgentId,
        now,
      ],
    );
    return result.rows[0]!;
  }

  async activityExistsInSpace(spaceId: string, activityId: string, userId: string): Promise<boolean> {
    const result = await this.db.query(
      `SELECT 1
         FROM activity_records ar
        WHERE ar.id = $1 AND ar.space_id = $2
          AND ${contentReadSql("activity", "ar", "$3")}
        LIMIT 1`,
      [activityId, spaceId, userId],
    );
    return result.rows.length > 0;
  }

  async sourceItemExistsInSpace(spaceId: string, sourceItemId: string): Promise<boolean> {
    const result = await this.db.query(
      `SELECT 1
         FROM source_items
        WHERE id = $1 AND space_id = $2 AND deleted_at IS NULL
        LIMIT 1`,
      [sourceItemId, spaceId],
    );
    return result.rows.length > 0;
  }

  async evidenceExistsInSpace(spaceId: string, evidenceId: string): Promise<boolean> {
    const result = await this.db.query(
      `SELECT 1
         FROM extracted_evidence
        WHERE id = $1 AND space_id = $2 AND deleted_at IS NULL
        LIMIT 1`,
      [evidenceId, spaceId],
    );
    return result.rows.length > 0;
  }

  async listSourceLinks(spaceId: string, objectId: string): Promise<RelationSourceLinkRow[]> {
    const result = await this.db.query<RelationSourceLinkRow>(
      `SELECT ${SOURCE_LINK_COLUMNS}
         FROM relation_source_links
        WHERE space_id = $1 AND object_id = $2
        ORDER BY created_at DESC`,
      [spaceId, objectId],
    );
    return result.rows;
  }

  async existsRelationObject(spaceId: string, objectId: string, userId: string): Promise<boolean> {
    const result = await this.db.query(
      `SELECT 1
         FROM space_objects so
        WHERE so.id = $1 AND so.space_id = $2 AND so.object_type IN ('person', 'organization') AND so.status <> 'deleted'
          AND ${contentReadSql("space_object", "so", "$3")}
        LIMIT 1`,
      [objectId, spaceId, userId],
    );
    return result.rows.length > 0;
  }

  async isOwnedRelationObject(spaceId: string, objectId: string, userId: string): Promise<boolean> {
    return contentOwnerFromDb(
      this.db,
      { spaceId, userId },
      "space_object",
      objectId,
    );
  }

  async deleteIdentity(spaceId: string, identityId: string, userId: string): Promise<boolean> {
    const result = await this.db.query(
      `DELETE FROM relation_identities ri
        USING space_objects so
        WHERE ri.id = $1 AND ri.space_id = $2
          AND so.id = ri.object_id AND so.space_id = ri.space_id
          AND ${contentReadSql("space_object", "so", "$3")}
          AND ${contentOwnerFilterSql("space_object", "so", "$3")}
        RETURNING ri.id`,
      [identityId, spaceId, userId],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async search(spaceId: string, userId: string, q: string, limit: number): Promise<Array<{ object_id: string; object_type: string; title: string }>> {
    const result = await this.db.query<{ object_id: string; object_type: string; title: string }>(
      `SELECT so.id AS object_id, so.object_type, so.title
         FROM space_objects so
        WHERE so.space_id = $1
          AND so.object_type IN ('person', 'organization')
          AND so.status <> 'deleted'
          AND ${contentReadSql("space_object", "so", "$2")}
          AND so.title ILIKE $3
        ORDER BY so.title ASC
        LIMIT $4`,
      [spaceId, userId, `%${q}%`, limit],
    );
    return result.rows;
  }
}
