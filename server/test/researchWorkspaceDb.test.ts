import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import type { ServerConfig } from "../src/config";
import { migrate } from "../src/db/migrator";
import { ProjectResearchWorkspaceService } from "../src/modules/projectResearch/workspaceService";
import { ProjectResearchMonitorComparisonService } from "../src/modules/projectResearch/monitorComparisonService";
import { ProjectResearchIntegrityMonitorService, enqueueDueResearchIntegrityChecks } from "../src/modules/projectResearch/integrityMonitorService";
import { writeNotebookSection } from "../src/modules/projectResearch/notebookWriteService";
import { PgReaderRepository } from "../src/modules/reader/repository";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";

const SPACE = "11111111-1111-4111-8111-111111111111"; const USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"; const PROJECT = "55555555-5555-4555-8555-555555555555";
let database: TestPostgresDatabase | undefined; let pool: Pool | undefined; let available = false;

beforeAll(async () => { try { database = await getTestPostgres(__filename); pool = new Pool({ connectionString: database.getConnectionUri(), max: 2 }); await migrate(pool, join(process.cwd(), "migrations")); available = true; } catch (error) { console.warn(`[research-workspace-db] skipped — Docker/Postgres unavailable: ${error instanceof Error ? error.message : String(error)}`); } }, 180_000);
afterAll(async () => { await pool?.end(); await database?.stop(); });
beforeEach(async () => { if (!available || !pool) return; await pool.query(`TRUNCATE research_checklist_items,research_paper_cards,research_notebook_section_revisions,research_notebook_sections,research_notebooks,project_corpus_items,source_items,projects,space_memberships,users,spaces CASCADE`); const now = new Date().toISOString(); await pool.query(`INSERT INTO spaces (id,name,type,created_at,updated_at) VALUES ($1,'Space','personal',$2,$2)`, [SPACE, now]); await pool.query(`INSERT INTO users (id,display_name,status,created_at,updated_at) VALUES ($1,'Owner','active',$2,$2)`, [USER, now]); await pool.query(`INSERT INTO space_memberships (id,space_id,user_id,role,status,created_at,updated_at) VALUES ($1,$2,$3,'owner','active',$4,$4)`, [randomUUID(), SPACE, USER, now]); await pool.query(`INSERT INTO projects (id,space_id,owner_user_id,name,status,created_at,updated_at) VALUES ($1,$2,$3,'Project','active',$4,$4)`, [PROJECT, SPACE, USER, now]); });

describe("Research Workspace (real Postgres)", () => {
  it("creates four notebook sections and enforces optimistic section versions", async () => {
    if (!available || !pool) return; const service = new ProjectResearchWorkspaceService(pool); const identity = { spaceId: SPACE, userId: USER };
    const workspace = await service.initializeWorkspace(identity, PROJECT); expect(workspace.notebook.sections.map((v: { section_key: string }) => v.section_key)).toEqual(["understanding", "questions", "ideas", "experiments"]);
    const doc = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Current finding" }] }] };
    const updated = await service.updateSection(identity, PROJECT, "understanding", { base_version: 1, content_json: doc }); expect(updated).toMatchObject({ version: 2, normalized_text: "Current finding", updated_by_user_id: USER });
    const reader = await new PgReaderRepository(pool, { artifactStorageRoot: "/tmp", sandboxRoot: "/tmp" } as ServerConfig).getDocument(identity, "research_notebook", updated.id);
    expect(reader).toMatchObject({ document_type: "research_notebook", document_id: updated.id, normalized_text: "Current finding", content_hash: updated.content_hash });
    await expect(service.updateSection(identity, PROJECT, "understanding", { base_version: 1, content_json: doc })).rejects.toMatchObject({ statusCode: 409 });
  });

  it("applies AI block ops without touching other blocks and supports rollback from the revision history", async () => {
    if (!available || !pool) return; const service = new ProjectResearchWorkspaceService(pool); const identity = { spaceId: SPACE, userId: USER };
    await service.initializeWorkspace(identity, PROJECT);
    const boldDoc = { type: "doc", content: [
      { type: "paragraph", content: [{ type: "text", marks: [{ type: "bold" }], text: "User formatted claim" }] },
      { type: "paragraph", content: [{ type: "text", text: "Second block" }] },
    ] };
    await service.updateSection(identity, PROJECT, "understanding", { base_version: 1, content_json: boldDoc });
    const written = await writeNotebookSection(pool, {
      spaceId: SPACE, projectId: PROJECT, sectionKey: "understanding",
      content: { kind: "ops", ops: [{ op: "replace", index: 1, count: 1, markdown: "Replaced second block" }, { op: "append", markdown: "## Monitoring update\n\n- New contradiction" }] },
      source: "ai_monitoring", refs: ["item-1"], diff: { ops: [] },
    });
    expect(written.outcome).toBe("written");
    if (written.outcome !== "written") return;
    // The user's formatted block survives byte-identical — the whole point of block ops.
    expect((written.section.content_json as { content: Array<Record<string, unknown>> }).content[0]).toEqual(boldDoc.content[0]);
    expect(written.section.normalized_text).toBe("User formatted claim\n\nReplaced second block\n\nMonitoring update\n\n- New contradiction");
    const revisions = await service.sectionRevisions(identity, PROJECT, "understanding", {});
    expect(revisions.map((row) => [row.version, row.source])).toEqual([[3, "ai_monitoring"], [2, "user_edit"], [1, "seed"]]);
    const restored = await service.rollbackSection(identity, PROJECT, "understanding", { to_version: 2 });
    expect(restored).toMatchObject({ version: 4, normalized_text: "User formatted claim\n\nSecond block" });
    expect((await service.sectionRevisions(identity, PROJECT, "understanding", {})).map((row) => [row.version, row.source])[0]).toEqual([4, "rollback"]);
  });

  it("keeps user-edited paper cards when deep analysis runs again", async () => {
    if (!available || !pool) return; const now = new Date().toISOString(); const item = randomUUID(); const corpus = randomUUID();
    await pool.query(`INSERT INTO source_items (id,space_id,owner_user_id,visibility,item_type,title,first_seen_at,last_seen_at,content_state,retention_policy,created_at,updated_at) VALUES ($1,$2,$3,'space_shared','feed_entry','Paper',$4,$4,'excerpt_saved','summary_only',$4,$4)`, [item, SPACE, USER, now]);
    await pool.query(`INSERT INTO project_corpus_items (id,space_id,project_id,source_item_id,role,status,triage_status,triage_confirmed_by_user,read_status,created_at,updated_at) VALUES ($1,$2,$3,$4,'candidate','active','relevant',true,'unread',$5,$5)`, [corpus, SPACE, PROJECT, item, now]);
    const service = new ProjectResearchWorkspaceService(pool);
    const first = await service.materializePaperCardsFromDeepAnalysis({ spaceId: SPACE, projectId: PROJECT, runId: randomUUID(), summaries: [{ source_item_id: item, summary_markdown: "WHY: Relevant\nHOW: Experiment\nWHAT: Result" }] });
    expect(first).toBe(1);
    await service.upsertPaperCard({ spaceId: SPACE, userId: USER }, PROJECT, item, { why_md: "My reason", how_md: "My method", what_md: "My result" });
    const second = await service.materializePaperCardsFromDeepAnalysis({ spaceId: SPACE, projectId: PROJECT, runId: randomUUID(), summaries: [{ source_item_id: item, summary_markdown: "WHY: Replaced\nHOW: Replaced\nWHAT: Replaced" }] });
    expect(second).toBe(0);
    expect((await pool.query(`SELECT why_md,edited_by_user FROM research_paper_cards WHERE source_item_id=$1`, [item])).rows[0]).toEqual({ why_md: "My reason", edited_by_user: true });
  });

  it("materializes monitoring stances and appends only disruptive evidence to the notebook", async () => {
    if (!available || !pool) return;
    const now = new Date().toISOString(); const workflow = randomUUID(); const operation = randomUUID();
    const supporting = randomUUID(); const contradicting = randomUUID();
    await new ProjectResearchWorkspaceService(pool).initializeWorkspace({ spaceId: SPACE, userId: USER }, PROJECT);
    await pool.query(
      `INSERT INTO project_research_workflows (id,space_id,project_id,workflow_type,status,mode,state_json,started_by_user_id,created_at,updated_at)
       VALUES ($1,$2,$3,'literature_review','active','autonomous','{}'::jsonb,$4,$5,$5)`,
      [workflow, SPACE, PROJECT, USER, now],
    );
    for (const [item, title] of [[supporting, "Supporting paper"], [contradicting, "Contradicting paper"]]) {
      await pool.query(
        `INSERT INTO source_items (id,space_id,owner_user_id,visibility,item_type,title,first_seen_at,last_seen_at,content_state,retention_policy,created_at,updated_at)
         VALUES ($1,$2,$3,'space_shared','feed_entry',$4,$5,$5,'excerpt_saved','summary_only',$5,$5)`,
        [item, SPACE, USER, title, now],
      );
      await pool.query(
        `INSERT INTO project_corpus_items (id,space_id,project_id,source_item_id,role,status,triage_status,triage_confirmed_by_user,read_status,created_at,updated_at)
         VALUES ($1,$2,$3,$4,'candidate','active','relevant',true,'unread',$5,$5)`,
        [randomUUID(), SPACE, PROJECT, item, now],
      );
    }
    await pool.query(
      `INSERT INTO research_scan_summaries (id,space_id,project_id,workflow_id,operation_id,scan_key,scanned_at,new_item_count,relevant_count,maybe_count,excluded_count,created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,2,2,0,0,$7)`,
      [randomUUID(), SPACE, PROJECT, workflow, operation, `operation:${operation}`, now],
    );
    const comparisonRun = randomUUID();
    const comparisonInput = {
      spaceId: SPACE, projectId: PROJECT, workflowId: workflow, operationId: operation, runId: comparisonRun,
      expectedSourceItemIds: [supporting, contradicting],
      output: { comparisons: [
        { source_item_id: supporting, stance: "supports", detail: "Replicates the current effect.", affected_sections: ["understanding"] },
        { source_item_id: contradicting, stance: "contradicts", detail: "Finds no effect under stronger controls.", affected_sections: ["understanding", "questions"] },
      ] },
    };
    const comparisonService = new ProjectResearchMonitorComparisonService(pool);
    const result = await comparisonService.materialize(comparisonInput);
    const replay = await comparisonService.materialize(comparisonInput);
    expect(result.notebookVersion).toBe(2);
    expect(replay.notebookVersion).toBe(2);
    expect((await pool.query(`SELECT supports_count,contradicts_count,new_direction_count FROM research_scan_summaries WHERE operation_id=$1`, [operation])).rows[0])
      .toEqual({ supports_count: 1, contradicts_count: 1, new_direction_count: 0 });
    const section = (await pool.query(`SELECT version,normalized_text,refs_json FROM research_notebook_sections s JOIN research_notebooks n ON n.id=s.notebook_id WHERE n.project_id=$1 AND s.section_key='understanding'`, [PROJECT])).rows[0];
    expect(section).toMatchObject({ version: 2, refs_json: [contradicting] });
    expect(String(section?.normalized_text)).toContain("**Contradiction**");
    expect(String(section?.normalized_text)).not.toContain("Replicates");
    const supportOnlyOperation = randomUUID();
    await pool.query(
      `INSERT INTO research_scan_summaries (id,space_id,project_id,workflow_id,operation_id,scan_key,scanned_at,new_item_count,relevant_count,maybe_count,excluded_count,created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,1,1,0,0,$7)`,
      [randomUUID(), SPACE, PROJECT, workflow, supportOnlyOperation, `operation:${supportOnlyOperation}`, now],
    );
    const supportOnly = await comparisonService.materialize({
      spaceId: SPACE, projectId: PROJECT, workflowId: workflow, operationId: supportOnlyOperation, runId: randomUUID(),
      expectedSourceItemIds: [supporting],
      output: { comparisons: [{ source_item_id: supporting, stance: "supports", detail: "Replicates the current effect.", affected_sections: ["understanding"] }] },
    });
    expect(supportOnly.notebookVersion).toBeNull();
    expect((await pool.query(`SELECT version FROM research_notebook_sections s JOIN research_notebooks n ON n.id=s.notebook_id WHERE n.project_id=$1 AND s.section_key='understanding'`, [PROJECT])).rows[0]).toEqual({ version: 2 });
  });

  it("deduplicates cited-DOI integrity alerts and creates review work", async () => {
    if (!available || !pool) return;
    const now = new Date().toISOString(); const workflow = randomUUID(); const sourceItem = randomUUID();
    const service = new ProjectResearchWorkspaceService(pool);
    const workspace = await service.initializeWorkspace({ spaceId: SPACE, userId: USER }, PROJECT);
    await pool.query(
      `INSERT INTO project_research_workflows (id,space_id,project_id,workflow_type,current_stage,status,mode,state_json,started_by_user_id,created_at,updated_at)
       VALUES ($1,$2,$3,'literature_review','monitoring','active','autonomous','{}'::jsonb,$4,$5,$5)`,
      [workflow, SPACE, PROJECT, USER, now],
    );
    await pool.query(
      `INSERT INTO source_items (id,space_id,owner_user_id,visibility,item_type,title,metadata_json,first_seen_at,last_seen_at,content_state,retention_policy,created_at,updated_at)
       VALUES ($1,$2,$3,'space_shared','feed_entry','Cited paper',$4::jsonb,$5,$5,'excerpt_saved','summary_only',$5,$5)`,
      [sourceItem, SPACE, USER, JSON.stringify({ doi: "10.1000/original" }), now],
    );
    await pool.query(
      `INSERT INTO project_corpus_items (id,space_id,project_id,source_item_id,role,status,triage_status,triage_confirmed_by_user,read_status,created_at,updated_at)
       VALUES ($1,$2,$3,$4,'reference','active','relevant',true,'read',$5,$5)`,
      [randomUUID(), SPACE, PROJECT, sourceItem, now],
    );
    await pool.query(`UPDATE research_notebook_sections SET refs_json=$2::jsonb WHERE notebook_id=$1 AND section_key='understanding'`, [workspace.notebook.id, JSON.stringify([sourceItem])]);
    const monitor = new ProjectResearchIntegrityMonitorService(pool, async () => ({ message: { "updated-by": [
      { DOI: "10.1000/retraction", type: "retraction", source: "retraction-watch" },
    ] } }));
    const first = await monitor.check({ spaceId: SPACE, projectId: PROJECT, workflowId: workflow, userId: USER });
    const second = await monitor.check({ spaceId: SPACE, projectId: PROJECT, workflowId: workflow, userId: USER });
    expect(first.alerts).toHaveLength(1); expect(first.checkpointId).toBeTruthy(); expect(first.checklistItemIds).toHaveLength(1);
    expect(second.alerts).toHaveLength(0);
    expect(Number((await pool.query(`SELECT count(*) AS count FROM research_integrity_alerts WHERE project_id=$1`, [PROJECT])).rows[0]?.count)).toBe(1);
    expect((await pool.query(`SELECT text,origin FROM research_checklist_items WHERE project_id=$1`, [PROJECT])).rows[0]).toMatchObject({ origin: "agent" });
    expect((await pool.query(`SELECT integrity_alerts_json FROM research_scan_summaries WHERE workflow_id=$1`, [workflow])).rows[0]?.integrity_alerts_json).toMatchObject([{ event_type: "retraction", doi: "10.1000/original" }]);
    expect((await pool.query(`SELECT checkpoint_type,status FROM project_research_checkpoints WHERE workflow_id=$1`, [workflow])).rows[0]).toEqual({ checkpoint_type: "integrity_gate", status: "pending" });
    expect(await enqueueDueResearchIntegrityChecks(pool, new Date("2026-07-19T12:00:00.000Z"))).toBe(1);
    expect(await enqueueDueResearchIntegrityChecks(pool, new Date("2026-07-19T13:00:00.000Z"))).toBe(0);
  });
});
