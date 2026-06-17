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

describe("server-owned features route", () => {
  it("advertises server_health and protocol detection", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/server/features" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { service: string; features: string[] };
    expect(body.service).toBe("server");
    expect(body.features).toContain("server_health");
    expect(body.features).toContain("run_event_sse_stream");
    expect(body.features).toContain("frontend_support_read_model_facades");
    expect(body.features).toContain("runtime_tools_controlled_installer");
    expect(body.features).toContain("native_identity_auth");
    expect(body.features).toContain("native_google_oauth");
    expect(body.features).toContain("native_space_membership");
    expect(body.features).toContain("api_keys_feature_gate");
    expect(body.features).toContain("space_default_seeding");
    expect(body.features).toContain("runtime_adapter_catalog");
    expect(body.features).toContain("execution_planes_server_authority");
    expect(body.features).toContain("runtime_tool_bindings_server_authority");
    expect(body.features).toContain("providers_read_server_authority");
    expect(body.features).toContain("providers_credentials_server_authority");
    expect(body.features).toContain("policy_enforcement_server_authority");
    expect(body.features).toContain("sessions_server_authority");
    expect(body.features).toContain("server_agent_runtime_host");
    expect(body.features).toContain("runs_server_authority");
    expect(body.features).toContain("runs_child_resources_server_authority");
    expect(body.features).toContain("artifacts_server_authority");
    expect(body.features).toContain("projects_server_authority");
    expect(body.features).toContain("agent_templates_server_authority");
    expect(body.features).toContain("capabilities_server_authority");
    expect(body.features).toContain("personal_memory_grants_server_authority");
    expect(body.features).toContain("evolution_server_authority");
    expect(body.features).toContain("source_pointers_server_authority");
    expect(body.features).toContain("workspace_profiles_server_authority");
    expect(body.features).toContain("proposals_server_authority");
    expect(body.features).toContain("chat_turn_server_authority");
    expect(body.features).toContain("context_assembly_server_authority");
    expect(body.features).toContain("memory_server_authority");
    expect(body.features).toContain("config_semantic_validation");
    expect(body.features).toContain("notification_webhook_egress_policy_gate");
  });

  it("exposes the product feature-list route used by the frontend", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/features" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as Array<{ id: string; name: string; enabled: boolean; always_on: boolean }>;
    expect(body).toContainEqual({
      id: "server_health",
      name: "server_health",
      enabled: true,
      always_on: true,
    });
  });

  it("detects the @agent-space/protocol package (declared file dependency)", () => {
    expect(isProtocolPackageDetected()).toBe(true);
    expect(computeFeatures(loadConfig({}))).toContain("protocol_package_detected");
  });

  it("advertises notification_webhook_egress only when policy enables it", () => {
    expect(computeFeatures(loadConfig({}))).not.toContain("notification_webhook_egress");
    const enabled = computeFeatures(
      loadConfig({
        SERVER_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true",
        SERVER_NOTIFICATION_WEBHOOK_ALLOWLIST:
          "https://hooks.example.com/proposal",
      }),
    );
    expect(enabled).toContain("notification_webhook_egress");
  });

  it("advertises fixed server providers, policy, sessions, and runtime-adapter features", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("providers_read_server_authority");
    expect(features).toContain("providers_credentials_server_authority");
    expect(features).toContain("policy_enforcement_server_authority");
    expect(features).toContain("sessions_server_authority");
    expect(features).toContain("runs_server_authority");
    expect(features).toContain("runs_child_resources_server_authority");
    expect(features).toContain("artifacts_server_authority");
    expect(features).toContain("projects_server_authority");
    expect(features).toContain("agent_templates_server_authority");
    expect(features).toContain("capabilities_server_authority");
    expect(features).toContain("personal_memory_grants_server_authority");
    expect(features).toContain("evolution_server_authority");
    expect(features).toContain("execution_planes_server_authority");
    expect(features).toContain("runtime_tool_bindings_server_authority");
    expect(features).toContain("source_pointers_server_authority");
    expect(features).toContain("workspace_profiles_server_authority");
    expect(features).toContain("runtime_adapter_catalog");
    expect(features).toContain("server_agent_runtime_host");
  });

  it("advertises fixed server proposal authority", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("proposals_server_authority");
  });

  it("advertises fixed server chat-turn, context, and memory authority", () => {
    const features = computeFeatures(loadConfig({}));
    expect(features).toContain("chat_turn_server_authority");
    expect(features).toContain("context_assembly_server_authority");
    expect(features).toContain("memory_server_authority");
  });
});
