import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import { RelationsRepository } from "../src/modules/relations/repository";
import { RelationsService } from "../src/modules/relations/service";

// Real-Postgres coverage for Relation Core: the space_objects composite-FK
// extension pattern, the CHECK-constrained enums, the relation_affiliations ->
// object_relations materialization, and space isolation across all relation
// entities. A FakeDb unit test cannot catch constraint/FK-shape bugs here.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OTHER_SPACE = "22222222-2222-4222-8222-222222222222";
const USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (err) {
    console.warn(`[relations-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    "TRUNCATE relation_source_links, relation_notes, relation_affiliations, relation_identities, relation_organizations, relation_people, object_relations, space_objects, users, spaces CASCADE",
  );
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at)
     VALUES ($1, 'User', 'active', now(), now())`,
    [USER],
  );
  for (const spaceId of [SPACE, OTHER_SPACE]) {
    await pool.query(
      `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
       VALUES ($1, 'Relations Space', 'household', $2, now(), now())`,
      [spaceId, USER],
    );
    await pool.query(
      `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
       VALUES (gen_random_uuid()::varchar, $1, $2, 'owner', 'active', now(), now())`,
      [spaceId, USER],
    );
  }
});

function service(): RelationsService {
  return new RelationsService(pool as Pool, new RelationsRepository(pool as Pool));
}

describe("relations module (real Postgres)", () => {
  it("creates and reads a relation person", async () => {
    if (!available) return;
    const person = await service().createPerson(
      { spaceId: SPACE, userId: USER },
      { title: "Ada Lovelace", summary: "Mathematician", pronouns: "she/her", headline: "Analytical Engine pioneer" },
    );
    expect(person.title).toBe("Ada Lovelace");
    expect(person.pronouns).toBe("she/her");
    expect(person.headline).toBe("Analytical Engine pioneer");

    const fetched = await service().getPerson({ spaceId: SPACE, userId: USER }, person.object_id);
    expect(fetched.object_id).toBe(person.object_id);
  });

  it("updates a person's fields, including clearing summary with an explicit null", async () => {
    if (!available) return;
    const person = await service().createPerson(
      { spaceId: SPACE, userId: USER },
      { title: "Hedy Lamarr", summary: "Actress and inventor", pronouns: "she/her" },
    );
    const renamed = await service().updatePerson({ spaceId: SPACE, userId: USER }, person.object_id, {
      title: "Hedy Lamarr (updated)",
      summary: null,
    });
    expect(renamed.title).toBe("Hedy Lamarr (updated)");
    expect(renamed.summary).toBeNull();
    expect(renamed.pronouns).toBe("she/her");

    await expect(
      service().updatePerson({ spaceId: SPACE, userId: USER }, "does-not-exist", { title: "Nope" }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("paginates listPeople honoring the requested limit and offset", async () => {
    if (!available) return;
    for (const name of ["Person A", "Person B", "Person C", "Person D"]) {
      await service().createPerson({ spaceId: SPACE, userId: USER }, { title: name });
    }
    const firstPage = await service().listPeople({ spaceId: SPACE, userId: USER }, { q: null, limit: 2, offset: 0 });
    expect(firstPage.items).toHaveLength(2);
    expect(firstPage.total).toBe(4);
    expect(firstPage.items.map((p) => p.title)).toEqual(["Person A", "Person B"]);

    const secondPage = await service().listPeople({ spaceId: SPACE, userId: USER }, { q: null, limit: 2, offset: 2 });
    expect(secondPage.items.map((p) => p.title)).toEqual(["Person C", "Person D"]);
  });

  it("rejects reading a person from another space", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Alan Turing" });
    await expect(service().getPerson({ spaceId: OTHER_SPACE, userId: USER }, person.object_id)).rejects.toMatchObject({
      statusCode: 404,
    });
  });

  it("creates an organization with org_type and parent linkage", async () => {
    if (!available) return;
    const university = await service().createOrganization({ spaceId: SPACE, userId: USER }, {
      title: "Stanford University",
      org_type: "university",
      homepage_url: "https://stanford.edu",
    });
    expect(university.org_type).toBe("university");

    const lab = await service().createOrganization({ spaceId: SPACE, userId: USER }, {
      title: "AI Lab",
      org_type: "lab",
      parent_organization_object_id: university.object_id,
    });
    expect(lab.parent_organization_object_id).toBe(university.object_id);
  });

  it("rejects an invalid org_type", async () => {
    if (!available) return;
    await expect(
      service().createOrganization({ spaceId: SPACE, userId: USER }, { title: "Bad Org", org_type: "not_a_type" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("creates identities and enforces the unique (space, object, type, value) index", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Grace Hopper" });
    const identity = await service().createIdentity({ spaceId: SPACE, userId: USER }, person.object_id, {
      id_type: "email",
      id_value: "grace@example.com",
      is_primary: true,
    });
    expect(identity.id_type).toBe("email");

    await expect(pool!.query(
      `INSERT INTO relation_identities (id, space_id, object_id, id_type, id_value, is_primary, source, created_at, updated_at)
       VALUES (gen_random_uuid(), $1, $2, 'email', 'grace@example.com', false, 'manual', now(), now())`,
      [SPACE, person.object_id],
    )).rejects.toThrow();

    const identities = await service().listIdentities({ spaceId: SPACE, userId: USER }, person.object_id);
    expect(identities).toHaveLength(1);
  });

  it("creates an affiliation and materializes an object_relations edge, then ends it", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Barbara Liskov" });
    const org = await service().createOrganization({ spaceId: SPACE, userId: USER }, { title: "MIT", org_type: "university" });

    const affiliation = await service().createAffiliation({ spaceId: SPACE, userId: USER }, {
      person_object_id: person.object_id,
      organization_object_id: org.object_id,
      role: "professor",
      title: "Professor of Computer Science",
    });
    expect(affiliation.status).toBe("active");

    const edgeResult = await pool!.query(
      `SELECT relation_type, status FROM object_relations WHERE from_object_id = $1 AND to_object_id = $2`,
      [person.object_id, org.object_id],
    );
    expect(edgeResult.rows).toHaveLength(1);
    expect(edgeResult.rows[0].relation_type).toBe("affiliated_with");
    expect(edgeResult.rows[0].status).toBe("active");

    const ended = await service().endAffiliation({ spaceId: SPACE, userId: USER }, affiliation.id, "2020-01-01T00:00:00.000Z");
    expect(ended.status).toBe("past");

    const edgeAfterEnd = await pool!.query(`SELECT status FROM object_relations WHERE from_object_id = $1 AND to_object_id = $2`, [
      person.object_id,
      org.object_id,
    ]);
    expect(edgeAfterEnd.rows[0].status).toBe("archived");
  });

  it("rejects an affiliation referencing a person from another space", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: OTHER_SPACE, userId: USER }, { title: "Cross Space Person" });
    const org = await service().createOrganization({ spaceId: SPACE, userId: USER }, { title: "Local Org", org_type: "company" });
    await expect(
      service().createAffiliation({ spaceId: SPACE, userId: USER }, {
        person_object_id: person.object_id,
        organization_object_id: org.object_id,
      }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("creates and lists relation notes", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Katherine Johnson" });
    await service().createNote({ spaceId: SPACE, userId: USER }, person.object_id, { body: "Met at a conference in 2024." });
    const notes = await service().listNotes({ spaceId: SPACE, userId: USER }, person.object_id);
    expect(notes).toHaveLength(1);
    expect(notes[0]!.body).toBe("Met at a conference in 2024.");
  });

  it("creates and lists relation source links", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Margaret Hamilton" });
    await service().createSourceLink({ spaceId: SPACE, userId: USER }, person.object_id, {
      link_type: "external",
      external_ref: "https://example.com/bio",
    });
    const links = await service().listSourceLinks({ spaceId: SPACE, userId: USER }, person.object_id);
    expect(links).toHaveLength(1);
    expect(links[0]!.link_type).toBe("external");
  });

  it("rejects an invalid source link type", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Invalid Link Target" });
    await expect(
      service().createSourceLink({ spaceId: SPACE, userId: USER }, person.object_id, { link_type: "not_a_type" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("searches people and organizations by title within a space", async () => {
    if (!available) return;
    await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "Radia Perlman" });
    await service().createOrganization({ spaceId: SPACE, userId: USER }, { title: "Perlman Labs", org_type: "lab" });
    await service().createPerson({ spaceId: OTHER_SPACE, userId: USER }, { title: "Perlman Impostor" });

    const results = await service().search({ spaceId: SPACE, userId: USER }, "Perlman", 20);
    expect(results.map((r) => r.title).sort()).toEqual(["Perlman Labs", "Radia Perlman"]);
  });

  it("archives a person via soft delete", async () => {
    if (!available) return;
    const person = await service().createPerson({ spaceId: SPACE, userId: USER }, { title: "To Be Archived" });
    await service().archivePerson({ spaceId: SPACE, userId: USER }, person.object_id);
    const result = await pool!.query(`SELECT status FROM space_objects WHERE id = $1`, [person.object_id]);
    expect(result.rows[0].status).toBe("archived");
  });
});
