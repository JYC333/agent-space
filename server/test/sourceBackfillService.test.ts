import { describe,expect,it,vi } from "vitest";import { SourceBackfillPlanningService } from "../src/modules/sources/sourceBackfillService";import type { Queryable } from "../src/modules/routeUtils/common";
const identity={spaceId:"space-1",userId:"user-1"};
const allowed=(sql:string)=>sql.includes("effective_access_level")?{rows:[{effective_access_level:"full"}],rowCount:1}:sql.includes("SELECT c.connector_key")?{rows:[{connector_key:"arxiv"}],rowCount:1}:{rows:[{one:1}],rowCount:1};
describe("SourceBackfillPlanningService",()=>{
 it("previews deterministic bounded date segments without durable writes",async()=>{const query=vi.fn(async(sql:string)=>allowed(sql));const service=new SourceBackfillPlanningService({query} as Queryable);const out=await service.preview(identity,"connection-1",{strategy:{window_unit:"date_window",from:"2026-01-01T00:00:00.000Z",to:"2026-03-01T00:00:00.000Z",window_size:30,max_items:500}});expect(out.segments).toHaveLength(2);expect(out.segments[0]).toMatchObject({to:"2026-03-01T00:00:00.000Z"});expect(query).toHaveBeenCalledTimes(2);});
 it("rejects invalid windows",async()=>{const query=vi.fn(async(sql:string)=>allowed(sql));const service=new SourceBackfillPlanningService({query} as Queryable);await expect(service.preview(identity,"connection-1",{strategy:{from:"2026-03-01",to:"2026-01-01"}})).rejects.toMatchObject({statusCode:422});});
 it("keeps the aggregate date-window item budget bounded",async()=>{const query=vi.fn(async(sql:string)=>allowed(sql));const out=await new SourceBackfillPlanningService({query} as Queryable).preview(identity,"connection-1",{strategy:{from:"2026-01-01",to:"2026-07-01",window_size:30,max_items:17}});expect(out.segments.reduce((sum,segment)=>sum+Number(segment.max_items),0)).toBe(17);});

 it("never emits a zero-item segment when the item budget is smaller than the window count", async () => {
   const query = vi.fn(async (sql: string) => allowed(sql));
   const service = new SourceBackfillPlanningService({ query } as Queryable);
   // ~181 days of history at a 30-day window size produces 7 candidate
   // windows; a 3-item budget must stop after the first window instead of
   // emitting six trailing windows with max_items: 0.
   const out = await service.preview(identity, "connection-1", {
     strategy: { from: "2026-01-01", to: "2026-07-01", window_size: 30, max_items: 3 },
   });
   expect(out.segments.every((segment) => Number(segment.max_items) > 0)).toBe(true);
   expect(out.segments.reduce((sum, segment) => sum + Number(segment.max_items), 0)).toBe(3);
 });
 it("fails closed for unsupported connector strategies",async()=>{const query=vi.fn(async(sql:string)=>sql.includes("SELECT c.connector_key")?{rows:[{connector_key:"rss"}],rowCount:1}:allowed(sql));await expect(new SourceBackfillPlanningService({query} as Queryable).preview(identity,"connection-1",{strategy:{window_unit:"date_window"}})).rejects.toMatchObject({statusCode:422});});
 it.each([
  [{strategy:{max_items:"NaN"}},"strategy.max_items"],
  [{strategy:{window_size:1.5}},"strategy.window_size"],
  [{strategy:{direction:"sideways"}},"Only backward"],
  [{strategy:{direction:"forward"}},"Only backward"],
  [{quota_policy:{window:"week"}},"invalid quota_policy.window"],
  [{quota_policy:{limit_count:0}},"quota_policy.limit_count"],
 ])("strictly rejects malformed numeric and enum input",async(body,message)=>{const query=vi.fn(async(sql:string)=>allowed(sql));await expect(new SourceBackfillPlanningService({query} as Queryable).preview(identity,"connection-1",body)).rejects.toMatchObject({statusCode:422,message:expect.stringContaining(message)});});
 it("creates the plan and all segments in one explicit transaction",async()=>{
  const clientQuery=vi.fn(async(sql:string)=>{if(sql.startsWith("INSERT INTO source_backfill_plans"))return{rows:[{id:"plan-1"}],rowCount:1};if(sql.startsWith("SELECT * FROM source_backfill_plans"))return{rows:[{id:"plan-1",source_connection_id:"connection-1"}],rowCount:1};if(sql.startsWith("SELECT * FROM source_backfill_segments"))return{rows:[{seq:0}],rowCount:1};return{rows:[],rowCount:0};});
  const release=vi.fn(),connect=vi.fn().mockResolvedValue({query:clientQuery,release});
  const query=vi.fn(async(sql:string)=>allowed(sql));
  const result=await new SourceBackfillPlanningService({query,connect} as unknown as Queryable).create(identity,"connection-1",{idempotency_key:"key-1",strategy:{from:"2026-01-01",to:"2026-01-02"}});
  expect(result).toMatchObject({id:"plan-1",segments:[{seq:0}]});expect(clientQuery.mock.calls.map(call=>call[0])).toEqual(expect.arrayContaining(["BEGIN","COMMIT"]));expect(clientQuery).toHaveBeenCalledWith(expect.stringContaining("ON CONFLICT (space_id,idempotency_key) DO NOTHING"),expect.any(Array));expect(release).toHaveBeenCalledOnce();
 });
 it("returns the winning concurrent idempotent plan without adding segments",async()=>{
  const query=vi.fn(async(sql:string)=>{if(sql.startsWith("INSERT INTO source_backfill_plans"))return{rows:[],rowCount:0};if(sql.startsWith("SELECT id, source_connection_id"))return{rows:[{id:"winner",source_connection_id:"connection-1"}],rowCount:1};if(sql.startsWith("SELECT * FROM source_backfill_plans"))return{rows:[{id:"winner"}],rowCount:1};if(sql.startsWith("SELECT * FROM source_backfill_segments"))return{rows:[{seq:0}],rowCount:1};return allowed(sql);});
  const result=await new SourceBackfillPlanningService({query} as Queryable).create(identity,"connection-1",{idempotency_key:"same",strategy:{from:"2026-01-01",to:"2026-01-02"}});
  expect(result).toMatchObject({id:"winner"});expect(query.mock.calls.filter(call=>String(call[0]).startsWith("INSERT INTO source_backfill_segments"))).toHaveLength(0);
 });
 it("rejects a binding from another connection and mismatched operation project",async()=>{
  const wrongBinding=vi.fn(async(sql:string)=>sql.includes("project_source_bindings")?{rows:[],rowCount:0}:allowed(sql));
  await expect(new SourceBackfillPlanningService({query:wrongBinding} as Queryable).create(identity,"connection-1",{idempotency_key:"a",project_source_binding_id:"binding-1"})).rejects.toMatchObject({statusCode:404});
  const mismatch=vi.fn(async(sql:string)=>{if(sql.includes("project_source_bindings"))return{rows:[{project_id:"project-1"}],rowCount:1};if(sql.includes("project_operations"))return{rows:[{project_id:"project-2"}],rowCount:1};return allowed(sql);});
  await expect(new SourceBackfillPlanningService({query:mismatch} as Queryable).create(identity,"connection-1",{idempotency_key:"b",project_source_binding_id:"binding-1",project_operation_id:"operation-1"})).rejects.toMatchObject({statusCode:422});
 });
 it("durably reuses an agent proposal by run action idempotency key",async()=>{const query=vi.fn(async(sql:string)=>{if(sql.includes("action_idempotency_key"))return{rows:[{id:"proposal-1",status:"accepted"}],rowCount:1};return allowed(sql);});const result=await new SourceBackfillPlanningService({query} as Queryable).proposeStart(identity,"connection-1","plan-1",{agentId:"agent-1",runId:"run-1",idempotencyKey:"call-1"});expect(result).toEqual({proposal:{id:"proposal-1",status:"accepted"},auto_applied:true});expect(query.mock.calls.some(call=>String(call[0]).includes("FOR UPDATE"))).toBe(false);});
 it.each([
  ["belongs to another Project"],
  ["has no Project binding or operation"],
 ])("does not create a proposal when an agent-scoped plan %s",async()=>{
  const query=vi.fn(async(sql:string)=>sql.includes("FROM source_backfill_plans p LEFT JOIN project_source_bindings")?{rows:[],rowCount:0}:allowed(sql));
  await expect(new SourceBackfillPlanningService({query} as Queryable).proposeStart(identity,"connection-1","plan-1",{agentId:"agent-1",runId:"run-1",idempotencyKey:"call-1",projectId:"project-1"})).rejects.toMatchObject({statusCode:404,message:"Backfill plan not found in this Project"});
  expect(query.mock.calls.some(call=>String(call[0]).includes("INSERT INTO proposals"))).toBe(false);
  expect(query.mock.calls.some(call=>String(call[0]).includes("action_idempotency_key"))).toBe(false);
 });
});
