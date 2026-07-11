import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import { withQueryableTransaction } from "../routeUtils/common";
import { consumeConnectionQuota } from "./sourceQuotaBucket";

interface PlanRow {
  status: string;
  source_connection_id: string;
  quota_policy_json: { window?: unknown; limit_count?: unknown };
}

interface SegmentRow {
  id: string;
  window_json: unknown;
}

interface ReconcileJobRow {
  id: string;
  status: string;
  items_created: number | null;
  items_updated: number | null;
  error_message: string | null;
}

export class SourceBackfillExecutionService {
  constructor(private readonly db: Queryable) {}

  async start(spaceId: string, planId: string, proposalId: string, strategy: unknown, quota: unknown) {
    return withQueryableTransaction(this.db, (db) =>
      new SourceBackfillExecutionService(db).startLocked(spaceId, planId, proposalId, strategy, quota),
    );
  }

  async executeNext(spaceId: string, planId: string) {
    return withQueryableTransaction(this.db, (db) => new SourceBackfillExecutionService(db).executeNextLocked(spaceId, planId));
  }

  async reconcile(spaceId: string, planId: string) {
    return withQueryableTransaction(this.db, (db) => new SourceBackfillExecutionService(db).reconcileLocked(spaceId, planId));
  }

  private async startLocked(spaceId: string, planId: string, proposalId: string, strategy: unknown, quota: unknown) {
    const updated = await this.db.query<{ id: string }>(
      `UPDATE source_backfill_plans
          SET status='approved', updated_at=$4
        WHERE id=$1 AND space_id=$2 AND proposal_id=$3 AND status='proposed'
          AND strategy_json=$5::jsonb AND quota_policy_json=$6::jsonb
        RETURNING id`,
      [planId, spaceId, proposalId, new Date().toISOString(), JSON.stringify(strategy), JSON.stringify(quota)],
    );
    if (!updated.rows[0]) throw new Error("Backfill plan is stale or does not match its proposal");
    return this.executeNextLocked(spaceId, planId);
  }

  private async executeNextLocked(spaceId: string, planId: string) {
    const planResult = await this.db.query<PlanRow>(`SELECT * FROM source_backfill_plans WHERE id=$1 AND space_id=$2 FOR UPDATE`, [planId, spaceId]);
    const plan = planResult.rows[0];
    if (!plan || !["approved", "running"].includes(plan.status)) return null;

    const segmentResult = await this.db.query<SegmentRow>(
      `SELECT * FROM source_backfill_segments
        WHERE plan_id=$1 AND space_id=$2 AND status='pending' AND (next_eligible_at IS NULL OR next_eligible_at<=now())
        ORDER BY seq LIMIT 1 FOR UPDATE SKIP LOCKED`,
      [planId, spaceId],
    );
    const segment = segmentResult.rows[0];
    if (!segment) {
      await this.finishIfDone(spaceId, planId);
      return null;
    }

    const quota = await consumeConnectionQuota(this.db, spaceId, plan.source_connection_id, plan.quota_policy_json);
    if (!quota.allowed) {
      await this.db.query(
        `UPDATE source_backfill_segments SET next_eligible_at=$3 WHERE id=$1 AND space_id=$2 AND status='pending'`,
        [segment.id, spaceId, quota.resetAt],
      );
      await this.db.query(
        `UPDATE source_backfill_plans SET status='paused', next_eligible_at=$3, updated_at=$4 WHERE id=$1 AND space_id=$2`,
        [planId, spaceId, quota.resetAt, new Date().toISOString()],
      );
      return { paused: true, next_eligible_at: quota.resetAt };
    }

    const now = new Date().toISOString();
    const jobId = randomUUID();
    await this.db.query(
      `INSERT INTO extraction_jobs (id, space_id, connection_id, job_type, status, metadata_json, created_at)
       VALUES ($1,$2,$3,'connection_scan','pending',$4::jsonb,$5)`,
      [jobId, spaceId, plan.source_connection_id, JSON.stringify({ source_backfill_plan_id: planId, source_backfill_segment_id: segment.id, window: segment.window_json }), now],
    );
    await this.db.query(
      `UPDATE source_backfill_segments SET status='running', next_eligible_at=NULL, attempt_count=attempt_count+1, extraction_job_id=$3 WHERE id=$1 AND space_id=$2`,
      [segment.id, spaceId, jobId],
    );
    await this.db.query(`UPDATE source_backfill_plans SET status='running', updated_at=$3 WHERE id=$1 AND space_id=$2`, [planId, spaceId, now]);
    return { job_id: jobId, segment_id: segment.id };
  }

  private async reconcileLocked(spaceId: string, planId: string) {
    const rows = await this.db.query<{ id: string } & ReconcileJobRow>(
      `SELECT s.id, j.status, j.items_created, j.items_updated, j.error_message
         FROM source_backfill_segments s JOIN extraction_jobs j ON j.id=s.extraction_job_id
        WHERE s.plan_id=$1 AND s.space_id=$2 AND s.status='running'`,
      [planId, spaceId],
    );
    for (const row of rows.rows) {
      if (row.status === "succeeded") {
        const itemsIngested = Number(row.items_created ?? 0) + Number(row.items_updated ?? 0);
        await this.db.query(`UPDATE source_backfill_segments SET status='succeeded', items_ingested=$3 WHERE id=$1 AND space_id=$2`, [row.id, spaceId, itemsIngested]);
      } else if (row.status === "failed") {
        await this.db.query(
          `UPDATE source_backfill_segments SET status='failed', error_json=$3::jsonb WHERE id=$1 AND space_id=$2`,
          [row.id, spaceId, JSON.stringify({ message: row.error_message })],
        );
      }
    }
    await this.refreshCounters(spaceId, planId);
    return this.executeNextLocked(spaceId, planId);
  }

  private async refreshCounters(spaceId: string, planId: string): Promise<void> {
    await this.db.query(
      `UPDATE source_backfill_plans p
          SET segments_completed = x.done, segments_failed = x.failed, items_ingested = x.items, updated_at = now()
         FROM (SELECT count(*) FILTER (WHERE status='succeeded')::int done,
                      count(*) FILTER (WHERE status='failed')::int failed,
                      coalesce(sum(items_ingested), 0)::int items
                 FROM source_backfill_segments
                WHERE plan_id=$1 AND space_id=$2) x
        WHERE p.id=$1 AND p.space_id=$2`,
      [planId, spaceId],
    );
  }

  private async finishIfDone(spaceId: string, planId: string): Promise<void> {
    await this.refreshCounters(spaceId, planId);
    await this.db.query(
      `UPDATE source_backfill_plans
          SET status = CASE WHEN segments_failed>0 THEN 'failed' ELSE 'completed' END, updated_at = now()
        WHERE id=$1 AND space_id=$2
          AND NOT EXISTS(SELECT 1 FROM source_backfill_segments WHERE plan_id=$1 AND space_id=$2 AND status IN ('pending','running'))`,
      [planId, spaceId],
    );
  }
}
