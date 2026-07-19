import { randomUUID } from "node:crypto";
import { HttpError, objectValue, optionalString, type Queryable, type SpaceUserIdentity, withQueryableTransaction } from "../routeUtils/common";
import { assertProjectReadable, assertProjectWriter, canWriteProject } from "../projects/access";
import { ProjectCorpusRepository } from "../projects/corpusRepository";
import type { ServerConfig } from "../../config";
import { ProjectResearchExecutionProfileService } from "./executionProfileService";
import { PgRunRepository } from "../runs/repository";
import { PgJobQueueRepository } from "../jobs/repository";
import { createManagedExecutionPolicy } from "../policy/managedExecutionPolicy";
import { markdownToPm, parseNotebookOps, pmBlocksText, type NotebookOp } from "./notebookDocument";
import {
  insertInitialRevision,
  listNotebookRevisions,
  rollbackNotebookSection,
  sha256,
  writeNotebookSection,
} from "./notebookWriteService";

export const NOTEBOOK_SECTION_KEYS = ["understanding", "questions", "ideas", "experiments"] as const;
type SectionKey = typeof NOTEBOOK_SECTION_KEYS[number];

/**
 * D6: ad-hoc analysis has its own small budget lane, independent of the
 * project research operation budget. Enforced per project per UTC day.
 */
export const RESEARCH_ADHOC_DAILY_RUN_LIMIT = 20;

const ADHOC_OUTPUT_CONTRACT = {
  type: "json_schema",
  schema_id: "research.adhoc_analyze.v2",
  strict: true,
  stage: "research_adhoc",
  schema: {
    type: "object",
    properties: {
      notebook_update: {
        type: "object",
        properties: {
          section_key: { enum: NOTEBOOK_SECTION_KEYS },
          ops: {
            type: "array",
            minItems: 1,
            maxItems: 20,
            items: {
              type: "object",
              properties: {
                op: { enum: ["append", "insert", "replace", "delete"] },
                index: { type: ["integer", "null"], minimum: 0 },
                count: { type: ["integer", "null"], minimum: 1 },
                markdown: { type: ["string", "null"], maxLength: 20_000 },
              },
              required: ["op", "index", "count", "markdown"],
              additionalProperties: false,
            },
          },
          refs: { type: "array", items: { type: "string" } },
        },
        required: ["section_key", "ops", "refs"],
        additionalProperties: false,
      },
    },
    required: ["notebook_update"],
    additionalProperties: false,
  },
} as const;

export class ProjectResearchWorkspaceService {
  constructor(private readonly db: Queryable, private readonly config?: ServerConfig) {}

  async getWorkspace(identity: SpaceUserIdentity, projectId: string) {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const found = await this.db.query<any>(`SELECT * FROM research_notebooks WHERE space_id=$1 AND project_id=$2`, [identity.spaceId, projectId]);
    const notebook = found.rows[0]; if (!notebook) throw new HttpError(404, "Research workspace not initialized");
    const [sections, checklist, reports] = await Promise.all([
      this.db.query(`SELECT id,section_key,content_json,normalized_text,content_hash,refs_json,version,updated_by_user_id,updated_by_run_id,updated_at FROM research_notebook_sections WHERE notebook_id=$1 ORDER BY CASE section_key WHEN 'understanding' THEN 1 WHEN 'questions' THEN 2 WHEN 'ideas' THEN 3 ELSE 4 END`, [notebook.id]),
      this.db.query(`SELECT * FROM research_checklist_items WHERE space_id=$1 AND project_id=$2 ORDER BY sort_order,id`, [identity.spaceId, projectId]),
      this.db.query(`SELECT id,research_question,research_question_version,status,run_kind,created_at,updated_at FROM project_research_reports WHERE space_id=$1 AND project_id=$2 ORDER BY created_at DESC`, [identity.spaceId, projectId]),
    ]);
    return { notebook: { ...notebook, sections: sections.rows }, checklist: checklist.rows, reports: reports.rows };
  }

  async initializeWorkspace(identity: SpaceUserIdentity, projectId: string) {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const existing = await this.db.query(`SELECT id FROM research_notebooks WHERE space_id=$1 AND project_id=$2`, [identity.spaceId, projectId]);
    if (existing.rows[0]) return this.getWorkspace(identity, projectId);
    if (!await canWriteProject(this.db, identity.spaceId, projectId, identity.userId)) {
      // Readers must not fail the page; they see the uninitialized state.
      throw new HttpError(404, "Research workspace not initialized");
    }
    await withQueryableTransaction(this.db, async (db) => {
      const service = new ProjectResearchWorkspaceService(db, this.config);
      await service.ensureNotebook(identity.spaceId, projectId);
      // Projects with reports from before the living workspace existed get
      // their notebook seeded from the latest completed report once.
      const report = await db.query<{ synthesis_run_id: string; content_json: unknown }>(
        `SELECT synthesis_run_id,content_json FROM project_research_reports
          WHERE space_id=$1 AND project_id=$2 AND status <> 'rejected'
          ORDER BY created_at DESC LIMIT 1`,
        [identity.spaceId, projectId],
      );
      if (report.rows[0]) {
        await service.seedFromReport({
          spaceId: identity.spaceId,
          projectId,
          runId: report.rows[0].synthesis_run_id,
          report: objectValue(report.rows[0].content_json),
        });
      }
    });
    return this.getWorkspace(identity, projectId);
  }

  async readingList(identity: SpaceUserIdentity, projectId: string, filters: Record<string, unknown>) {
    const corpus = await new ProjectCorpusRepository(this.db).list(identity, projectId, {
      status: "active", triageStatus: optionalString(filters.triage_status), readStatus: optionalString(filters.read_status), role: null,
      q: optionalString(filters.q), limit: Math.min(100, Math.max(1, Number(filters.limit) || 50)), offset: Math.max(0, Number(filters.offset) || 0),
    });
    const items = Array.isArray(corpus.items) ? corpus.items as Record<string, unknown>[] : [];
    const sourceIds = items.map((row) => optionalString(row.source_item_id)).filter((id): id is string => Boolean(id));
    const cards = sourceIds.length ? await this.db.query(`SELECT * FROM research_paper_cards WHERE space_id=$1 AND project_id=$2 AND source_item_id=ANY($3::text[])`, [identity.spaceId, projectId, sourceIds]) : { rows: [] as Record<string, unknown>[] };
    const bySource = new Map(cards.rows.map((card) => [String(card.source_item_id), card]));
    return { ...corpus, items: items.map((row) => ({ ...row, paper_card: bySource.get(String(row.source_item_id)) ?? null })) };
  }

  async updateSection(identity: SpaceUserIdentity, projectId: string, sectionKey: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    assertSectionKey(sectionKey);
    const baseVersion = Number(body.base_version); const contentJson = objectValue(body.content_json);
    if (!Number.isInteger(baseVersion) || baseVersion < 1 || contentJson.type !== "doc") throw new HttpError(422, "base_version and Tiptap content_json are required");
    const result = await withQueryableTransaction(this.db, (db) => writeNotebookSection(db, {
      spaceId: identity.spaceId, projectId, sectionKey,
      expectVersion: baseVersion,
      content: { kind: "doc", doc: contentJson },
      source: "user_edit",
      userId: identity.userId,
    }));
    if (result.outcome !== "written") throw new HttpError(409, "Notebook section changed; reload before saving");
    return result.section;
  }

  async sectionRevisions(identity: SpaceUserIdentity, projectId: string, sectionKey: string, filters: Record<string, unknown>) {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    assertSectionKey(sectionKey);
    return listNotebookRevisions(this.db, { spaceId: identity.spaceId, projectId, sectionKey, limit: Number(filters.limit) || undefined });
  }

  async rollbackSection(identity: SpaceUserIdentity, projectId: string, sectionKey: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    assertSectionKey(sectionKey);
    const toVersion = Number(body.to_version);
    if (!Number.isInteger(toVersion) || toVersion < 1) throw new HttpError(422, "to_version is required");
    return withQueryableTransaction(this.db, (db) => rollbackNotebookSection(db, {
      spaceId: identity.spaceId, projectId, sectionKey, toVersion, userId: identity.userId,
    }));
  }

  async upsertPaperCard(identity: SpaceUserIdentity, projectId: string, sourceItemId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const now = new Date().toISOString();
    const result = await this.db.query(
      `INSERT INTO research_paper_cards (id,space_id,project_id,source_item_id,object_id,why_md,how_md,what_md,provenance_json,edited_by_user,created_at,updated_at)
       SELECT $1::varchar,$2::varchar,$3::varchar,$4::varchar,pci.object_id,$5::text,$6::text,$7::text,'{}'::jsonb,true,$8::timestamptz,$8::timestamptz FROM project_corpus_items pci
       WHERE pci.space_id=$2::varchar AND pci.project_id=$3::varchar AND pci.source_item_id=$4::varchar AND pci.status='active' LIMIT 1
       ON CONFLICT (project_id,source_item_id) DO UPDATE SET why_md=EXCLUDED.why_md,how_md=EXCLUDED.how_md,what_md=EXCLUDED.what_md,edited_by_user=true,updated_at=EXCLUDED.updated_at RETURNING *`,
      [randomUUID(), identity.spaceId, projectId, sourceItemId, text(body.why_md, 4000), text(body.how_md, 4000), text(body.what_md, 4000), now],
    );
    if (!result.rows[0]) throw new HttpError(404, "Project paper not found");
    return result.rows[0];
  }

  async createChecklistItem(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const value = text(body.text, 2000); if (!value) throw new HttpError(422, "text is required");
    const now = new Date().toISOString();
    const result = await this.db.query(`INSERT INTO research_checklist_items (id,space_id,project_id,text,status,sort_order,origin,created_at,updated_at) SELECT $1,$2,$3,$4,'open',COALESCE(max(sort_order)+1,0),'user',$5,$5 FROM research_checklist_items WHERE space_id=$2 AND project_id=$3 RETURNING *`, [randomUUID(), identity.spaceId, projectId, value, now]);
    return result.rows[0];
  }

  async updateChecklistItem(identity: SpaceUserIdentity, projectId: string, itemId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const status = optionalString(body.status); if (status && !["open", "done", "dismissed"].includes(status)) throw new HttpError(422, "invalid checklist status");
    const value = body.text === undefined ? null : text(body.text, 2000);
    if (body.text !== undefined && !value) throw new HttpError(422, "text must not be empty");
    const order = Number.isInteger(body.sort_order) && Number(body.sort_order) >= 0 ? Number(body.sort_order) : null;
    if (body.sort_order !== undefined && order === null) throw new HttpError(422, "sort_order must be a non-negative integer");
    const result = await this.db.query(`UPDATE research_checklist_items SET text=COALESCE($4,text),status=COALESCE($5,status),sort_order=COALESCE($6,sort_order),updated_at=$7 WHERE id=$1 AND space_id=$2 AND project_id=$3 RETURNING *`, [itemId, identity.spaceId, projectId, value, status, order, new Date().toISOString()]);
    if (!result.rows[0]) throw new HttpError(404, "Checklist item not found"); return result.rows[0];
  }

  async deleteChecklistItem(identity: SpaceUserIdentity, projectId: string, itemId: string) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const result = await this.db.query(`DELETE FROM research_checklist_items WHERE id=$1 AND space_id=$2 AND project_id=$3 RETURNING id`, [itemId, identity.spaceId, projectId]);
    if (!result.rows[0]) throw new HttpError(404, "Checklist item not found"); return { id: itemId };
  }

  async askAi(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    if (!this.config) throw new HttpError(500, "Research execution is unavailable");
    const prompt = text(body.prompt, 4000); const sectionKey = optionalString(body.section_key) ?? "understanding"; assertSectionKey(sectionKey);
    if (!prompt) throw new HttpError(422, "prompt is required");
    const used = await this.adhocRunsUsedToday(identity.spaceId, projectId);
    if (used >= RESEARCH_ADHOC_DAILY_RUN_LIMIT) {
      throw new HttpError(429, `The ad-hoc research budget of ${RESEARCH_ADHOC_DAILY_RUN_LIMIT} runs per day is spent for this project; try again tomorrow`);
    }
    const notebook = await this.ensureNotebook(identity.spaceId, projectId);
    const section = await this.db.query<{ version: number; content_json: Record<string, unknown> }>(`SELECT version,content_json FROM research_notebook_sections WHERE notebook_id=$1 AND section_key=$2`, [notebook.id, sectionKey]);
    const baseVersion = section.rows[0]?.version ?? 1;
    const blocks = pmBlocksText(section.rows[0]?.content_json ?? { type: "doc", content: [] });
    const paperIds = (Array.isArray(body.source_item_ids) ? body.source_item_ids : []).filter((v): v is string => typeof v === "string").slice(0, 20);
    const papers = paperIds.length ? await this.db.query<{ title: string; excerpt: string | null; why_md: string | null; how_md: string | null; what_md: string | null }>(
      `SELECT si.title,si.excerpt,pc.why_md,pc.how_md,pc.what_md FROM project_corpus_items pci JOIN source_items si ON si.id=pci.source_item_id LEFT JOIN research_paper_cards pc ON pc.project_id=pci.project_id AND pc.source_item_id=pci.source_item_id WHERE pci.space_id=$1 AND pci.project_id=$2 AND pci.source_item_id=ANY($3::text[]) AND pci.status='active'`,
      [identity.spaceId, projectId, paperIds],
    ) : { rows: [] };
    const execution = objectValue(body.execution); const resolved = await new ProjectResearchExecutionProfileService(this.db, this.config).resolve(identity, { modelProviderId: optionalString(execution.model_provider_id), modelName: optionalString(execution.model_name) });
    const instruction = [
      "Perform the requested bounded research analysis using only the supplied notebook and paper context.",
      `User request: ${prompt}`, `Target section: ${sectionKey}`, `Section base version: ${baseVersion}`,
      `Current section as indexed blocks (edit by block index; the document has ${blocks.length} blocks):\n${blocks.map((value, index) => `[${index}] ${value || "(empty)"}`).join("\n") || "(empty document)"}`,
      `Selected papers:\n${papers.rows.map((p) => JSON.stringify(p)).join("\n")}`,
      "Return JSON only with a top-level notebook_update. Express the change as minimal block operations against the indexed blocks:",
      `- {"op":"append","index":null,"count":null,"markdown":"..."} adds blocks at the end`,
      `- {"op":"insert","index":N,"count":null,"markdown":"..."} inserts before block N`,
      `- {"op":"replace","index":N,"count":C,"markdown":"..."} replaces blocks N..N+C-1`,
      `- {"op":"delete","index":N,"count":C,"markdown":null} removes blocks`,
      "Never rewrite blocks you are not changing. Use refs for source_item ids you relied on.",
      `notebook_update.section_key must be "${sectionKey}".`,
    ].join("\n\n");
    const run = await new PgRunRepository(this.db).createQueuedRunWithBudgetAdmission({
      agent_id: resolved.agentId, space_id: identity.spaceId, user_id: identity.userId, project_id: projectId,
      mode: "live", run_type: "agent", trigger_origin: "manual", runtime_profile_id: resolved.runtimeProfileId,
      prompt, instruction, capability_id: "research.adhoc_analyze", capabilities_json: ["research.adhoc_analyze"],
      contract_snapshot: { source: { kind: "direct", id: notebook.id }, project_id: projectId, policy_context_json: createManagedExecutionPolicy("project_research", true), workflow_input_json: { research_adhoc: { notebook_id: notebook.id, section_key: sectionKey, base_version: baseVersion, source_item_ids: paperIds } }, structured_output_json: ADHOC_OUTPUT_CONTRACT },
    });
    const job = await new PgJobQueueRepository(this.db).enqueue({ job_type: "agent_run", space_id: identity.spaceId, user_id: identity.userId, agent_id: resolved.agentId, payload: { run_id: run.id } });
    return { run_id: run.id, job_id: job.id, status: run.status, daily_limit: RESEARCH_ADHOC_DAILY_RUN_LIMIT, daily_used: used + 1 };
  }

  /**
   * Terminal callback for ad-hoc runs (invoked by the research reconciler).
   * Applies the run's block ops directly to the notebook; when the section
   * moved past the run's base version, the change degrades to a clearly
   * labeled append so the user's request is never silently dropped.
   */
  async applyAdhocRunOutput(spaceId: string, runId: string): Promise<void> {
    const run = await this.db.query<{ project_id: string | null; status: string; output_json: unknown; contract_snapshot_json: unknown }>(
      `SELECT project_id,status,output_json,contract_snapshot_json FROM runs WHERE id=$1 AND space_id=$2`,
      [runId, spaceId],
    );
    const row = run.rows[0];
    if (!row?.project_id || !["succeeded", "degraded"].includes(row.status)) return;
    const contract = objectValue(objectValue(objectValue(row.contract_snapshot_json).workflow_input_json).research_adhoc);
    const sectionKey = optionalString(contract.section_key); const baseVersion = Number(contract.base_version);
    if (!sectionKey || !NOTEBOOK_SECTION_KEYS.includes(sectionKey as SectionKey) || !Number.isInteger(baseVersion)) return;
    const applied = await this.db.query(`SELECT 1 FROM research_notebook_section_revisions WHERE created_by_run_id=$1 LIMIT 1`, [runId]);
    if (applied.rows[0]) return;
    const update = objectValue(objectValue(row.output_json).notebook_update);
    const rawOps: unknown[] = Array.isArray(update.ops) ? update.ops : [];
    if (optionalString(update.section_key) !== sectionKey || rawOps.length === 0) {
      throw new Error("Ad-hoc research run output does not contain a valid notebook_update for the contracted section");
    }
    const refs = Array.isArray(update.refs) ? update.refs.filter((v): v is string => typeof v === "string").slice(0, 50) : [];
    const projectId = row.project_id;
    await withQueryableTransaction(this.db, async (db) => {
      const section = await db.query<{ version: number; content_json: Record<string, unknown> }>(
        `SELECT s.version,s.content_json FROM research_notebook_sections s JOIN research_notebooks n ON n.id=s.notebook_id
          WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key=$3 FOR UPDATE OF s`,
        [spaceId, projectId, sectionKey],
      );
      if (!section.rows[0]) return;
      if (section.rows[0].version === baseVersion) {
        const ops = parseNotebookOps(rawOps, pmBlocksText(section.rows[0].content_json).length);
        await writeNotebookSection(db, {
          spaceId, projectId, sectionKey,
          expectVersion: baseVersion,
          content: { kind: "ops", ops },
          source: "ai_adhoc", runId, refs,
          diff: { ops, base_version: baseVersion },
        });
        return;
      }
      const markdown = rawOps
        .map((value) => optionalString(objectValue(value).markdown))
        .filter((value): value is string => Boolean(value))
        .join("\n\n");
      if (!markdown) return;
      const fallback: NotebookOp[] = [{ op: "append", markdown: `## AI update (section changed since v${baseVersion})\n\n${markdown}` }];
      await writeNotebookSection(db, {
        spaceId, projectId, sectionKey,
        content: { kind: "ops", ops: fallback },
        source: "ai_adhoc", runId, refs,
        diff: { ops: fallback, base_version: baseVersion, conflict: true },
      });
    });
  }

  async seedFromReport(input: { spaceId: string; projectId: string; runId: string; report: Record<string, unknown> }) {
    return withQueryableTransaction(this.db, async (db) => {
      const service = new ProjectResearchWorkspaceService(db); const notebook = await service.ensureNotebook(input.spaceId, input.projectId);
      const sections: Record<SectionKey, string> = {
        understanding: [text(input.report.summary, 20_000), ...arrayObjects(input.report.findings).map((v) => `- ${text(v.title, 1000) || text(v.claim, 1000)} ${text(v.detail, 4000)}`)].filter(Boolean).join("\n\n"),
        questions: arrayStrings(input.report.limitations).map((v) => `- ${v}`).join("\n"),
        ideas: arrayObjects(input.report.ideas).map((v) => `- ${text(v.title, 1000) || text(v.idea, 1000)} ${text(v.detail, 4000)}`).join("\n"), experiments: "",
      };
      const reportRefs = collectSourceItemRefs(input.report);
      for (const key of NOTEBOOK_SECTION_KEYS) {
        const current = await db.query<{ version: number; normalized_text: string }>(`SELECT version,normalized_text FROM research_notebook_sections WHERE notebook_id=$1 AND section_key=$2`, [notebook.id, key]);
        if (current.rows[0]?.version !== 1 || current.rows[0].normalized_text !== "") continue;
        const markdown = sections[key]; if (!markdown) continue;
        await writeNotebookSection(db, {
          spaceId: input.spaceId, projectId: input.projectId, sectionKey: key,
          expectVersion: 1,
          content: { kind: "doc", doc: markdownToPm(markdown) },
          source: "seed", runId: input.runId, refs: reportRefs,
        });
      }
      const actions = [
        ...arrayObjects(input.report.ideas).map((idea) => text(idea.title, 1000) || text(idea.idea, 1000) || text(idea.detail, 2000)),
        ...arrayStrings(input.report.limitations).map((limitation) => `Resolve limitation: ${limitation}`),
      ].filter(Boolean);
      if (actions.length) {
        const existing = await db.query(`SELECT 1 FROM research_checklist_items WHERE space_id=$1 AND project_id=$2 AND origin_run_id=$3 LIMIT 1`, [input.spaceId, input.projectId, input.runId]);
        if (!existing.rows[0]) {
          const now = new Date().toISOString();
          for (const item of actions) {
            await db.query(
              `INSERT INTO research_checklist_items (id,space_id,project_id,text,status,sort_order,origin,origin_run_id,created_at,updated_at)
               SELECT $1::varchar,$2::varchar,$3::varchar,$4::text,'open',COALESCE(max(sort_order)+1,0),'agent',$5::varchar,$6::timestamptz,$6::timestamptz FROM research_checklist_items WHERE space_id=$2::varchar AND project_id=$3::varchar`,
              [randomUUID(), input.spaceId, input.projectId, item.slice(0, 2000), input.runId, now],
            );
          }
        }
      }
      return notebook;
    });
  }

  async materializePaperCardsFromDeepAnalysis(input: { spaceId: string; projectId: string; runId: string; promptHash?: string | null; summaries: Array<{ source_item_id: string; summary_markdown: string }> }): Promise<number> {
    const now = new Date().toISOString();
    let written = 0;
    const creator = await this.db.query<{ model_provider_id: string | null; model_override_json: unknown }>(`SELECT model_provider_id,model_override_json FROM runs WHERE id=$1 AND space_id=$2`, [input.runId, input.spaceId]);
    const runProvenance = creator.rows[0];
    for (const summary of input.summaries) {
      const parts = paperCardParts(summary.summary_markdown);
      // User-edited cards are never overwritten by generation; the user's
      // interpretation wins until they clear it themselves.
      const result = await this.db.query(
        `INSERT INTO research_paper_cards (id,space_id,project_id,source_item_id,object_id,why_md,how_md,what_md,provenance_json,edited_by_user,created_at,updated_at)
         SELECT $1::varchar,$2::varchar,$3::varchar,$4::varchar,pci.object_id,$5::text,$6::text,$7::text,$8::jsonb,false,$9::timestamptz,$9::timestamptz FROM project_corpus_items pci
          WHERE pci.space_id=$2::varchar AND pci.project_id=$3::varchar AND pci.source_item_id=$4::varchar AND pci.status='active'
            AND pci.triage_status IN ('relevant','maybe','included') LIMIT 1
         ON CONFLICT (project_id,source_item_id) DO UPDATE SET why_md=EXCLUDED.why_md,how_md=EXCLUDED.how_md,what_md=EXCLUDED.what_md,provenance_json=EXCLUDED.provenance_json,updated_at=EXCLUDED.updated_at
         WHERE research_paper_cards.edited_by_user=false
         RETURNING id`,
        [randomUUID(), input.spaceId, input.projectId, summary.source_item_id, parts.why, parts.how, parts.what,
          JSON.stringify({ run_id: input.runId, model_provider_id: runProvenance?.model_provider_id ?? null, model: optionalString(objectValue(runProvenance?.model_override_json).model), prompt_hash: input.promptHash ?? null, generated_from: "deep_analysis" }), now],
      );
      if (result.rows[0]) written += 1;
    }
    return written;
  }

  private async adhocRunsUsedToday(spaceId: string, projectId: string): Promise<number> {
    const result = await this.db.query<{ used: number }>(
      `SELECT count(*)::int AS used FROM runs
        WHERE space_id=$1 AND project_id=$2 AND capability_id='research.adhoc_analyze'
          AND created_at >= date_trunc('day', now())`,
      [spaceId, projectId],
    );
    return result.rows[0]?.used ?? 0;
  }

  private async ensureNotebook(spaceId: string, projectId: string): Promise<{ id: string; space_id: string; project_id: string; created_at: string; updated_at: string }> {
    const current = await this.db.query<any>(`SELECT * FROM research_notebooks WHERE space_id=$1 AND project_id=$2`, [spaceId, projectId]);
    if (current.rows[0]) return current.rows[0];
    const id = randomUUID(); const now = new Date().toISOString(); const empty = markdownToPm("");
    await this.db.query(`INSERT INTO research_notebooks (id,space_id,project_id,created_at,updated_at) VALUES ($1,$2,$3,$4,$4) ON CONFLICT (project_id,space_id) DO NOTHING`, [id, spaceId, projectId, now]);
    const found = await this.db.query<any>(`SELECT * FROM research_notebooks WHERE space_id=$1 AND project_id=$2`, [spaceId, projectId]); const notebook = found.rows[0];
    for (const key of NOTEBOOK_SECTION_KEYS) {
      const sectionId = randomUUID();
      const inserted = await this.db.query(`INSERT INTO research_notebook_sections (id,notebook_id,section_key,content_json,normalized_text,content_hash,version,updated_at) VALUES ($1,$2,$3,$4::jsonb,'',$5,1,$6) ON CONFLICT (notebook_id,section_key) DO NOTHING RETURNING id`, [sectionId, notebook.id, key, JSON.stringify(empty), sha256(""), now]);
      if (inserted.rows[0]) await insertInitialRevision(this.db, { sectionId, doc: empty, at: now });
    }
    return notebook;
  }
}

function assertSectionKey(value: string): asserts value is SectionKey { if (!NOTEBOOK_SECTION_KEYS.includes(value as SectionKey)) throw new HttpError(422, "invalid notebook section"); }
function text(value: unknown, max: number): string { return typeof value === "string" ? value.trim().slice(0, max) : ""; }
function arrayStrings(value: unknown): string[] { return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []; }
function arrayObjects(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(objectValue) : []; }
function collectSourceItemRefs(value: unknown, refs = new Set<string>()): string[] {
  if (Array.isArray(value)) for (const item of value) collectSourceItemRefs(item, refs);
  else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>; const id = optionalString(record.source_item_id); if (id) refs.add(id);
    for (const child of Object.values(record)) collectSourceItemRefs(child, refs);
  }
  return [...refs];
}
function paperCardParts(markdown: string): { why: string; how: string; what: string } {
  const take = (label: string) => markdown.match(new RegExp(`(?:^|\\n)#{0,3}\\s*${label}\\s*:?\\s*([^\\n]+(?:\\n(?!#{0,3}\\s*(?:WHY|HOW|WHAT)\\b)[^\\n]+)*)`, "i"))?.[1]?.trim().slice(0, 4000) ?? "";
  const why = clipWords(take("WHY"), 80); const how = clipWords(take("HOW"), 80); const what = clipWords(take("WHAT"), 80);
  return { why, how, what: what || (!why && !how ? clipWords(markdown.trim(), 80) : "") };
}
function clipWords(value: string, limit: number): string { return value.split(/\s+/).filter(Boolean).slice(0, limit).join(" "); }
