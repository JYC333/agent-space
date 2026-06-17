import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import type { SpaceUserIdentity } from "../routeUtils/common";
import { TRUST_BY_SOURCE_TYPE } from "./repository";

interface ActivityRow {
  id: string;
  space_id: string;
  user_id: string | null;
  owner_user_id: string | null;
  subject_user_id: string | null;
  workspace_id: string | null;
  project_id: string | null;
  activity_type: string;
  title: string | null;
  content: string | null;
  source_trust: string | null;
  source_url: string | null;
  consolidation_status: string;
  status: string;
}

const ACTIVITY_COLUMNS = `
  id, space_id, user_id, owner_user_id, subject_user_id, workspace_id, project_id,
  activity_type, title, content, source_trust, source_url, consolidation_status, status
`;

export class PgActivityConsolidationRepository {
  constructor(private readonly db: Queryable) {}

  async runPending(input: {
    spaceId: string;
    actingUserId: string;
    batchLimit: number;
    activityIds: string[] | null;
  }): Promise<Record<string, unknown>> {
    const runId = randomUUID();
    const proposalsCreated: string[] = [];
    const activitiesProcessed: string[] = [];
    const activitiesSkipped: string[] = [];
    const activitiesFailed: string[] = [];

    const params: unknown[] = [input.spaceId];
    let idFilter = "";
    if (input.activityIds?.length) {
      params.push(input.activityIds);
      idFilter = `AND id::text = ANY($${params.length}::text[])`;
    }
    params.push(input.batchLimit);
    const result = await this.db.query<ActivityRow>(
      `SELECT ${ACTIVITY_COLUMNS}
         FROM activity_records
        WHERE space_id = $1
          AND consolidation_status = 'pending'
          ${idFilter}
        ORDER BY created_at ASC
        LIMIT $${params.length}`,
      params,
    );

    const identity: SpaceUserIdentity = {
      spaceId: input.spaceId,
      userId: input.actingUserId,
    };

    for (const activity of result.rows) {
      try {
        const content = (activity.content ?? "").trim();
        if (!content) {
          await this.markConsolidation(activity.id, input.spaceId, "skipped");
          activitiesSkipped.push(activity.id);
          continue;
        }
        const proposalId = await this.insertMemoryProposal(identity, activity);
        await this.markConsolidation(activity.id, input.spaceId, "proposals_generated");
        proposalsCreated.push(proposalId);
        activitiesProcessed.push(activity.id);
      } catch {
        activitiesFailed.push(activity.id);
        await this.markConsolidation(activity.id, input.spaceId, "failed");
      }
    }

    return {
      consolidation_run_id: runId,
      proposals_created: proposalsCreated,
      activities_processed: activitiesProcessed,
      activities_skipped: activitiesSkipped,
      activities_failed: activitiesFailed,
    };
  }

  private async markConsolidation(
    activityId: string,
    spaceId: string,
    consolidationStatus: string,
  ): Promise<void> {
    const now = new Date().toISOString();
    const status =
      consolidationStatus === "proposals_generated"
        ? "proposals_generated"
        : consolidationStatus === "skipped"
          ? "processed"
          : undefined;
    await this.db.query(
      `UPDATE activity_records
          SET consolidation_status = $3,
              processed_at = $4,
              status = COALESCE($5, status),
              updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [activityId, spaceId, consolidationStatus, now, status ?? null],
    );
  }

  private async insertMemoryProposal(
    identity: SpaceUserIdentity,
    activity: ActivityRow,
  ): Promise<string> {
    const proposalId = randomUUID();
    const now = new Date().toISOString();
    const payload = {
      operation: "create",
      proposed_content: activity.content ?? "",
      memory_type: "experience",
      target_scope: "user",
      target_namespace: "activity.consolidation",
      target_visibility: "private",
      owner_user_id: activity.owner_user_id ?? activity.user_id ?? identity.userId,
      subject_user_id: activity.subject_user_id ?? activity.user_id ?? identity.userId,
      source_activity_id: activity.id,
      activity_source_trust:
        activity.source_trust ?? TRUST_BY_SOURCE_TYPE[activity.activity_type] ?? "untrusted_external",
      provenance_entries: [
        {
          source_type: "activity",
          source_id: activity.id,
          source_trust:
            activity.source_trust ?? TRUST_BY_SOURCE_TYPE[activity.activity_type] ?? "untrusted_external",
          evidence_json: {
            activity_type: activity.activity_type,
            source_url: activity.source_url,
          },
        },
      ],
    };
    await this.db.query(
      `INSERT INTO proposals (
         id, space_id, proposal_type, status, title, rationale, payload_json,
         created_by_user_id, workspace_id, project_id, created_at, updated_at
       ) VALUES (
         $1, $2, 'memory_create', 'pending', $3, $4, $5::jsonb,
         $6, $7, $8, $9, $9
       )`,
      [
        proposalId,
        identity.spaceId,
        activity.title || `Activity: ${(activity.content ?? "").slice(0, 80)}`,
        "Activity consolidation generated a memory proposal.",
        JSON.stringify(payload),
        identity.userId,
        activity.workspace_id,
        activity.project_id,
        now,
      ],
    );
    return proposalId;
  }
}
