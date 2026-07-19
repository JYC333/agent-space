import { createHash, randomUUID } from "node:crypto";
import type { ServerConfig } from "../../../config";
import { HttpError, objectValue, optionalString, withQueryableTransaction, type Queryable, type SpaceUserIdentity } from "../../routeUtils/common";
import { assertProjectWriter } from "../../projects/access";
import { readSpaceRetrievalSettings } from "../../retrieval/settings";
import { SourceQueryPreviewService } from "../../sources/sourceQueryPreviewService";
import { SourceChannelService } from "../../sources/channels/sourceChannelService";
import { ProjectSourceBindingService } from "../../projects/projectSourceBindingService";
import { ResearchQueryPlanner } from "./queryPlanner";
import type { ResearchCandidate, ResearchProviderKey, ResearchQueryPlan } from "./types";

interface ResearchEngineDependencies {
  planner?: { plan(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<ResearchQueryPlan> };
  previews?: { preview(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<{ approximate_hit_count: number; samples: Record<string, unknown>[]; compiled_query?: unknown }> };
}

export class ResearchEngineService {
  constructor(private readonly db: Queryable, private readonly config: ServerConfig, private readonly dependencies: ResearchEngineDependencies = {}) {}

  async search(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const projectId = optionalString(body.project_id);
    const operationId = optionalString(body.operation_id);
    if (projectId) await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    if (operationId) await this.assertOperation(identity.spaceId, operationId, projectId);
    const plan = await (this.dependencies.planner ?? new ResearchQueryPlanner(this.db, this.config)).plan(identity, body);
    const credentials = objectValue(body.credentials);
    const strategyId = randomUUID(); const startedAt = new Date().toISOString();
    await this.db.query(
      `INSERT INTO research_search_strategies (id,space_id,project_id,operation_id,created_by_user_id,question,scope_json,providers_json,queries_json,filters_json,time_window_json,status,created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb,'running',$12)`,
      [strategyId, identity.spaceId, projectId, operationId, identity.userId, plan.question, JSON.stringify(plan.scope), JSON.stringify(plan.providers.map((p) => p.provider_key)), JSON.stringify(plan.providers), JSON.stringify(plan.filters), plan.time_window ? JSON.stringify(plan.time_window) : null, startedAt],
    );
    const settings = await readSpaceRetrievalSettings(this.db, identity.spaceId);
    const previews = this.dependencies.previews ?? new SourceQueryPreviewService(this.db, this.config);
    const settled = await Promise.all(plan.providers.map(async (provider) => {
      if (provider.provider_key === "web_search" && !settings.externalEgressEnabled) {
        throw new HttpError(403, "Web search is disabled by this space's external egress policy");
      }
      const credentialId = optionalString(credentials[provider.provider_key]);
      return previews.preview(identity, { provider_key: provider.provider_key, query: withWindow(provider.query, plan), ...(credentialId ? { credential_id: credentialId } : {}) });
    }).map((promise) => promise.then((value) => ({ status: "fulfilled" as const, value })).catch((reason) => ({ status: "rejected" as const, reason }))));
    const errors: Record<string, string> = {}; const hitCounts: Record<string, number> = {}; const candidates: ResearchCandidate[] = [];
    const suggestions: Array<Record<string, unknown>> = [];
    for (let i = 0; i < settled.length; i += 1) {
      const provider = plan.providers[i]!; const result = settled[i]!;
      if (result.status === "rejected") { errors[provider.provider_key] = errorMessage(result.reason); continue; }
      hitCounts[provider.provider_key] = Number(result.value.approximate_hit_count ?? 0);
      for (const sample of result.value.samples) candidates.push(candidateFromSample(provider.provider_key, sample));
      suggestions.push(monitorSuggestion(provider, result.value, optionalString(credentials[provider.provider_key])));
    }
    const merged = dedupeResearchCandidates(candidates);
    const status = Object.keys(errors).length === 0 ? "completed" : merged.length ? "partial" : "failed";
    const completedAt = new Date().toISOString();
    await this.db.query(
      `UPDATE research_search_strategies SET hit_counts_json=$3::jsonb,provider_errors_json=$4::jsonb,result_count=$5,status=$6,completed_at=$7 WHERE id=$1 AND space_id=$2`,
      [strategyId, identity.spaceId, JSON.stringify(hitCounts), JSON.stringify(errors), merged.length, status, completedAt],
    );
    return { strategy: { id: strategyId, status, question: plan.question, providers: plan.providers, filters: plan.filters, time_window: plan.time_window, hit_counts: hitCounts, provider_errors: errors, result_count: merged.length, created_at: startedAt, completed_at: completedAt }, candidates: merged, monitor_suggestions: suggestions };
  }

  async createSuggestedMonitors(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    return withQueryableTransaction(this.db, (db) => new ResearchEngineService(db, this.config, this.dependencies).createSuggestedMonitorsLocked(identity, body));
  }

  private async createSuggestedMonitorsLocked(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const strategyId = optionalString(body.strategy_id); const projectId = optionalString(body.project_id);
    if (!strategyId || !projectId) throw new HttpError(422, "strategy_id and project_id are required");
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const strategy = await this.db.query<{ queries_json: unknown; status: string }>(
      `SELECT queries_json,status FROM research_search_strategies WHERE id=$1 AND space_id=$2 AND created_by_user_id=$3 AND (project_id IS NULL OR project_id=$4) LIMIT 1`,
      [strategyId, identity.spaceId, identity.userId, projectId],
    );
    if (!strategy.rows[0] || !["completed", "partial"].includes(strategy.rows[0].status)) throw new HttpError(404, "Completed research search strategy not found");
    const selected = new Set((Array.isArray(body.provider_keys) ? body.provider_keys : []).filter((v): v is string => typeof v === "string"));
    const credentials = objectValue(body.credentials); const planned = Array.isArray(strategy.rows[0].queries_json) ? strategy.rows[0].queries_json : [];
    const channels = []; const bindings = [];
    for (const value of planned) {
      const provider = objectValue(value); const providerKey = optionalString(provider.provider_key);
      if (!providerKey || (selected.size && !selected.has(providerKey))) continue;
      const credentialId = optionalString(credentials[providerKey]);
      if (providerKey === "web_search" && !credentialId) throw new HttpError(422, "web_search requires a managed source credential");
      const channel = await new SourceChannelService(this.db, this.config).create(identity, {
        provider_key: providerKey, name: `${providerKey}: ${String(firstQueryText(objectValue(provider.query))).slice(0, 140)}`,
        query: objectValue(provider.query), fetch_frequency: "daily", capture_policy: "reference_only",
        trust_level: providerKey === "web_search" ? "untrusted" : "normal", ...(credentialId ? { credential_id: credentialId } : {}),
      });
      const binding = await new ProjectSourceBindingService(this.db).createBinding(identity, {
        project_id: projectId, source_channel_id: String(channel.id), binding_key: `research-engine:${providerKey}`,
        delivery_scope: "project_members", extraction_policy: { mode: "metadata_and_text", full_text: providerKey !== "web_search" }, routing_policy: { archive_non_matching: false },
      });
      channels.push(channel); bindings.push(binding);
    }
    if (!channels.length) throw new HttpError(422, "No suggested providers were selected");
    return { strategy_id: strategyId, channels, bindings };
  }

  private async assertOperation(spaceId: string, operationId: string, projectId: string | null) {
    const result = await this.db.query<{ project_id: string }>(`SELECT project_id FROM project_operations WHERE id=$1 AND space_id=$2 LIMIT 1`, [operationId, spaceId]);
    if (!result.rows[0] || (projectId && result.rows[0].project_id !== projectId)) throw new HttpError(404, "Research operation not found");
  }
}

function withWindow(query: Record<string, unknown>, plan: ResearchQueryPlan): Record<string, unknown> {
  if (!plan.time_window) return query;
  return { ...query, from_publication_date: plan.time_window.from, to_publication_date: plan.time_window.to };
}
function candidateFromSample(provider: ResearchProviderKey, sample: Record<string, unknown>): ResearchCandidate {
  const metadata = objectValue(sample.metadata); const title = optionalString(sample.title) ?? "Untitled result";
  const authors = Array.isArray(metadata.authors) ? metadata.authors.filter((v): v is string => typeof v === "string") : optionalString(sample.author)?.split(",").map((v) => v.trim()).filter(Boolean) ?? [];
  return { candidate_id: createHash("sha256").update(`${provider}\n${title}\n${optionalString(sample.source_uri) ?? ""}`).digest("hex").slice(0, 24),
    kind: provider === "web_search" ? "web_page" : "academic_paper", title, authors, occurred_at: optionalString(sample.occurred_at), source_uri: optionalString(sample.source_uri), excerpt: optionalString(sample.excerpt),
    doi: normalizeDoi(optionalString(metadata.doi)), arxiv_id: optionalString(metadata.arxiv_id), openalex_id: optionalString(metadata.openalex_id), semantic_scholar_id: optionalString(metadata.semantic_scholar_id),
    providers: [provider], trust_level: provider === "web_search" ? "untrusted" : "normal", metadata };
}
export function dedupeResearchCandidates(input: ResearchCandidate[]): ResearchCandidate[] {
  const merged: ResearchCandidate[] = [];
  for (const candidate of input) {
    const index = merged.findIndex((prior) => candidatesMatch(prior, candidate));
    if (index < 0) merged.push(candidate);
    else {
      const prior = merged[index]!;
      merged[index] = { ...prior, providers: [...new Set([...prior.providers, ...candidate.providers])], doi: prior.doi ?? candidate.doi, arxiv_id: prior.arxiv_id ?? candidate.arxiv_id, openalex_id: prior.openalex_id ?? candidate.openalex_id, semantic_scholar_id: prior.semantic_scholar_id ?? candidate.semantic_scholar_id, excerpt: prior.excerpt ?? candidate.excerpt, metadata: { ...candidate.metadata, ...prior.metadata } };
    }
  }
  return merged;
}
function candidatesMatch(left: ResearchCandidate, right: ResearchCandidate): boolean {
  if (left.doi && right.doi && left.doi === right.doi) return true;
  if (left.arxiv_id && right.arxiv_id && left.arxiv_id.toLowerCase() === right.arxiv_id.toLowerCase()) return true;
  if (left.openalex_id && right.openalex_id && left.openalex_id.toLowerCase() === right.openalex_id.toLowerCase()) return true;
  if (left.semantic_scholar_id && right.semantic_scholar_id && left.semantic_scholar_id.toLowerCase() === right.semantic_scholar_id.toLowerCase()) return true;
  const leftAuthor = normalizeTitle(left.authors[0] ?? ""); const rightAuthor = normalizeTitle(right.authors[0] ?? "");
  return Boolean(leftAuthor && leftAuthor === rightAuthor && titleSimilarity(left.title, right.title) >= 0.9);
}
function titleSimilarity(left: string, right: string): number {
  const a = new Set(normalizeTitle(left).split(" ").filter(Boolean)); const b = new Set(normalizeTitle(right).split(" ").filter(Boolean));
  if (!a.size || !b.size) return 0;
  const intersection = [...a].filter((token) => b.has(token)).length;
  return intersection / new Set([...a, ...b]).size;
}
function monitorSuggestion(provider: ResearchQueryPlan["providers"][number], preview: Record<string, unknown>, credentialId: string | null) {
  return { provider_key: provider.provider_key, rationale: provider.rationale, approximate_hit_count: preview.approximate_hit_count, samples: preview.samples,
    create_body: { provider_key: provider.provider_key, name: `${provider.provider_key}: ${String(preview.compiled_query).slice(0, 140)}`, query: provider.query, fetch_frequency: "daily", capture_policy: "reference_only", trust_level: provider.provider_key === "web_search" ? "untrusted" : "normal", ...(credentialId ? { credential_id: credentialId } : {}) } };
}
function normalizeDoi(value: string | null): string | null { return value?.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "").toLowerCase() ?? null; }
function normalizeTitle(value: string): string { return value.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, " ").trim(); }
function errorMessage(value: unknown): string { return value instanceof Error ? value.message.slice(0, 500) : String(value).slice(0, 500); }
function firstQueryText(query: Record<string, unknown>): string { return optionalString(query.search_query) ?? optionalString(query.search) ?? optionalString(query.query) ?? optionalString(query.q) ?? "search"; }
