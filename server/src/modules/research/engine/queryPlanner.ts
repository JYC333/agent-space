import type { ServerConfig } from "../../../config";
import { HttpError, objectValue, optionalString, type Queryable, type SpaceUserIdentity } from "../../routeUtils/common";
import { resolvePrompt } from "../../prompts/resolver";
import { resolveProviderCommandStore } from "../../providers/commands/store";
import { completeProviderMessages } from "../../providers/invocation/invocation";
import { RESEARCH_PROVIDER_KEYS, type ResearchProviderKey, type ResearchQueryPlan } from "./types";

export const RESEARCH_ENGINE_QUERY_PLAN_PROMPT_KEY = "research_engine.query_plan";

export class ResearchQueryPlanner {
  constructor(private readonly db: Queryable, private readonly config: ServerConfig) {}

  async plan(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<ResearchQueryPlan> {
    const question = optionalString(body.question);
    if (!question) throw new HttpError(422, "question is required");
    if (question.length > 2000) throw new HttpError(422, "question must be at most 2000 characters");
    const scope = objectValue(body.scope);
    const execution = objectValue(body.execution);
    const providerId = optionalString(execution.model_provider_id);
    if (!providerId) return heuristicPlan(question, scope);
    const resolved = await resolvePrompt(this.db, {
      spaceId: identity.spaceId, userId: identity.userId, assetKey: RESEARCH_ENGINE_QUERY_PLAN_PROMPT_KEY,
      variables: { research_question: question, research_scope: JSON.stringify(scope) },
    });
    if (resolved.validation_errors.length || !resolved.rendered_text) throw new HttpError(500, "Research query planning prompt is not resolvable");
    const response = await completeProviderMessages(resolveProviderCommandStore(this.config), identity.spaceId, {
      provider_id: providerId,
      model: optionalString(execution.model_name),
      system: resolved.rendered_text,
      messages: [{ role: "user", content: "Create the bounded multi-provider search plan." }],
      max_tokens: 1400,
      task: "research_engine_query_plan",
      output_format: QUERY_PLAN_OUTPUT_CONTRACT,
      metering: { subject_user_id: identity.userId, source_type: "local_run", execution_channel: "managed_api", task: "research_engine_query_plan" },
      egressPolicy: { externalEgressEnabled: true },
    });
    if (!response.structured_output) throw new HttpError(502, "Research query planner returned no structured output");
    return normalizePlan(question, scope, response.structured_output);
  }
}

function heuristicPlan(question: string, scope: Record<string, unknown>): ResearchQueryPlan {
  const inferredGeneral = /\b(current|latest|today|policy|regulation|market|industry|company|product|news)\b/i.test(question);
  const kind = optionalString(scope.kind) ?? (inferredGeneral ? "mixed" : "academic");
  const academic = kind !== "general";
  const includeWeb = kind !== "academic" || scope.include_web === true;
  const providers: ResearchQueryPlan["providers"] = [];
  if (academic) {
    providers.push(
      { provider_key: "arxiv", query: { search_query: question, max_results: 20, sort_by: "relevance", sort_order: "descending" }, rationale: "Preprints and recent technical work" },
      { provider_key: "openalex", query: { search: question, per_page: 20, sort: "publication_date:desc" }, rationale: "Broad scholarly coverage and DOI metadata" },
      { provider_key: "semantic_scholar", query: { query: question, limit: 20 }, rationale: "Relevance-ranked scholarly graph coverage" },
    );
  }
  if (includeWeb) providers.push({ provider_key: "web_search", query: { q: question, count: 10 }, rationale: "Non-academic and current web evidence" });
  return { question, scope, providers, filters: objectValue(scope.filters), time_window: timeWindow(scope) };
}

function normalizePlan(question: string, scope: Record<string, unknown>, value: Record<string, unknown>): ResearchQueryPlan {
  const providers = (Array.isArray(value.providers) ? value.providers : []).map((entry) => {
    const row = objectValue(entry); const key = optionalString(row.provider_key);
    if (!key || !RESEARCH_PROVIDER_KEYS.includes(key as ResearchProviderKey)) return null;
    return { provider_key: key as ResearchProviderKey, query: objectValue(row.query), rationale: optionalString(row.rationale) ?? "Planned by research engine" };
  }).filter((entry): entry is ResearchQueryPlan["providers"][number] => entry !== null);
  if (!providers.length) throw new HttpError(502, "Research query planner selected no supported providers");
  return { question, scope, providers: providers.slice(0, 4), filters: objectValue(value.filters), time_window: timeWindow(objectValue(value.time_window)) };
}

function timeWindow(value: Record<string, unknown>): ResearchQueryPlan["time_window"] {
  const from = optionalString(value.from); const to = optionalString(value.to); return from || to ? { from, to } : null;
}

const QUERY_PLAN_OUTPUT_CONTRACT = {
  type: "json_schema", schema_id: "research_engine.query_plan.v1", strict: true, stage: "query_planning",
  schema: { type: "object", properties: {
    providers: { type: "array", minItems: 1, maxItems: 4, items: { type: "object", properties: {
      provider_key: { enum: RESEARCH_PROVIDER_KEYS }, query: { type: "object" }, rationale: { type: "string" },
    }, required: ["provider_key", "query", "rationale"], additionalProperties: false } },
    filters: { type: "object" }, time_window: { type: "object", properties: { from: { anyOf: [{ type: "string" }, { type: "null" }] }, to: { anyOf: [{ type: "string" }, { type: "null" }] } }, required: ["from", "to"], additionalProperties: false },
  }, required: ["providers", "filters", "time_window"], additionalProperties: false },
} as const;
