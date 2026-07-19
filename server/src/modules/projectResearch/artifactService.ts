import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import { objectValue } from "../routeUtils/common";

interface MatrixRow {
  id: string;
  object_id: string | null;
  source_item_id: string | null;
  evidence_id: string | null;
  title: string | null;
  source_external_id: string | null;
  occurred_at: string | null;
  triage_status: string;
  relevance: string | null;
  confidence: number | null;
  role: string;
  reason: string | null;
  source_metadata: unknown;
  evidence_title: string | null;
  evidence_excerpt: string | null;
}

/**
 * Materializes deterministic Project Research read artifacts from the
 * approved corpus. The agent-generated synthesis archive remains owned by the
 * normal RunMaterializationService; this service only owns derived matrices.
 */
export class ProjectResearchArtifactService {
  constructor(private readonly db: Queryable) {}

  async ensureLiteratureMatrix(input: {
    spaceId: string;
    projectId: string;
    workflowId: string;
    operationId: string;
    ownerUserId: string;
  }): Promise<string> {
    const existing = await this.db.query<{ id: string }>(
      `SELECT id
         FROM artifacts
        WHERE space_id=$1 AND project_id=$2 AND artifact_type='literature_matrix'
          AND metadata_json->>'project_research_operation_id'=$3
        ORDER BY created_at DESC
        LIMIT 1`,
      [input.spaceId, input.projectId, input.operationId],
    );
    if (existing.rows[0]) return existing.rows[0].id;

    const rows = await this.db.query<MatrixRow>(
      `SELECT pci.id, pci.object_id, pci.source_item_id, pci.evidence_id,
              si.title, si.source_external_id, si.occurred_at,
              pci.triage_status, pci.relevance, pci.confidence, pci.role,
              pci.reason, si.metadata_json AS source_metadata,
              ee.title AS evidence_title, ee.content_excerpt AS evidence_excerpt
         FROM project_corpus_items pci
         LEFT JOIN source_items si
           ON si.id=pci.source_item_id AND si.space_id=pci.space_id
         LEFT JOIN extracted_evidence ee
           ON ee.id=pci.evidence_id AND ee.space_id=pci.space_id
        WHERE pci.space_id=$1 AND pci.project_id=$2 AND pci.status='active'
          AND pci.triage_status <> 'excluded'
        ORDER BY COALESCE(si.occurred_at, pci.created_at) DESC, pci.id`,
      [input.spaceId, input.projectId],
    );

    const content = JSON.stringify({
      schema_version: "literature_matrix.v1",
      project_id: input.projectId,
      workflow_id: input.workflowId,
      operation_id: input.operationId,
      generated_at: new Date().toISOString(),
      rows: rows.rows.map((row) => ({
        corpus_item_id: row.id,
        title: row.title ?? row.evidence_title ?? "Untitled source",
        source_external_id: row.source_external_id,
        occurred_at: row.occurred_at,
        triage_status: row.triage_status,
        relevance: row.relevance,
        confidence: row.confidence,
        role: row.role,
        reason: row.reason,
        evidence_excerpt: row.evidence_excerpt,
        source_metadata: objectValue(row.source_metadata),
        references: [citationReference(row)].filter(Boolean),
      })),
    });
    const artifactId = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, project_id, artifact_type, surface_role, title, content, mime_type,
         exportable, export_formats_json, canonical_format, preview,
         created_at, updated_at, metadata_json, visibility, owner_user_id, trust_level
       ) VALUES (
         $1,$2,$3,'literature_matrix','operational',$4,$5,'application/json',
         true,$6::jsonb,'json',false,$7,$7,$8::jsonb,'space_shared',$9,'medium'
       )`,
      [
        artifactId,
        input.spaceId,
        input.projectId,
        `Literature Matrix (${new Date().toISOString()})`,
        content,
        JSON.stringify(["json"]),
        now,
        JSON.stringify({
          schema_version: "literature_matrix.v1",
          project_research_operation_id: input.operationId,
          project_research_workflow_id: input.workflowId,
        }),
        input.ownerUserId,
      ],
    );
    return artifactId;
  }
}

function citationReference(row: MatrixRow): Record<string, string> | null {
  if (row.source_item_id) return { source_item_id: row.source_item_id };
  if (row.evidence_id) return { evidence_id: row.evidence_id };
  if (row.object_id) return { object_id: row.object_id };
  return null;
}
