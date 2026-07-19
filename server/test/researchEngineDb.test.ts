import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Pool } from "pg";
import type { ServerConfig } from "../src/config";
import { migrate } from "../src/db/migrator";
import { runBuiltInSeeds } from "../src/db/seeds";
import { ResearchEngineService } from "../src/modules/research/engine/service";
import type { ResearchQueryPlan } from "../src/modules/research/engine/types";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";

const SPACE = "11111111-1111-4111-8111-111111111111";
const USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
let database: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    database = await getTestPostgres(__filename);
    pool = new Pool({ connectionString: database.getConnectionUri(), max: 2 });
    await migrate(pool, join(process.cwd(), "migrations"));
    await runBuiltInSeeds(pool, { info: () => {} }, join(process.cwd(), "..", "catalog"));
    const now = new Date().toISOString();
    await pool.query(`INSERT INTO spaces (id,name,type,created_at,updated_at) VALUES ($1,'Research','personal',$2,$2)`, [SPACE, now]);
    await pool.query(`INSERT INTO users (id,display_name,status,created_at,updated_at) VALUES ($1,'Owner','active',$2,$2)`, [USER, now]);
    await pool.query(`INSERT INTO space_memberships (id,space_id,user_id,role,status,created_at,updated_at) VALUES ($1,$2,$3,'owner','active',$4,$4)`, [randomUUID(), SPACE, USER, now]);
    await pool.query(`INSERT INTO projects (id,space_id,owner_user_id,name,status,created_at,updated_at) VALUES ($1,$2,$3,'Project','active',$4,$4)`, [PROJECT, SPACE, USER, now]);
    available = true;
  } catch (error) {
    console.warn(`[research-engine-db] skipped — Docker/Postgres unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }
}, 180_000);

afterAll(async () => { await pool?.end(); await database?.stop(); });

describe("Research Engine strategy persistence (real Postgres)", () => {
  it("persists provider plans, partial errors, hit counts, and deduplicated results", async () => {
    if (!available || !pool) return;
    const plan: ResearchQueryPlan = {
      question: "How should agent memory be evaluated?", scope: {}, filters: {}, time_window: null,
      providers: [
        { provider_key: "openalex", query: { search: "agent memory evaluation" }, rationale: "Broad coverage" },
        { provider_key: "semantic_scholar", query: { query: "agent memory evaluation" }, rationale: "Graph coverage" },
        { provider_key: "arxiv", query: { search_query: "agent memory evaluation" }, rationale: "Preprints" },
      ],
    };
    const service = new ResearchEngineService(pool, {} as ServerConfig, {
      planner: { plan: async () => plan },
      previews: { preview: async (_identity, body) => {
        if (body.provider_key === "arxiv") throw new Error("provider unavailable");
        const provider = String(body.provider_key);
        return { approximate_hit_count: provider === "openalex" ? 12 : 8, compiled_query: "agent memory evaluation", samples: [{
          title: "Agent Memory Evaluation", author: "Ada", source_uri: `https://example.test/${provider}`,
          metadata: { doi: "10.1000/shared", authors: ["Ada"], ...(provider === "openalex" ? { openalex_id: "W1" } : { semantic_scholar_id: "S1" }) },
        }] };
      } },
    });

    const result = await service.search({ spaceId: SPACE, userId: USER }, { question: plan.question, project_id: PROJECT });
    expect(result.strategy.status).toBe("partial");
    expect(result.candidates).toHaveLength(1);
    expect(result.candidates[0]).toMatchObject({ providers: ["openalex", "semantic_scholar"], openalex_id: "W1", semantic_scholar_id: "S1" });
    const stored = await pool.query(`SELECT status,queries_json,hit_counts_json,provider_errors_json,result_count FROM research_search_strategies WHERE id=$1`, [result.strategy.id]);
    expect(stored.rows[0]).toMatchObject({ status: "partial", result_count: 1, hit_counts_json: { openalex: 12, semantic_scholar: 8 }, provider_errors_json: { arxiv: "provider unavailable" } });
    expect(stored.rows[0].queries_json).toHaveLength(3);
  });
});
