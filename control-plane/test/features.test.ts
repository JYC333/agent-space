import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  computeFeatures,
  isProtocolPackageDetected,
} from "../src/modules/system";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("TS-owned features route", () => {
  it("advertises control_plane_health, python_fallback_proxy and protocol detection", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/features" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { service: string; features: string[] };
    expect(body.service).toBe("control-plane");
    expect(body.features).toContain("control_plane_health");
    expect(body.features).toContain("python_fallback_proxy");
    expect(body.features).toContain("run_event_sse_stream");
    expect(body.features).toContain("frontend_support_read_model_facades");
    expect(body.features).toContain("runtime_tools_controlled_installer");
    expect(body.features).toContain("native_identity_auth");
    expect(body.features).toContain("native_google_oauth");
    expect(body.features).toContain("native_space_membership");
    expect(body.features).toContain("api_keys_feature_gate");
    expect(body.features).toContain("space_default_seeding");
    expect(body.features).toContain("runtime_adapter_catalog");
    expect(body.features).toContain("providers_read_ts_authority");
    expect(body.features).toContain("providers_credentials_ts_authority");
    expect(body.features).toContain("policy_enforcement_ts_authority");
    expect(body.features).toContain("sessions_ts_authority");
    expect(body.features).toContain("ts_agent_runtime_host");
    expect(body.features).toContain("runs_ts_authority");
    expect(body.features).toContain("artifacts_ts_authority");
    expect(body.features).toContain("proposals_ts_authority");
    expect(body.features).toContain("chat_turn_ts_authority");
    expect(body.features).toContain("context_assembly_ts_authority");
    expect(body.features).toContain("memory_ts_authority");
    expect(body.features).toContain("config_semantic_validation");
    expect(body.features).toContain("notification_webhook_egress_policy_gate");
  });

  it("detects the @agent-space/protocol package (declared file dependency)", () => {
    expect(isProtocolPackageDetected()).toBe(true);
    expect(computeFeatures(loadConfig({}))).toContain("protocol_package_detected");
  });

  it("omits python_fallback_proxy when the proxy is disabled", () => {
    const features = computeFeatures(
      loadConfig({ CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false" }),
    );
    expect(features).not.toContain("python_fallback_proxy");
    expect(features).toContain("control_plane_health");
  });

  it("advertises notification_webhook_egress only when policy enables it", () => {
    expect(computeFeatures(loadConfig({}))).not.toContain("notification_webhook_egress");
    const enabled = computeFeatures(
      loadConfig({
        CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true",
        CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST:
          "https://hooks.example.com/proposal",
      }),
    );
    expect(enabled).toContain("notification_webhook_egress");
  });

  it("advertises fixed TS providers, policy, sessions, and runtime-adapter features", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("providers_read_ts_authority");
    expect(features).toContain("providers_credentials_ts_authority");
    expect(features).toContain("policy_enforcement_ts_authority");
    expect(features).not.toContain("policy_enforcement_python_authority");
    expect(features).toContain("sessions_ts_authority");
    expect(features).not.toContain("sessions_python_authority");
    expect(features).toContain("runs_ts_authority");
    expect(features).toContain("artifacts_ts_authority");
    expect(features).not.toContain("runs_commands_python_authority");
    expect(features).toContain("runtime_adapter_catalog");
    expect(features).toContain("ts_agent_runtime_host");
  });

  it("advertises fixed TS proposal authority", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("proposals_ts_authority");
    expect(features).not.toContain("proposals_review_python_authority");
    expect(features).not.toContain("proposals_review_ts_authority");
  });

  it("advertises fixed TS chat-turn, context, and memory authority", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("chat_turn_ts_authority");
    expect(features).not.toContain("chat_turn_python_authority");
    expect(features).toContain("context_assembly_ts_authority");
    expect(features).not.toContain("context_assembly_python_authority");
    expect(features).toContain("memory_ts_authority");
    expect(features).not.toContain("memory_python_authority");
  });
});
