import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import { AcademicRepository } from "../src/modules/academic/repository";
import { AcademicService } from "../src/modules/academic/service";
import { RelationsRepository } from "../src/modules/relations/repository";
import { RelationsService } from "../src/modules/relations/service";

// Real-Postgres coverage for the Academic Research preset's object extensions:
// papers built on the existing `sources` extension (not a new space_objects
// object_type), authored_by/cites object_relations edges, and space isolation.

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
    console.warn(`[academic-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    "TRUNCATE academic_papers, sources, relation_people, object_relations, space_objects, users, spaces CASCADE",
  );
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at)
     VALUES ($1, 'User', 'active', now(), now())`,
    [USER],
  );
  for (const spaceId of [SPACE, OTHER_SPACE]) {
    await pool.query(
      `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
       VALUES ($1, 'Academic Space', 'household', $2, now(), now())`,
      [spaceId, USER],
    );
    await pool.query(
      `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
       VALUES (gen_random_uuid()::varchar, $1, $2, 'owner', 'active', now(), now())`,
      [spaceId, USER],
    );
  }
});

function service(): AcademicService {
  return new AcademicService(pool as Pool, new AcademicRepository(pool as Pool));
}

function relationsService(): RelationsService {
  return new RelationsService(pool as Pool, new RelationsRepository(pool as Pool));
}

const identity = { spaceId: SPACE, userId: USER };

describe("academic module (real Postgres)", () => {
  it("creates a paper backed by the sources extension (not a new object_type)", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, {
      title: "Attention Is All You Need",
      summary: "Introduces the Transformer architecture.",
      arxiv_id: "1706.03762",
      paper_type: "preprint",
    });
    expect(paper.title).toBe("Attention Is All You Need");
    expect(paper.arxiv_id).toBe("1706.03762");
    expect(paper.paper_type).toBe("preprint");

    const objectTypeResult = await pool!.query(`SELECT object_type FROM space_objects WHERE id = $1`, [paper.object_id]);
    expect(objectTypeResult.rows[0].object_type).toBe("source");
    const sourceTypeResult = await pool!.query(`SELECT source_type FROM sources WHERE object_id = $1`, [paper.object_id]);
    expect(sourceTypeResult.rows[0].source_type).toBe("paper");
  });

  it("rejects creating a duplicate paper by arxiv_id in the same space", async () => {
    if (!available) return;
    await service().createPaper(identity, { title: "Paper One", arxiv_id: "1111.11111" });
    await expect(service().createPaper(identity, { title: "Paper One Duplicate", arxiv_id: "1111.11111" })).rejects.toMatchObject({
      statusCode: 409,
    });
  });

  it("allows the same arxiv_id in different spaces", async () => {
    if (!available) return;
    await service().createPaper(identity, { title: "Paper One", arxiv_id: "2222.22222" });
    await expect(
      service().createPaper({ spaceId: OTHER_SPACE, userId: USER }, { title: "Paper One Elsewhere", arxiv_id: "2222.22222" }),
    ).resolves.toMatchObject({ arxiv_id: "2222.22222" });
  });

  it("rejects an invalid paper_type", async () => {
    if (!available) return;
    await expect(service().createPaper(identity, { title: "Bad Paper", paper_type: "not_a_type" })).rejects.toMatchObject({
      statusCode: 422,
    });
  });

  it("links an author to a paper via an authored_by object_relations edge", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, { title: "Deep Learning Survey" });
    const person = await relationsService().createPerson(identity, { title: "Yann LeCun" });

    await service().linkAuthor(identity, paper.object_id, { person_object_id: person.object_id, author_position: 1 });
    const authors = await service().listAuthors(identity, paper.object_id);
    expect(authors).toHaveLength(1);
    expect(authors[0]!.person_object_id).toBe(person.object_id);
    expect(authors[0]!.author_position).toBe(1);

    const edgeResult = await pool!.query(
      `SELECT relation_type FROM object_relations WHERE from_object_id = $1 AND to_object_id = $2`,
      [paper.object_id, person.object_id],
    );
    expect(edgeResult.rows[0].relation_type).toBe("authored_by");
  });

  it("reuses an existing active author edge when the same author is linked again", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, { title: "Author Idempotency" });
    const person = await relationsService().createPerson(identity, { title: "First Author" });

    const first = await service().linkAuthor(identity, paper.object_id, { person_object_id: person.object_id, author_position: 2 });
    const second = await service().linkAuthor(identity, paper.object_id, { person_object_id: person.object_id, author_position: 1 });

    expect(second.object_relation_id).toBe(first.object_relation_id);
    const authors = await service().listAuthors(identity, paper.object_id);
    expect(authors).toHaveLength(1);
    expect(authors[0]!.author_position).toBe(1);
  });

  it("rejects linking a non-existent person as an author", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, { title: "Some Paper" });
    await expect(
      service().linkAuthor(identity, paper.object_id, { person_object_id: "does-not-exist" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("links a citation edge and lists it from both directions", async () => {
    if (!available) return;
    const citing = await service().createPaper(identity, { title: "Citing Paper" });
    const cited = await service().createPaper(identity, { title: "Cited Paper" });

    await service().linkCitation(identity, citing.object_id, { cited_paper_object_id: cited.object_id });

    const outgoing = await service().listCitations(identity, citing.object_id);
    expect(outgoing).toHaveLength(1);
    expect(outgoing[0]!.paper_object_id).toBe(cited.object_id);

    const incoming = await service().listCitedBy(identity, cited.object_id);
    expect(incoming).toHaveLength(1);
    expect(incoming[0]!.paper_object_id).toBe(citing.object_id);
  });

  it("reuses an existing active citation edge when the same citation is linked again", async () => {
    if (!available) return;
    const citing = await service().createPaper(identity, { title: "Citing Idempotently" });
    const cited = await service().createPaper(identity, { title: "Cited Once" });

    const first = await service().linkCitation(identity, citing.object_id, { cited_paper_object_id: cited.object_id });
    const second = await service().linkCitation(identity, citing.object_id, { cited_paper_object_id: cited.object_id });

    expect(second.object_relation_id).toBe(first.object_relation_id);
    const outgoing = await service().listCitations(identity, citing.object_id);
    expect(outgoing).toHaveLength(1);
  });

  it("rejects a paper citing itself", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, { title: "Self-Referential Paper" });
    await expect(
      service().linkCitation(identity, paper.object_id, { cited_paper_object_id: paper.object_id }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("rejects reading a paper from another space", async () => {
    if (!available) return;
    const paper = await service().createPaper(identity, { title: "Space-Scoped Paper" });
    await expect(service().getPaper({ spaceId: OTHER_SPACE, userId: USER }, paper.object_id)).rejects.toMatchObject({
      statusCode: 404,
    });
  });

  it("paginates listPapers honoring the requested limit and offset", async () => {
    if (!available) return;
    for (const title of ["Paper A", "Paper B", "Paper C"]) {
      await service().createPaper(identity, { title });
    }
    const firstPage = await service().listPapers(identity, { q: null, limit: 2, offset: 0 });
    expect(firstPage.items).toHaveLength(2);
    expect(firstPage.total).toBe(3);
  });
});
