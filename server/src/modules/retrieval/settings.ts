import { randomUUID } from "node:crypto";
import type {
  ContextOpsReviewMode,
  ContextOpsScanMode,
  RetrievalCalibrationMechanic,
  RetrievalRuntimeRankingConfig,
  RetrievalSearchMode,
  RetrievalToolMode,
  SpaceRetrievalSettingsUpdate,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { Queryable } from "../routeUtils/common";
import { RetrievalEmbeddingStore } from "./embeddingStore";
import { DEFAULT_EMBED_DIMENSIONS } from "../retrievalEmbedding/config";

export interface SpaceRetrievalSettingsOut {
  space_id: string;
  default_search_mode: RetrievalSearchMode;
  rerank_enabled: boolean;
  query_rewrite_enabled: boolean;
  query_rewrite_default: boolean;
  use_query_cache: boolean;
  include_trace: boolean;
  external_egress_enabled: boolean;
  retrieval_tool_mode: RetrievalToolMode;
  context_ops_review_mode: ContextOpsReviewMode;
  context_ops_scan_mode: ContextOpsScanMode;
  embedding_dimensions: number;
  max_results_default: number;
  ranking_config: RetrievalRuntimeRankingConfig;
  created_at: string;
  updated_at: string;
}

export interface ResolvedSpaceRetrievalSettings {
  defaultSearchMode: RetrievalSearchMode;
  rerankEnabled: boolean;
  queryRewriteEnabled: boolean;
  queryRewriteDefault: boolean;
  useQueryCache: boolean;
  includeTrace: boolean;
  externalEgressEnabled: boolean;
  retrievalToolMode: RetrievalToolMode;
  contextOpsReviewMode: ContextOpsReviewMode;
  contextOpsScanMode: ContextOpsScanMode;
  embeddingDimensions: number;
  maxResultsDefault: number;
  rankingConfig: RetrievalRuntimeRankingConfig;
}

export interface ResolvedRetrievalSearchControls {
  mode: RetrievalSearchMode;
  rewrite: boolean;
  useCache: boolean;
  includeTrace: boolean;
  adaptiveReturn: boolean;
  maxResults: number;
  rankingConfig: RetrievalRuntimeRankingConfig;
}

export interface RetrievalControlRequest {
  mode?: RetrievalSearchMode;
  rewrite?: boolean;
  use_cache?: boolean;
  include_trace?: boolean;
  adaptive_return?: boolean;
  max_results?: number;
}

interface SpaceRetrievalSettingsRow {
  space_id: string;
  default_search_mode: RetrievalSearchMode;
  rerank_enabled: boolean;
  query_rewrite_enabled: boolean;
  query_rewrite_default: boolean;
  use_query_cache: boolean;
  include_trace: boolean;
  external_egress_enabled: boolean;
  retrieval_tool_mode: RetrievalToolMode;
  context_ops_review_mode: ContextOpsReviewMode;
  context_ops_scan_mode: ContextOpsScanMode;
  embedding_dimensions: number | string;
  max_results_default: number | string;
  ranking_config_json: unknown;
  created_at: Date | string;
  updated_at: Date | string;
}

type ShippableRetrievalMechanic = Exclude<RetrievalCalibrationMechanic, "semantic_results_cache">;

const SHIPPABLE_RETRIEVAL_MECHANICS: readonly ShippableRetrievalMechanic[] = [
  "visible_edge_backlink",
  "candidate_owned_salience",
  "richer_dedup",
  "autocut",
];

const ALL_RETRIEVAL_MECHANICS: readonly RetrievalCalibrationMechanic[] = [
  ...SHIPPABLE_RETRIEVAL_MECHANICS,
  "semantic_results_cache",
];

type RuntimeMechanicConfig = RetrievalRuntimeRankingConfig["mechanics"][RetrievalCalibrationMechanic];

export const DEFAULT_RETRIEVAL_RANKING_CONFIG: RetrievalRuntimeRankingConfig = {
  version: 1,
  eval_gate: {
    min_primary_metric_delta: 0,
    required_evidence_artifacts: 1,
  },
  mechanics: {
    visible_edge_backlink: defaultRuntimeMechanic(),
    candidate_owned_salience: defaultRuntimeMechanic(),
    richer_dedup: defaultRuntimeMechanic(),
    autocut: defaultRuntimeMechanic(),
    semantic_results_cache: defaultRuntimeMechanic(),
  },
};

export const DEFAULT_SPACE_RETRIEVAL_SETTINGS: ResolvedSpaceRetrievalSettings = {
  defaultSearchMode: "hybrid",
  rerankEnabled: false,
  queryRewriteEnabled: false,
  queryRewriteDefault: false,
  useQueryCache: true,
  includeTrace: false,
  externalEgressEnabled: true,
  retrievalToolMode: "off",
  contextOpsReviewMode: "private_only",
  contextOpsScanMode: "admins",
  embeddingDimensions: DEFAULT_EMBED_DIMENSIONS,
  maxResultsDefault: 50,
  rankingConfig: DEFAULT_RETRIEVAL_RANKING_CONFIG,
};

export async function readSpaceRetrievalSettings(
  db: Queryable,
  spaceId: string,
): Promise<ResolvedSpaceRetrievalSettings> {
  const row = await selectSettingsRow(db, spaceId);
  return row ? resolvedFromRow(row) : { ...DEFAULT_SPACE_RETRIEVAL_SETTINGS };
}

export async function getOrCreateSpaceRetrievalSettings(
  db: Queryable,
  spaceId: string,
): Promise<SpaceRetrievalSettingsOut> {
  await db.query(
    `INSERT INTO space_retrieval_settings (
        id, space_id, default_search_mode, rerank_enabled,
        query_rewrite_enabled, query_rewrite_default, use_query_cache,
        include_trace, external_egress_enabled, retrieval_tool_mode, context_ops_review_mode, context_ops_scan_mode,
        embedding_dimensions, max_results_default, ranking_config_json, created_at, updated_at
      )
      VALUES ($1, $2, 'hybrid', false, false, false, true, false, true, 'off', 'private_only', 'admins', $3, 50, $4::jsonb, now(), now())
      ON CONFLICT (space_id) DO NOTHING`,
    [randomUUID(), spaceId, DEFAULT_EMBED_DIMENSIONS, JSON.stringify(DEFAULT_RETRIEVAL_RANKING_CONFIG)],
  );
  const row = await selectSettingsRow(db, spaceId);
  if (!row) throw new Error("space retrieval settings row was not created");
  return outFromRow(row);
}

export async function updateSpaceRetrievalSettings(
  db: Queryable,
  spaceId: string,
  patch: SpaceRetrievalSettingsUpdate,
  options: { actorUserId?: string | null } = {},
): Promise<SpaceRetrievalSettingsOut> {
  await getOrCreateSpaceRetrievalSettings(db, spaceId);
  const current = await selectSettingsRow(db, spaceId);
  if (!current) throw new Error("space retrieval settings row was not found");
  const next = {
    defaultSearchMode: patch.default_search_mode ?? current.default_search_mode,
    rerankEnabled: patch.rerank_enabled ?? current.rerank_enabled,
    queryRewriteEnabled: patch.query_rewrite_enabled ?? current.query_rewrite_enabled,
    queryRewriteDefault: patch.query_rewrite_default ?? current.query_rewrite_default,
    useQueryCache: patch.use_query_cache ?? current.use_query_cache,
    includeTrace: patch.include_trace ?? current.include_trace,
    externalEgressEnabled: patch.external_egress_enabled ?? current.external_egress_enabled,
    retrievalToolMode: patch.retrieval_tool_mode ?? current.retrieval_tool_mode,
    contextOpsReviewMode: patch.context_ops_review_mode ?? current.context_ops_review_mode,
    contextOpsScanMode: patch.context_ops_scan_mode ?? current.context_ops_scan_mode,
    embeddingDimensions: patch.embedding_dimensions ?? Number(current.embedding_dimensions),
    maxResultsDefault: patch.max_results_default ?? Number(current.max_results_default),
    rankingConfig: await normalizeRankingConfigForUpdate(
      db,
      spaceId,
      patch.ranking_config ?? current.ranking_config_json,
      options.actorUserId ?? null,
    ),
  };
  const updated = await db.query<SpaceRetrievalSettingsRow>(
    `UPDATE space_retrieval_settings
        SET default_search_mode = $2,
            rerank_enabled = $3,
            query_rewrite_enabled = $4,
            query_rewrite_default = $5,
            use_query_cache = $6,
            include_trace = $7,
            external_egress_enabled = $8,
            retrieval_tool_mode = $9,
            context_ops_review_mode = $10,
            context_ops_scan_mode = $11,
            embedding_dimensions = $12,
            max_results_default = $13,
            ranking_config_json = $14::jsonb,
            updated_at = now()
      WHERE space_id = $1
      RETURNING space_id, default_search_mode, rerank_enabled,
                query_rewrite_enabled, query_rewrite_default, use_query_cache,
                include_trace, external_egress_enabled, retrieval_tool_mode,
                context_ops_review_mode, context_ops_scan_mode, embedding_dimensions, max_results_default,
                ranking_config_json, created_at, updated_at`,
    [
      spaceId,
      next.defaultSearchMode,
      next.rerankEnabled,
      next.queryRewriteEnabled,
      next.queryRewriteDefault,
      next.useQueryCache,
      next.includeTrace,
      next.externalEgressEnabled,
      next.retrievalToolMode,
      next.contextOpsReviewMode,
      next.contextOpsScanMode,
      next.embeddingDimensions,
      next.maxResultsDefault,
      JSON.stringify(next.rankingConfig),
    ],
  );
  if (next.embeddingDimensions !== Number(current.embedding_dimensions)) {
    await new RetrievalEmbeddingStore(db).resetEmbeddingsForSpace(spaceId);
  }
  return outFromRow(updated.rows[0]!);
}

export function resolveRetrievalSearchControls(
  request: RetrievalControlRequest,
  settings: ResolvedSpaceRetrievalSettings,
): ResolvedRetrievalSearchControls {
  return {
    mode: request.mode ?? settings.defaultSearchMode,
    rewrite: request.rewrite ?? settings.queryRewriteDefault,
    useCache: request.use_cache ?? settings.useQueryCache,
    includeTrace: request.include_trace ?? settings.includeTrace,
    adaptiveReturn: request.adaptive_return ?? isRetrievalMechanicShipped(settings.rankingConfig, "autocut"),
    maxResults: request.max_results ?? settings.maxResultsDefault,
    rankingConfig: settings.rankingConfig,
  };
}

async function selectSettingsRow(
  db: Queryable,
  spaceId: string,
): Promise<SpaceRetrievalSettingsRow | null> {
  const result = await db.query<SpaceRetrievalSettingsRow>(
    `SELECT space_id, default_search_mode, rerank_enabled,
            query_rewrite_enabled, query_rewrite_default, use_query_cache,
            include_trace, external_egress_enabled, retrieval_tool_mode,
            context_ops_review_mode, context_ops_scan_mode, embedding_dimensions, max_results_default,
            ranking_config_json, created_at, updated_at
       FROM space_retrieval_settings
      WHERE space_id = $1
      LIMIT 1`,
    [spaceId],
  );
  return result.rows[0] ?? null;
}

function resolvedFromRow(row: SpaceRetrievalSettingsRow): ResolvedSpaceRetrievalSettings {
  return {
    defaultSearchMode: row.default_search_mode,
    rerankEnabled: row.rerank_enabled,
    queryRewriteEnabled: row.query_rewrite_enabled,
    queryRewriteDefault: row.query_rewrite_default,
    useQueryCache: row.use_query_cache,
    includeTrace: row.include_trace,
    externalEgressEnabled: row.external_egress_enabled,
    retrievalToolMode: row.retrieval_tool_mode,
    contextOpsReviewMode: row.context_ops_review_mode,
    contextOpsScanMode: row.context_ops_scan_mode,
    embeddingDimensions: Number(row.embedding_dimensions),
    maxResultsDefault: Number(row.max_results_default),
    rankingConfig: normalizeRuntimeRankingConfig(row.ranking_config_json),
  };
}

function outFromRow(row: SpaceRetrievalSettingsRow): SpaceRetrievalSettingsOut {
  return {
    space_id: row.space_id,
    default_search_mode: row.default_search_mode,
    rerank_enabled: row.rerank_enabled,
    query_rewrite_enabled: row.query_rewrite_enabled,
    query_rewrite_default: row.query_rewrite_default,
    use_query_cache: row.use_query_cache,
    include_trace: row.include_trace,
    external_egress_enabled: row.external_egress_enabled,
    retrieval_tool_mode: row.retrieval_tool_mode,
    context_ops_review_mode: row.context_ops_review_mode,
    context_ops_scan_mode: row.context_ops_scan_mode,
    embedding_dimensions: Number(row.embedding_dimensions),
    max_results_default: Number(row.max_results_default),
    ranking_config: normalizeRuntimeRankingConfig(row.ranking_config_json),
    created_at: asIso(row.created_at),
    updated_at: asIso(row.updated_at),
  };
}

export function normalizeRuntimeRankingConfig(value: unknown): RetrievalRuntimeRankingConfig {
  const root = record(value);
  const gate = record(root.eval_gate);
  const mechanics = record(root.mechanics);
  const normalized: RetrievalRuntimeRankingConfig = {
    version: 1,
    eval_gate: {
      min_primary_metric_delta: finiteNumber(gate.min_primary_metric_delta) ?? 0,
      required_evidence_artifacts: Math.max(0, Math.min(12, intValue(gate.required_evidence_artifacts, 1))),
    },
    mechanics: {
      visible_edge_backlink: normalizeMechanic(mechanics.visible_edge_backlink),
      candidate_owned_salience: normalizeMechanic(mechanics.candidate_owned_salience),
      richer_dedup: normalizeMechanic(mechanics.richer_dedup),
      autocut: normalizeMechanic(mechanics.autocut),
      semantic_results_cache: { ...normalizeMechanic(mechanics.semantic_results_cache), state: "disabled" },
    },
  };
  return normalized;
}

export function isRetrievalMechanicShipped(
  config: RetrievalRuntimeRankingConfig,
  mechanic: ShippableRetrievalMechanic,
): boolean {
  return normalizeRuntimeRankingConfig(config).mechanics[mechanic].state === "shipped";
}

async function normalizeRankingConfigForUpdate(
  db: Queryable,
  spaceId: string,
  value: unknown,
  _actorUserId: string | null,
): Promise<RetrievalRuntimeRankingConfig> {
  const normalized = normalizeRuntimeRankingConfig(value);
  const checkedAt = new Date().toISOString();
  for (const mechanic of ALL_RETRIEVAL_MECHANICS) {
    const config = normalized.mechanics[mechanic];
    if (mechanic === "semantic_results_cache") {
      config.state = "disabled";
      config.calibration_artifact_id = null;
      config.shipped_at = null;
      config.eval_gate = { status: "failed", metric: null, value: null, threshold: normalized.eval_gate.min_primary_metric_delta, checked_at: checkedAt };
      continue;
    }
    if (config.state === "disabled") {
      config.shipped_at = null;
      if (!config.calibration_artifact_id) config.eval_gate = defaultRuntimeMechanic().eval_gate;
      continue;
    }
    if (!config.calibration_artifact_id) {
      throw new SpaceRetrievalSettingsError(`${mechanic} requires calibration_artifact_id before it can be ${config.state}`);
    }
    const gate = await evaluateCalibrationGate(db, {
      spaceId,
      mechanic,
      calibrationArtifactId: config.calibration_artifact_id,
      minDelta: normalized.eval_gate.min_primary_metric_delta,
      requiredEvidence: normalized.eval_gate.required_evidence_artifacts,
      checkedAt,
    });
    config.eval_gate = gate;
    if (config.state === "shipped") {
      if (gate.status !== "passed") {
        throw new SpaceRetrievalSettingsError(`${mechanic} cannot ship until its calibration eval gate passes`);
      }
      config.shipped_at = config.shipped_at ?? checkedAt;
    } else {
      config.shipped_at = null;
    }
  }
  return normalized;
}

async function evaluateCalibrationGate(
  db: Queryable,
  input: {
    spaceId: string;
    mechanic: ShippableRetrievalMechanic;
    calibrationArtifactId: string;
    minDelta: number;
    requiredEvidence: number;
    checkedAt: string;
  },
): Promise<RuntimeMechanicConfig["eval_gate"]> {
  const result = await db.query<{ metadata_json: unknown }>(
    `SELECT metadata_json
       FROM artifacts
      WHERE space_id = $1
        AND id = $2
        AND artifact_type = 'retrieval_calibration_decision'
        AND visibility = 'space_shared'
      LIMIT 1`,
    [input.spaceId, input.calibrationArtifactId],
  );
  const row = result.rows[0];
  if (!row) {
    throw new SpaceRetrievalSettingsError("calibration artifact not found or not visible");
  }
  const metadata = record(row.metadata_json);
  const decision = arrayValue(metadata.decisions)
    .map(record)
    .find((item) =>
      stringValue(item.mechanic) === input.mechanic &&
      stringValue(item.decision) === "adopt"
    );
  if (!decision) {
    throw new SpaceRetrievalSettingsError(`${input.mechanic} requires an adopted calibration decision`);
  }
  const evidenceCount = arrayValue(decision.evidence_artifact_ids).filter((id) => typeof id === "string" && id.trim()).length;
  const evalDelta = record(decision.eval_delta);
  const { metric, value } = bestEvalDelta(evalDelta);
  const passed = evidenceCount >= input.requiredEvidence && value !== null && value >= input.minDelta;
  return {
    status: passed ? "passed" : "failed",
    metric,
    value,
    threshold: input.minDelta,
    checked_at: input.checkedAt,
  };
}

function bestEvalDelta(values: Record<string, unknown>): { metric: string | null; value: number | null } {
  let bestMetric: string | null = null;
  let bestValue: number | null = null;
  for (const [key, raw] of Object.entries(values)) {
    const value = finiteNumber(raw);
    if (value === null) continue;
    if (bestValue === null || value > bestValue) {
      bestMetric = key;
      bestValue = value;
    }
  }
  return { metric: bestMetric, value: bestValue };
}

function defaultRuntimeMechanic(): RuntimeMechanicConfig {
  return {
    state: "disabled",
    calibration_artifact_id: null,
    shipped_at: null,
    eval_gate: {
      status: "not_run",
      metric: null,
      value: null,
      threshold: 0,
      checked_at: null,
    },
  };
}

function normalizeMechanic(value: unknown): RuntimeMechanicConfig {
  const item = record(value);
  const state = stringValue(item.state);
  const gate = record(item.eval_gate);
  return {
    state: state === "adopted" || state === "shipped" ? state : "disabled",
    calibration_artifact_id: stringValue(item.calibration_artifact_id),
    shipped_at: isoOrNull(item.shipped_at),
    eval_gate: {
      status: ["passed", "failed", "not_run"].includes(stringValue(gate.status) ?? "")
        ? stringValue(gate.status) as "passed" | "failed" | "not_run"
        : "not_run",
      metric: stringValue(gate.metric),
      value: finiteNumber(gate.value),
      threshold: finiteNumber(gate.threshold) ?? 0,
      checked_at: isoOrNull(gate.checked_at),
    },
  };
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function intValue(value: unknown, fallback: number): number {
  const numeric = finiteNumber(value);
  return numeric === null ? fallback : Math.trunc(numeric);
}

function isoOrNull(value: unknown): string | null {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "string" && value.trim() && !Number.isNaN(Date.parse(value))) {
    return new Date(value).toISOString();
  }
  return null;
}

export class SpaceRetrievalSettingsError extends Error {
  constructor(message: string, readonly statusCode = 422) {
    super(message);
    this.name = "SpaceRetrievalSettingsError";
  }
}

function asIso(value: Date | string): string {
  if (value instanceof Date) return value.toISOString();
  return new Date(value).toISOString();
}
