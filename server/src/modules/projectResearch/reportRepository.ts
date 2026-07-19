import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import { HttpError, dateIso, objectValue } from "../routeUtils/common";
import { assertProjectReadable } from "../projects/access";
import { resolveResearchReportReferences } from "./reportReferenceResolver";

interface ReportRow {
  id: string; project_id: string; workflow_id: string; operation_id: string; synthesis_run_id: string;
  run_kind: string; research_question: string; research_question_version: number; status: string;
  content_json: unknown; reader_document_json: unknown; normalized_text: string; content_hash: string;
  archive_artifact_id: string; literature_matrix_artifact_id: string | null; integrity_artifact_id: string | null;
  created_at: unknown; updated_at: unknown;
}

const COLUMNS = `id,project_id,workflow_id,operation_id,synthesis_run_id,run_kind,research_question,
  research_question_version,status,content_json,reader_document_json,normalized_text,content_hash,
  archive_artifact_id,literature_matrix_artifact_id,integrity_artifact_id,created_at,updated_at`;

export class ProjectResearchReportRepository {
  constructor(private readonly db: Queryable) {}

  async list(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const rows = await this.db.query<ReportRow>(
      `SELECT ${COLUMNS} FROM project_research_reports WHERE space_id=$1 AND project_id=$2 ORDER BY created_at DESC,id DESC`,
      [identity.spaceId, projectId],
    );
    return rows.rows.map((row) => reportOut(row, false));
  }

  async get(identity: SpaceUserIdentity, projectId: string, reportId: string): Promise<Record<string, unknown>> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const rows = await this.db.query<ReportRow>(
      `SELECT ${COLUMNS} FROM project_research_reports WHERE id=$1 AND space_id=$2 AND project_id=$3`,
      [reportId, identity.spaceId, projectId],
    );
    if (!rows.rows[0]) throw new HttpError(404, "Research report not found or not accessible");
    const row = rows.rows[0];
    const profile = await this.db.query<{ research_question: string | null }>(
      `SELECT research_question FROM project_research_profiles WHERE space_id=$1 AND project_id=$2 LIMIT 1`,
      [identity.spaceId, projectId],
    );
    const references = await resolveResearchReportReferences(this.db, identity, objectValue(row.content_json));
    return {
      ...reportOut(row, true),
      current_research_question: profile.rows[0]?.research_question ?? null,
      content: references.content,
      resolved_references: references.resolved,
    };
  }
}

function reportOut(row: ReportRow, detail: boolean): Record<string, unknown> {
  return {
    id: row.id, project_id: row.project_id, workflow_id: row.workflow_id, operation_id: row.operation_id,
    synthesis_run_id: row.synthesis_run_id, run_kind: row.run_kind, research_question: row.research_question,
    research_question_version: row.research_question_version, status: row.status,
    created_at: dateIso(row.created_at), updated_at: dateIso(row.updated_at),
    ...(detail ? {
      content: objectValue(row.content_json), reader_document: objectValue(row.reader_document_json),
      normalized_text: row.normalized_text, content_hash: row.content_hash,
      integrity: { artifact_id: row.integrity_artifact_id, status: row.integrity_artifact_id ? "available" : "not_run" },
      provenance: { workflow_id: row.workflow_id, operation_id: row.operation_id, synthesis_run_id: row.synthesis_run_id },
      archive_descriptors: [
        { kind: "archive", artifact_id: row.archive_artifact_id },
        ...(row.literature_matrix_artifact_id ? [{ kind: "literature_matrix", artifact_id: row.literature_matrix_artifact_id }] : []),
        ...(row.integrity_artifact_id ? [{ kind: "integrity", artifact_id: row.integrity_artifact_id }] : []),
      ],
    } : {}),
  };
}
