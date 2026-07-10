import type {
  NormalizedUsageObservation,
  UsageBucketName,
  UsageDetails,
} from "./types";

export const PRICING_NORMALIZATION_VERSION = 1;

export interface PricingRuleRecord {
  id: string;
  scope_type: "system" | "instance" | "space" | string;
  space_id: string | null;
  provider_type: string | null;
  provider_id: string | null;
  model_pattern: string;
  input_usd_per_million: number | string | null;
  output_usd_per_million: number | string | null;
  cache_write_usd_per_million: number | string | null;
  cache_read_usd_per_million: number | string | null;
  reasoning_usd_per_million: number | string | null;
  usage_type_prices_json: Record<string, unknown>;
  tier_conditions_json: Record<string, unknown>;
  priority: number | string;
  pricing_normalization_version: number | string;
  currency: string;
  effective_from: string;
  effective_until: string | null;
  source: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UsageCostEstimate {
  estimatedCostUsd: number;
  currency: string;
  pricingRuleId: string;
  pricingTierName: string | null;
  costDetails: Record<string, unknown>;
}

interface PriceSet {
  input: number | null;
  output: number | null;
  cacheWrite: number | null;
  cacheRead: number | null;
  reasoning: number | null;
  usageTypePrices: Record<string, number>;
}

interface TierSelection {
  tierName: string | null;
  prices: PriceSet;
}

const BILLABLE_BUCKETS: UsageBucketName[] = [
  "input",
  "output",
  "input_cache_creation",
  "input_cache_read",
  "output_reasoning",
  "input_audio",
  "output_audio",
  "input_image",
  "output_image",
  "embedding_input",
];

export function estimateUsageCost(
  event: NormalizedUsageObservation,
  rule: PricingRuleRecord,
): UsageCostEstimate | null {
  const selection = selectTier(rule, event);
  const bucketCosts: Array<{
    bucket: string;
    units: number;
    usd_per_million: number;
    cost_usd: number;
  }> = [];

  for (const bucket of billableBuckets(event.usage_details_json)) {
    const units = nonNegativeNumber(event.usage_details_json[bucket]);
    if (!units) continue;
    const usdPerMillion = priceForBucket(bucket, selection.prices);
    if (usdPerMillion === null) continue;
    const costUsd = roundCost((units / 1_000_000) * usdPerMillion);
    bucketCosts.push({ bucket, units, usd_per_million: usdPerMillion, cost_usd: costUsd });
  }

  if (bucketCosts.length === 0) return null;

  const estimatedCostUsd = roundCost(bucketCosts.reduce((sum, item) => sum + item.cost_usd, 0));
  return {
    estimatedCostUsd,
    currency: rule.currency || "USD",
    pricingRuleId: rule.id,
    pricingTierName: selection.tierName,
    costDetails: {
      pricing_normalization_version: PRICING_NORMALIZATION_VERSION,
      rule_id: rule.id,
      tier_name: selection.tierName,
      currency: rule.currency || "USD",
      bucket_costs: bucketCosts,
    },
  };
}

export function modelPatternMatches(pattern: string, model: string | null | undefined): boolean {
  const normalizedPattern = pattern.trim().toLowerCase();
  const normalizedModel = (model ?? "").trim().toLowerCase();
  if (normalizedPattern === "*" || normalizedPattern === "") return true;
  if (!normalizedPattern.includes("*")) return normalizedPattern === normalizedModel;
  const escaped = normalizedPattern
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${escaped}$`).test(normalizedModel);
}

export function modelPatternSpecificity(pattern: string): number {
  return pattern.replaceAll("*", "").length;
}

function selectTier(rule: PricingRuleRecord, event: NormalizedUsageObservation): TierSelection {
  const base = basePrices(rule);
  const tiers = Array.isArray(rule.tier_conditions_json?.tiers)
    ? rule.tier_conditions_json.tiers
    : [];
  for (const tier of tiers) {
    const tierObject = objectValue(tier);
    if (!tierObject || !tierMatches(tierObject, event)) continue;
    return {
      tierName: stringValue(tierObject.name) ?? stringValue(tierObject.tier_name),
      prices: mergePrices(base, pricesFromObject(tierObject)),
    };
  }
  return {
    tierName: stringValue(rule.tier_conditions_json?.default_tier_name),
    prices: base,
  };
}

function tierMatches(tier: Record<string, unknown>, event: NormalizedUsageObservation): boolean {
  const when = objectValue(tier.when) ?? objectValue(tier.conditions);
  if (!when) return true;
  const providerType = stringValue(when.provider_type);
  if (providerType && providerType !== event.provider_type) return false;
  const providerId = stringValue(when.provider_id);
  if (providerId && providerId !== event.provider_id) return false;
  const modelPattern = stringValue(when.model_pattern) ?? stringValue(when.model);
  if (modelPattern && !modelPatternMatches(modelPattern, event.model)) return false;
  const dimensionEquals = objectValue(when.dimension_equals) ?? objectValue(when.dimensions);
  if (dimensionEquals) {
    for (const [key, expected] of Object.entries(dimensionEquals)) {
      if (String(event.dimensions_json[key] ?? "") !== String(expected)) return false;
    }
  }
  return true;
}

function basePrices(rule: PricingRuleRecord): PriceSet {
  return {
    input: numberOrNull(rule.input_usd_per_million),
    output: numberOrNull(rule.output_usd_per_million),
    cacheWrite: numberOrNull(rule.cache_write_usd_per_million),
    cacheRead: numberOrNull(rule.cache_read_usd_per_million),
    reasoning: numberOrNull(rule.reasoning_usd_per_million),
    usageTypePrices: numericMap(rule.usage_type_prices_json),
  };
}

function pricesFromObject(value: Record<string, unknown>): Partial<PriceSet> {
  const prices = objectValue(value.prices) ?? value;
  return {
    input: numberOrUndefined(prices.input_usd_per_million),
    output: numberOrUndefined(prices.output_usd_per_million),
    cacheWrite: numberOrUndefined(prices.cache_write_usd_per_million),
    cacheRead: numberOrUndefined(prices.cache_read_usd_per_million),
    reasoning: numberOrUndefined(prices.reasoning_usd_per_million),
    usageTypePrices: numericMap(
      objectValue(prices.usage_type_prices_json) ??
      objectValue(prices.usage_type_prices) ??
      {},
    ),
  };
}

function mergePrices(base: PriceSet, override: Partial<PriceSet>): PriceSet {
  return {
    input: override.input ?? base.input,
    output: override.output ?? base.output,
    cacheWrite: override.cacheWrite ?? base.cacheWrite,
    cacheRead: override.cacheRead ?? base.cacheRead,
    reasoning: override.reasoning ?? base.reasoning,
    usageTypePrices: { ...base.usageTypePrices, ...(override.usageTypePrices ?? {}) },
  };
}

function billableBuckets(details: UsageDetails): UsageBucketName[] {
  const buckets = BILLABLE_BUCKETS.filter((bucket) => nonNegativeNumber(details[bucket]) > 0);
  if (buckets.length === 0 && nonNegativeNumber(details.total) > 0) return ["total"];
  return buckets;
}

function priceForBucket(bucket: UsageBucketName, prices: PriceSet): number | null {
  const explicit = prices.usageTypePrices[bucket];
  if (explicit !== undefined) return explicit;
  switch (bucket) {
    case "input":
    case "embedding_input":
      return prices.input;
    case "output":
      return prices.output;
    case "input_cache_creation":
      return prices.cacheWrite;
    case "input_cache_read":
      return prices.cacheRead;
    case "output_reasoning":
      return prices.reasoning ?? prices.output;
    case "total":
      return prices.usageTypePrices.total ?? null;
    default:
      return null;
  }
}

function numericMap(value: Record<string, unknown> | undefined): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value ?? {})) {
    const number = numberOrNull(raw);
    if (number !== null) result[key] = number;
  }
  return result;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function numberOrUndefined(value: unknown): number | undefined {
  return numberOrNull(value) ?? undefined;
}

function nonNegativeNumber(value: unknown): number {
  const number = numberOrNull(value);
  return number ?? 0;
}

function roundCost(value: number): number {
  return Number(value.toFixed(8));
}
