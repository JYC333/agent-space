/**
 * Optional read-only shadow compare for provider reads.
 *
 * While Python serves the response, the TS DB-backed result is computed and
 * compared. The comparison is strictly observational: it runs after the
 * response is sent, never throws into the request path, and degrades to a
 * logged skip when the DB or the introspection port is unavailable.
 */

import type { FastifyRequest } from "fastify";
import type { ControlPlaneConfig } from "../../config";
import { resolveProvidersDbPort } from "./dbReader";
import { introspectIdentity } from "./identity";
import { loadProtocol } from "./protocolRuntime";

export type ShadowRoute = "list" | "detail" | "catalog";

export interface ShadowReport {
  route: ShadowRoute;
  outcome: "match" | "divergence" | "skipped" | "error";
  divergences?: string[];
  reason?: string;
}

type ShadowReporter = (report: ShadowReport) => void;

let testReporter: ShadowReporter | null = null;

/** Test helper: observe shadow outcomes (pass null to remove). */
export function __setShadowReporterForTests(reporter: ShadowReporter | null): void {
  testReporter = reporter;
}

const TIMESTAMP_KEYS = new Set(["created_at", "updated_at"]);

function timestampsEqual(a: unknown, b: unknown): boolean {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const ta = Date.parse(a);
  const tb = Date.parse(b);
  return Number.isFinite(ta) && Number.isFinite(tb) && ta === tb;
}

/**
 * Deep-compare two JSON payloads and return the diverging paths. Timestamp
 * fields compare by instant, not by string, because Python (isoformat) and TS
 * (`toISOString`) serialize the same instant differently.
 */
export function compareProviderPayloads(
  expected: unknown,
  actual: unknown,
  path = "$",
): string[] {
  if (Array.isArray(expected) || Array.isArray(actual)) {
    if (!Array.isArray(expected) || !Array.isArray(actual)) return [path];
    if (expected.length !== actual.length) return [`${path}.length`];
    const diffs: string[] = [];
    for (let i = 0; i < expected.length; i += 1) {
      diffs.push(...compareProviderPayloads(expected[i], actual[i], `${path}[${i}]`));
    }
    return diffs;
  }
  if (
    expected !== null &&
    actual !== null &&
    typeof expected === "object" &&
    typeof actual === "object"
  ) {
    const expectedRecord = expected as Record<string, unknown>;
    const actualRecord = actual as Record<string, unknown>;
    const keys = new Set([...Object.keys(expectedRecord), ...Object.keys(actualRecord)]);
    const diffs: string[] = [];
    for (const key of keys) {
      const childPath = `${path}.${key}`;
      if (TIMESTAMP_KEYS.has(key)) {
        if (!timestampsEqual(expectedRecord[key], actualRecord[key])) diffs.push(childPath);
        continue;
      }
      diffs.push(...compareProviderPayloads(expectedRecord[key], actualRecord[key], childPath));
    }
    return diffs;
  }
  return Object.is(expected, actual) ? [] : [path];
}

async function computeTsResult(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  route: ShadowRoute,
  configId: string | undefined,
): Promise<{ ok: true; value: unknown } | { ok: false; reason: string }> {
  if (route === "catalog") {
    const { PROVIDER_CATALOG_INFO } = await loadProtocol();
    return { ok: true, value: PROVIDER_CATALOG_INFO };
  }
  const db = resolveProvidersDbPort(config);
  if (!db) return { ok: false, reason: "no_database_configured" };
  const identity = await introspectIdentity(config, request);
  if (!identity.ok) return { ok: false, reason: `introspect_${identity.reason}` };
  if (route === "list") {
    return { ok: true, value: await db.listProviders(identity.spaceId) };
  }
  if (!configId) return { ok: false, reason: "missing_config_id" };
  const row = await db.getProvider(identity.spaceId, configId);
  if (row === null) return { ok: false, reason: "row_not_found" };
  return { ok: true, value: row };
}

function emit(request: FastifyRequest, report: ShadowReport): void {
  testReporter?.(report);
  if (report.outcome === "divergence") {
    request.log.warn(
      { providers_shadow: report.outcome, route: report.route, divergences: report.divergences },
      "providers shadow compare divergence",
    );
  } else {
    request.log.info(
      { providers_shadow: report.outcome, route: report.route, reason: report.reason },
      "providers shadow compare",
    );
  }
}

/**
 * Compare the payload Python served against the TS DB-backed result.
 * Never throws; call without awaiting from the serving path.
 */
export async function runProvidersShadowCompare(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  route: ShadowRoute,
  servedPayload: unknown,
  configId?: string,
): Promise<void> {
  try {
    const computed = await computeTsResult(config, request, route, configId);
    if (!computed.ok) {
      emit(request, { route, outcome: "skipped", reason: computed.reason });
      return;
    }
    const divergences = compareProviderPayloads(servedPayload, computed.value);
    if (divergences.length === 0) {
      emit(request, { route, outcome: "match" });
    } else {
      emit(request, { route, outcome: "divergence", divergences });
    }
  } catch (err) {
    emit(request, {
      route,
      outcome: "error",
      reason: err instanceof Error ? err.message : "unknown",
    });
  }
}
