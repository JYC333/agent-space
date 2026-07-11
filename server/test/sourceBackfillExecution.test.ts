import { describe,expect,it } from "vitest";
import { backfillEndpointUrl } from "../src/modules/sources/extractionWorker";
import { SourceBackfillExecutionService } from "../src/modules/sources/sourceBackfillExecutionService";
import type { Queryable } from "../src/modules/routeUtils/common";
import { vi } from "vitest";

describe("source backfill extraction windows",()=>{
  it("adds the approved date window to arXiv scans",()=>{
    const url=backfillEndpointUrl("https://export.arxiv.org/api/query?search_query=cat%3Acs.AI","arxiv",{
      window:{from:"2026-01-02T03:04:05.000Z",to:"2026-02-03T04:05:06.000Z",max_items:17},
    });
    const parsed=new URL(url);
    expect(parsed.searchParams.get("search_query")).toBe("(cat:cs.AI) AND submittedDate:[202601020304 TO 202602030405]");
    expect(parsed.searchParams.get("max_results")).toBe("17");
  });

  it("adds bounded pagination to cursor scans",()=>{
    const url=backfillEndpointUrl("https://example.test/feed","custom",{window:{cursor:2,max_items:25}});
    const parsed=new URL(url);
    expect(parsed.searchParams.get("start")).toBe("200");
    expect(parsed.searchParams.get("max_results")).toBe("25");
  });

  it("claims quota and creates a segment job in one transaction",async()=>{
    const query=vi.fn(async(sql:string)=>{
      if(sql.startsWith("SELECT * FROM source_backfill_plans"))return{rows:[{status:"approved",source_connection_id:"connection-1",quota_policy_json:{window:"minute",limit_count:2}}],rowCount:1};
      if(sql.startsWith("SELECT * FROM source_backfill_segments"))return{rows:[{id:"segment-1",window_json:{cursor:0,max_items:25}}],rowCount:1};
      if(sql.startsWith("UPDATE source_quota_buckets SET used_count"))return{rows:[{reset_at:"2026-01-01T00:01:00.000Z"}],rowCount:1};
      return{rows:[],rowCount:0};
    });
    const release=vi.fn(),connect=vi.fn().mockResolvedValue({query,release});
    const result=await new SourceBackfillExecutionService({connect,query:vi.fn()} as unknown as Queryable).executeNext("space-1","plan-1");
    expect(result).toMatchObject({segment_id:"segment-1"});
    const statements=query.mock.calls.map(call=>String(call[0]));
    expect(statements[0]).toBe("BEGIN");
    expect(statements).toEqual(expect.arrayContaining([expect.stringContaining("INSERT INTO extraction_jobs"),"COMMIT"]));
    expect(release).toHaveBeenCalledOnce();
  });

  it("persists the actual quota reset on both segment and plan",async()=>{
    const reset="2026-01-01T00:01:00.000Z";
    const query=vi.fn(async(sql:string)=>{
      if(sql.startsWith("SELECT * FROM source_backfill_plans"))return{rows:[{status:"running",source_connection_id:"connection-1",quota_policy_json:{window:"minute",limit_count:1}}],rowCount:1};
      if(sql.startsWith("SELECT * FROM source_backfill_segments"))return{rows:[{id:"segment-1",window_json:{cursor:1}}],rowCount:1};
      if(sql.startsWith("UPDATE source_quota_buckets SET used_count"))return{rows:[],rowCount:0};
      if(sql.startsWith("SELECT reset_at FROM source_quota_buckets"))return{rows:[{reset_at:reset}],rowCount:1};
      return{rows:[],rowCount:0};
    });
    const result=await new SourceBackfillExecutionService({query} as Queryable).executeNext("space-1","plan-1");
    expect(result).toEqual({paused:true,next_eligible_at:reset});
    expect(query.mock.calls.some(call=>String(call[0]).includes("scope_kind='source_connection'"))).toBe(true);
    expect(query).toHaveBeenCalledWith(expect.stringContaining("UPDATE source_backfill_segments SET next_eligible_at"),["segment-1","space-1",reset]);
    expect(query).toHaveBeenCalledWith(expect.stringContaining("UPDATE source_backfill_plans SET status='paused'"),expect.arrayContaining(["plan-1","space-1",reset]));
  });

  it("keys the quota bucket by source connection so two plans on the same connection share one budget", async () => {
    const query = vi.fn(async (sql: string, _params?: readonly unknown[]) => {
      if (sql.startsWith("SELECT * FROM source_backfill_plans")) {
        return { rows: [{ status: "approved", source_connection_id: "connection-shared", quota_policy_json: { window: "minute", limit_count: 5 } }], rowCount: 1 };
      }
      if (sql.startsWith("SELECT * FROM source_backfill_segments")) return { rows: [{ id: "segment-1", window_json: { cursor: 0, max_items: 25 } }], rowCount: 1 };
      if (sql.startsWith("UPDATE source_quota_buckets SET used_count")) return { rows: [{ reset_at: "2026-01-01T00:01:00.000Z" }], rowCount: 1 };
      return { rows: [], rowCount: 0 };
    });
    await new SourceBackfillExecutionService({ query } as Queryable).executeNext("space-1", "plan-a");
    const scopeKeyArgs = query.mock.calls
      .filter((call) => String(call[0]).includes("scope_kind='source_connection'") || String(call[0]).startsWith("INSERT INTO source_quota_buckets"))
      .map((call) => call[1] as unknown[]);
    for (const args of scopeKeyArgs) expect(args).toContain("connection-shared");
    expect(scopeKeyArgs.some((args) => args.includes("plan-a"))).toBe(false);
  });
});
