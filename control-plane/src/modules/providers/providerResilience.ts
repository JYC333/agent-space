/**
 * Provider failure classification and retry/rotation decision vocabulary.
 */

export type ProviderFailureClass =
  | "rate_limit"
  | "payment_required"
  | "unauthorized"
  | "quota_exhausted"
  | "transient"
  | "permanent";

export type ProviderResilienceAction =
  | "retry_same_key_once"
  | "rotate_key"
  | "cooldown_24h"
  | "refresh_token"
  | "fallback_provider"
  | "fail";

export interface ProviderResilienceDecision {
  failure_class: ProviderFailureClass;
  actions: ProviderResilienceAction[];
  cooldown_seconds?: number;
}

export function classifyProviderFailure(statusCode: number, bodyText = ""): ProviderResilienceDecision {
  const body = bodyText.toLowerCase();
  if (statusCode === 429) {
    const quota = /quota|insufficient_quota|exceeded your current quota/.test(body);
    return quota
      ? { failure_class: "quota_exhausted", actions: ["rotate_key", "fallback_provider"] }
      : { failure_class: "rate_limit", actions: ["retry_same_key_once", "rotate_key"] };
  }
  if (statusCode === 402) {
    return {
      failure_class: "payment_required",
      actions: ["rotate_key", "cooldown_24h", "fallback_provider"],
      cooldown_seconds: 24 * 60 * 60,
    };
  }
  if (statusCode === 401 || statusCode === 403) {
    return {
      failure_class: "unauthorized",
      actions: ["refresh_token", "rotate_key", "fallback_provider"],
    };
  }
  if (statusCode >= 500 || statusCode === 408) {
    return { failure_class: "transient", actions: ["fallback_provider", "fail"] };
  }
  return { failure_class: "permanent", actions: ["fail"] };
}
