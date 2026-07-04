import type { Queryable } from "../routeUtils/common";

/**
 * Commit the intake watermark proposed at fire time once the run succeeded.
 * Monotonic: only moves the cursor forward on the (created_at, id) tuple, so
 * duplicate finalizations and out-of-order run completions cannot regress it.
 * Called from the run finalization path; failed/cancelled runs never advance.
 *
 * Returns true when a cursor was advanced.
 */
export async function advanceAutomationIntakeCursor(
  db: Queryable,
  input: { spaceId: string; runId: string },
): Promise<boolean> {
  const result = await db.query(
    `UPDATE automations a
        SET cursor_json = jsonb_set(
              COALESCE(a.cursor_json, '{}'::jsonb),
              '{intake_watermark}',
              ar.trigger_context_json->'proposed_intake_watermark'
            ),
            updated_at = $3
       FROM automation_runs ar
      WHERE ar.run_id = $2
        AND ar.automation_id = a.id
        AND a.space_id = $1
        AND ar.trigger_context_json ? 'proposed_intake_watermark'
        AND (
          a.cursor_json->'intake_watermark' IS NULL
          OR (
            ar.trigger_context_json->'proposed_intake_watermark'->>'created_at',
            ar.trigger_context_json->'proposed_intake_watermark'->>'id'
          ) > (
            a.cursor_json->'intake_watermark'->>'created_at',
            a.cursor_json->'intake_watermark'->>'id'
          )
        )`,
    [input.spaceId, input.runId, new Date().toISOString()],
  );
  return (result.rowCount ?? 0) > 0;
}
