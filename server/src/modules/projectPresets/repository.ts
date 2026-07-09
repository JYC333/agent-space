import type { Queryable } from "../routeUtils/common";

export class ProjectPresetsRepository {
  constructor(private readonly db: Queryable) {}

  async getProjectPresetKey(spaceId: string, projectId: string): Promise<{ preset_key: string | null } | null> {
    const result = await this.db.query<{ preset_key: string | null }>(
      `SELECT CASE
                WHEN jsonb_typeof(settings_json->'preset') = 'string' THEN settings_json->>'preset'
                ELSE NULL
              END AS preset_key
         FROM projects
        WHERE id = $2 AND space_id = $1 AND deleted_at IS NULL
        LIMIT 1`,
      [spaceId, projectId],
    );
    return result.rows[0] ?? null;
  }
}
