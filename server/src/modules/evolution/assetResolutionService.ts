import { HttpError, type Queryable } from "../routeUtils/common";

export interface ResolveEvolvableAssetVersionInput {
  spaceId: string;
  assetKey: string;
  assetType?: string | null;
  projectId?: string | null;
  userId?: string | null;
  agentId?: string | null;
  explicitVersionId?: string | null;
  /**
   * User pins never affect shared Project outputs unless a caller explicitly
   * opts into user-personal behavior. Defaults to false.
   */
  allowUserPin?: boolean;
}

export interface ResolvedEvolvableAssetVersion {
  assetId: string;
  versionId: string;
  contentRef: string | null;
  contentHash: string | null;
  contentJson: unknown;
  resolutionTrace: string[];
  fallbackReason: string | null;
}

interface VersionContentRow {
  id: string;
  content_ref: string | null;
  content_hash: string | null;
  content_json: unknown;
  status: string;
}

/**
 * Runtime resolution for evolvable prompt/workflow-template assets:
 * explicit approved override -> project pin -> agent pin -> user pin
 * (gated) -> space pin -> space approved version -> system baseline.
 * Every call returns a
 * resolution trace so Runs/workflow artifacts can record reproducibility
 * provenance.
 */
export async function resolveEvolvableAssetVersion(
  db: Queryable,
  input: ResolveEvolvableAssetVersionInput,
): Promise<ResolvedEvolvableAssetVersion> {
  const trace: string[] = [];
  const asset = await db.query<{ id: string; asset_type: string; current_system_version_id: string | null }>(
    `SELECT id, asset_type, current_system_version_id FROM evolvable_assets
      WHERE asset_key = $1 AND (space_id = $2 OR space_id IS NULL) AND status = 'active'
      ORDER BY space_id NULLS LAST
      LIMIT 1`,
    [input.assetKey, input.spaceId],
  );
  const assetRow = asset.rows[0];
  if (!assetRow) throw new HttpError(404, `No active evolvable asset registered for asset_key '${input.assetKey}'`);
  if (input.assetType && assetRow.asset_type !== input.assetType) {
    throw new HttpError(422, `asset_key '${input.assetKey}' is asset_type '${assetRow.asset_type}', not '${input.assetType}'`);
  }
  const assetId = assetRow.id;

  if (input.explicitVersionId) {
    const version = await versionContent(db, assetId, input.explicitVersionId, { approvedOnly: true });
    if (!version) {
      throw new HttpError(422, "explicit_version_id must reference an approved version of this asset");
    }
    trace.push(`explicit_override:${version.id}`);
    return resolved(assetId, version, trace, null);
  }

  if (input.projectId) {
    const pinned = await resolveViaPin(db, assetId, input.spaceId, "project", input.projectId, trace);
    if (pinned) return resolved(assetId, pinned, trace, null);
  }
  if (input.agentId) {
    const pinned = await resolveViaPin(db, assetId, input.spaceId, "agent", input.agentId, trace);
    if (pinned) return resolved(assetId, pinned, trace, null);
  }
  if (input.allowUserPin && input.userId) {
    const pinned = await resolveViaPin(db, assetId, input.spaceId, "user", input.userId, trace);
    if (pinned) return resolved(assetId, pinned, trace, null);
  }
  {
    const pinned = await resolveViaPin(db, assetId, input.spaceId, "space", input.spaceId, trace);
    if (pinned) return resolved(assetId, pinned, trace, null);
  }

  const spaceApproved = await db.query<VersionContentRow>(
    `SELECT id, content_ref, content_hash, content_json, status FROM evolvable_asset_versions
      WHERE asset_id = $1 AND scope_type = 'space' AND status = 'approved'
      ORDER BY version DESC LIMIT 1`,
    [assetId],
  );
  if (spaceApproved.rows[0]) {
    trace.push(`space_approved:${spaceApproved.rows[0].id}`);
    return resolved(assetId, spaceApproved.rows[0], trace, null);
  }

  if (assetRow.current_system_version_id) {
    const version = await versionContent(db, assetId, assetRow.current_system_version_id, { approvedOnly: true });
    if (version) {
      trace.push(`system_baseline:${version.id}`);
      return resolved(assetId, version, trace, "no project/agent/user pin or space-approved version; used current_system_version_id");
    }
  }
  const systemApproved = await db.query<VersionContentRow>(
    `SELECT id, content_ref, content_hash, content_json, status FROM evolvable_asset_versions
      WHERE asset_id = $1 AND scope_type = 'system' AND status = 'approved'
      ORDER BY version DESC LIMIT 1`,
    [assetId],
  );
  if (systemApproved.rows[0]) {
    trace.push(`system_baseline:${systemApproved.rows[0].id}`);
    return resolved(assetId, systemApproved.rows[0], trace, "no project/agent/user pin or space-approved version; used system baseline");
  }

  throw new HttpError(404, `No resolvable version for asset_key '${input.assetKey}' (no pin, space-approved, or system-baseline version)`);
}

async function resolveViaPin(
  db: Queryable,
  assetId: string,
  spaceId: string,
  scopeType: "project" | "agent" | "user" | "space",
  scopeId: string,
  trace: string[],
): Promise<VersionContentRow | null> {
  const pin = await db.query<{ version_id: string }>(
    `SELECT version_id FROM evolvable_asset_pins
      WHERE space_id = $1 AND asset_id = $2 AND scope_type = $3 AND scope_id = $4 AND status = 'active'
      LIMIT 1`,
    [spaceId, assetId, scopeType, scopeId],
  );
  const pinRow = pin.rows[0];
  if (!pinRow) return null;
  const version = await versionContent(db, assetId, pinRow.version_id, { approvedOnly: true });
  if (!version) {
    throw new HttpError(422, `Active ${scopeType} pin references a missing or non-approved asset version`);
  }
  trace.push(`${scopeType}_pin:${version.id}`);
  return version;
}

async function versionContent(
  db: Queryable,
  assetId: string,
  versionId: string,
  options: { approvedOnly?: boolean } = {},
): Promise<VersionContentRow | null> {
  const approvedClause = options.approvedOnly ? " AND status = 'approved'" : "";
  const result = await db.query<VersionContentRow>(
    `SELECT id, content_ref, content_hash, content_json, status FROM evolvable_asset_versions WHERE asset_id = $1 AND id = $2${approvedClause} LIMIT 1`,
    [assetId, versionId],
  );
  return result.rows[0] ?? null;
}

function resolved(
  assetId: string,
  version: VersionContentRow,
  trace: string[],
  fallbackReason: string | null,
): ResolvedEvolvableAssetVersion {
  return {
    assetId,
    versionId: version.id,
    contentRef: version.content_ref,
    contentHash: version.content_hash,
    contentJson: version.content_json ?? null,
    resolutionTrace: trace,
    fallbackReason,
  };
}
