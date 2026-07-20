import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import { objectValue, optionalString, withQueryableTransaction } from "../routeUtils/common";
import { PgRunRepository } from "../runs/repository";
import { PgJobQueueRepository } from "../jobs/repository";
import { createManagedExecutionPolicy } from "../policy/managedExecutionPolicy";
import { writeNotebookSection } from "./notebookWriteService";
import type { NotebookOp } from "./notebookDocument";
import {
  PROJECT_RESEARCH_MONITOR_COMPARE_PROMPT_KEY,
  resolveProjectResearchMonitorComparePrompt,
} from "./promptRegistry";

export const MONITOR_COMPARISON_OUTPUT_CONTRACT = {
  type: "json_schema",
  schema_id: "project_research.monitor_compare.v1",
  strict: true,
  stage: "monitor_compare",
  schema: {
    type: "object",
    properties: {
      comparisons: {
        type: "array",
        items: {
          type: "object",
          properties: {
            source_item_id: { type: "string" },
            stance: { enum: ["supports", "contradicts", "new_direction"] },
            detail: { type: "string", minLength: 1, maxLength: 4000 },
            affected_sections: {
              type: "array",
              items: { enum: ["understanding", "questions", "ideas", "experiments"] },
              uniqueItems: true,
            },
          },
          required: ["source_item_id", "stance", "detail", "affected_sections"],
          additionalProperties: false,
        },
      },
    },
    required: ["comparisons"],
    additionalProperties: false,
  },
} as const;

export type MonitorComparison = {
  source_item_id: string;
  stance: "supports" | "contradicts" | "new_direction";
  detail: string;
  affected_sections: Array<"understanding" | "questions" | "ideas" | "experiments">;
};

export class ProjectResearchMonitorComparisonService {
  constructor(private readonly db: Queryable) {}

  async queue(input: {
    spaceId: string;
    userId: string;
    projectId: string;
    workflowId: string;
    operationId: string;
    agentId: string;
    runtimeProfileId: string | null;
    researchQuestion: string;
    sourceItemIds: string[];
  }): Promise<{ runId: string; jobId: string; sourceItemIds: string[] } | null> {
    const papers = await this.eligiblePapers(input.spaceId, input.projectId, input.sourceItemIds);
    if (papers.length === 0) return null;
    const understanding = await this.db.query<{ normalized_text: string }>(
      `SELECT s.normalized_text FROM research_notebook_sections s
        JOIN research_notebooks n ON n.id=s.notebook_id
       WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key='understanding'`,
      [input.spaceId, input.projectId],
    );
    const resolved = await resolveProjectResearchMonitorComparePrompt(this.db, {
      spaceId: input.spaceId,
      userId: input.userId,
      projectId: input.projectId,
      agentId: input.agentId,
      researchQuestion: input.researchQuestion,
      currentUnderstanding: understanding.rows[0]?.normalized_text ?? "",
      newPapers: papers,
    });
    const run = await new PgRunRepository(this.db).createQueuedRunWithBudgetAdmission({
      agent_id: input.agentId,
      space_id: input.spaceId,
      user_id: input.userId,
      project_id: input.projectId,
      mode: "live",
      run_type: "agent",
      trigger_origin: "system",
      runtime_profile_id: input.runtimeProfileId,
      prompt: `Compare ${papers.length} newly screened paper${papers.length === 1 ? "" : "s"} with the current research understanding`,
      instruction: resolved.instruction,
      capability_id: "research.monitor_compare",
      capabilities_json: ["research.monitor_compare"],
      contract_snapshot: {
        source: { kind: "workflow", id: input.workflowId },
        project_id: input.projectId,
        required_outputs_json: { materializations: ["research_scan_summary", "research_paper_card"] },
        structured_output_json: MONITOR_COMPARISON_OUTPUT_CONTRACT,
        workflow_input_json: {
          project_research: {
            workflow_id: input.workflowId,
            operation_id: input.operationId,
            stage_key: "monitor_compare",
            source_item_ids: papers.map((paper) => paper.source_item_id),
            prompt_asset_key: PROJECT_RESEARCH_MONITOR_COMPARE_PROMPT_KEY,
            prompt_version_id: resolved.resolveResult.version_id,
            prompt_content_hash: resolved.resolveResult.content_hash,
          },
        },
        policy_context_json: createManagedExecutionPolicy("project_research", true),
        risk_level: "low",
      },
    });
    const job = await new PgJobQueueRepository(this.db).enqueue({
      job_type: "agent_run",
      space_id: input.spaceId,
      user_id: input.userId,
      agent_id: input.agentId,
      payload: { run_id: run.id },
    });
    return { runId: run.id, jobId: job.id, sourceItemIds: papers.map((paper) => paper.source_item_id) };
  }

  async materialize(input: {
    spaceId: string;
    projectId: string;
    workflowId: string;
    operationId: string;
    runId: string;
    output: unknown;
    expectedSourceItemIds: string[];
  }): Promise<{ comparisons: MonitorComparison[]; notebookVersion: number | null }> {
    const comparisons = parseMonitorComparisons(input.output, input.expectedSourceItemIds);
    return withQueryableTransaction(this.db, async (db) => {
      const now = new Date().toISOString();
      const scan = await db.query<{ comparisons_json: unknown }>(
        `SELECT comparisons_json FROM research_scan_summaries
          WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3 AND operation_id=$4
          FOR UPDATE`,
        [input.spaceId, input.projectId, input.workflowId, input.operationId],
      );
      if (!scan.rows[0]) throw new Error("Monitoring comparison has no scan summary to update");
      if (Array.isArray(scan.rows[0].comparisons_json) && scan.rows[0].comparisons_json.length > 0) {
        const existing = await db.query<{ version: number }>(
          `SELECT r.version FROM research_notebook_section_revisions r
            WHERE r.created_by_run_id=$1 OR r.diff_json->>'run_id'=$1
            ORDER BY r.version DESC LIMIT 1`,
          [input.runId],
        );
        return { comparisons: parseMonitorComparisons({ comparisons: scan.rows[0].comparisons_json }, input.expectedSourceItemIds), notebookVersion: existing.rows[0]?.version ?? null };
      }
      for (const comparison of comparisons) {
        await db.query(
          `INSERT INTO research_paper_cards (
             id,space_id,project_id,source_item_id,object_id,why_md,how_md,what_md,
             provenance_json,edited_by_user,stance,comparison_detail,created_at,updated_at
           ) SELECT $1::varchar,$2::varchar,$3::varchar,$4::varchar,pci.object_id,'','','',$5::jsonb,false,$6::varchar,$7::text,$8::timestamptz,$8::timestamptz
               FROM project_corpus_items pci
               JOIN project_corpus_item_sources pcis ON pcis.corpus_item_id=pci.id AND pcis.space_id=pci.space_id
               JOIN source_items si ON si.id=pcis.source_item_id AND si.space_id=pcis.space_id AND si.deleted_at IS NULL
              WHERE pci.space_id=$2::varchar AND pci.project_id=$3::varchar AND pcis.source_item_id=$4::varchar AND pci.status='active'
              LIMIT 1
           ON CONFLICT (space_id,project_id,source_item_id) DO UPDATE SET
             stance=EXCLUDED.stance,comparison_detail=EXCLUDED.comparison_detail,
             provenance_json=research_paper_cards.provenance_json || EXCLUDED.provenance_json,
             updated_at=EXCLUDED.updated_at`,
          [randomUUID(), input.spaceId, input.projectId, comparison.source_item_id,
            JSON.stringify({ comparison_run_id: input.runId }), comparison.stance, comparison.detail, now],
        );
      }
      const counts = stanceCounts(comparisons);
      await db.query(
        `UPDATE research_scan_summaries SET supports_count=$5,contradicts_count=$6,
           new_direction_count=$7,comparisons_json=$8::jsonb
         WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3 AND operation_id=$4`,
        [input.spaceId, input.projectId, input.workflowId, input.operationId,
          counts.supports, counts.contradicts, counts.new_direction, JSON.stringify(comparisons)],
      );
      const disruptive = comparisons.filter((item) => item.stance !== "supports");
      if (disruptive.length === 0) return { comparisons, notebookVersion: null };
      const section = await db.query(
        `SELECT 1 FROM research_notebook_sections s JOIN research_notebooks n ON n.id=s.notebook_id
          WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key='understanding'`,
        [input.spaceId, input.projectId],
      );
      if (!section.rows[0]) return { comparisons, notebookVersion: null };
      const additions = disruptive.map((item) =>
        `- **${item.stance === "contradicts" ? "Contradiction" : "New direction"}** (${item.source_item_id}): ${item.detail}`,
      ).join("\n");
      // Direct co-edit (revised D2): monitoring appends a labeled block to the
      // understanding section; existing blocks stay untouched and the write is
      // recorded as a revision the user can roll back.
      const ops: NotebookOp[] = [{ op: "append", markdown: `## Monitoring update — ${now.slice(0, 10)}\n\n${additions}` }];
      const run = await db.query(`SELECT 1 FROM runs WHERE id=$1 AND space_id=$2`, [input.runId, input.spaceId]);
      const written = await writeNotebookSection(db, {
        spaceId: input.spaceId,
        projectId: input.projectId,
        sectionKey: "understanding",
        content: { kind: "ops", ops },
        source: "ai_monitoring",
        runId: run.rows[0] ? input.runId : null,
        refs: disruptive.map((item) => item.source_item_id),
        diff: { ops, run_id: input.runId },
      });
      return { comparisons, notebookVersion: written.outcome === "written" ? written.section.version : null };
    });
  }

  private async eligiblePapers(spaceId: string, projectId: string, sourceItemIds: string[]) {
    if (sourceItemIds.length === 0) return [];
    const rows = await this.db.query<{
      source_item_id: string; title: string | null; excerpt: string | null;
      why_md: string | null; how_md: string | null; what_md: string | null;
    }>(
      `SELECT DISTINCT ON (pcis.source_item_id) pcis.source_item_id,left(si.title,1000) AS title,left(si.excerpt,4000) AS excerpt,
              left(pc.why_md,2000) AS why_md,left(pc.how_md,2000) AS how_md,left(pc.what_md,2000) AS what_md
         FROM project_corpus_items pci
         JOIN project_corpus_item_sources pcis ON pcis.corpus_item_id=pci.id AND pcis.space_id=pci.space_id
         JOIN source_items si ON si.id=pcis.source_item_id AND si.space_id=pcis.space_id AND si.deleted_at IS NULL
         LEFT JOIN research_paper_cards pc ON pc.space_id=pci.space_id AND pc.project_id=pci.project_id AND pc.source_item_id=pcis.source_item_id
        WHERE pci.space_id=$1 AND pci.project_id=$2 AND pcis.source_item_id=ANY($3::text[])
          AND pci.status='active' AND (pci.triage_status IN ('relevant','included','maybe') OR pci.relevance IN ('relevant','maybe'))
        ORDER BY pcis.source_item_id,pci.updated_at DESC`,
      [spaceId, projectId, sourceItemIds],
    );
    return rows.rows;
  }
}

export function parseMonitorComparisons(output: unknown, expectedSourceItemIds: string[]): MonitorComparison[] {
  const expected = new Set(expectedSourceItemIds);
  const values = objectValue(output).comparisons;
  if (!Array.isArray(values)) throw new Error("Monitoring comparison output is missing comparisons");
  const result: MonitorComparison[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const value = objectValue(raw);
    const sourceItemId = optionalString(value.source_item_id);
    const stance = optionalString(value.stance);
    const detail = optionalString(value.detail);
    const rawAffected = value.affected_sections;
    const affected = Array.isArray(rawAffected)
      ? [...new Set(rawAffected.filter((item: unknown): item is MonitorComparison["affected_sections"][number] =>
        typeof item === "string" && ["understanding", "questions", "ideas", "experiments"].includes(item)))]
      : [];
    if (!sourceItemId || !expected.has(sourceItemId) || seen.has(sourceItemId)) throw new Error("Monitoring comparison returned an unexpected or duplicate source_item_id");
    if (!detail || detail.length > 4000 || !["supports", "contradicts", "new_direction"].includes(stance ?? "") || !Array.isArray(rawAffected) || affected.length !== rawAffected.length) throw new Error(`Monitoring comparison for ${sourceItemId} is invalid`);
    seen.add(sourceItemId);
    result.push({ source_item_id: sourceItemId, stance: stance as MonitorComparison["stance"], detail, affected_sections: affected });
  }
  if (seen.size !== expected.size) throw new Error("Monitoring comparison did not classify every supplied paper");
  return result;
}

function stanceCounts(values: MonitorComparison[]) {
  return {
    supports: values.filter((item) => item.stance === "supports").length,
    contradicts: values.filter((item) => item.stance === "contradicts").length,
    new_direction: values.filter((item) => item.stance === "new_direction").length,
  };
}
