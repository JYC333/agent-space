import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { CustomSourcePolicyEnvelope } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};
import {
  CustomSourceRunner,
  cleanupSandbox,
  type CustomSourceRunnerSettings,
} from "../src/modules/intake/customSources/customSourceRunner";
import { validateCustomSourceHandlerOutput } from "../src/modules/intake/customSources/customSourceContractValidator";
import { generateCustomSourceHandlerSource } from "../src/modules/intake/customSources/customSourceHandlerTemplate";

function enabledSettings(): CustomSourceRunnerSettings {
  return {
    runner_enabled: true,
    allowed_languages: ["typescript_node"],
    network_hard_deny_rules: [],
    timeout_ms_max: 30_000,
    output_bytes_max: 1_048_576,
    download_bytes_max: 5_242_880,
    log_bytes_max: 65_536,
    max_files: 50,
    browser_automation_available: false,
    shell_available: false,
    dependency_installation_available: false,
  };
}

const POLICY_ENVELOPE = {
  allowed_network_origins: ["https://example.com"],
  capture_policy: "extract_text",
  retention_policy: "full_text",
  language: "typescript_node" as const,
  browser_automation_enabled: false,
  shell_enabled: false,
  dependency_installation_enabled: false,
  log_redaction_enabled: true,
  limits: {
    timeout_ms: 5000,
    max_download_bytes: 1_000_000,
    max_output_bytes: 1_000_000,
    max_files: 5,
    max_items: 20,
    max_evidence_items: 20,
    log_max_bytes: 65536,
  },
} satisfies CustomSourcePolicyEnvelope;

async function runGeneratedHandler(
  settings: CustomSourceRunnerSettings,
  listSelector: string | null,
  fetchedHtml: string,
) {
  const workDir = await mkdtemp(join(tmpdir(), "custom-source-template-test-"));
  const entrypointPath = join(workDir, "handler.cjs");
  await writeFile(entrypointPath, generateCustomSourceHandlerSource({ listSelector }), "utf8");

  const runner = new CustomSourceRunner(settings);
  const result = await runner.run({
    policyEnvelope: POLICY_ENVELOPE,
    handlerInput: {
      contract_version: "custom_source.handler_input.v1",
      run: {
        mode: "test",
        job_id: "job-1",
        connection_id: "conn-1",
        handler_version_id: "handler-1",
        started_at: new Date().toISOString(),
      },
      source: {
        name: "Example Source",
        endpoint_url: "https://example.com/list",
        config: { fetched_html: fetchedHtml },
      },
      policy: {
        allowed_network_origins: POLICY_ENVELOPE.allowed_network_origins,
        capture_policy: POLICY_ENVELOPE.capture_policy,
        retention_policy: POLICY_ENVELOPE.retention_policy,
        limits: POLICY_ENVELOPE.limits,
      },
    },
    handlerEntrypointPath: entrypointPath,
  });
  await rm(workDir, { recursive: true, force: true });
  return result;
}

describe("generateCustomSourceHandlerSource", () => {
  it("single_page mode extracts one item from the fetched page title/body via the real sandboxed runner", async () => {
    const result = await runGeneratedHandler(
      enabledSettings(),
      null,
      "<html><head><title>My Page Title</title></head><body><p>Hello world content here.</p></body></html>",
    );
    expect(result.status).toBe("completed");
    if (result.status !== "completed") return;
    expect(result.raw_output_json).not.toBeNull();
    await cleanupSandbox(result.sandbox_files_root);

    const validation = await validateCustomSourceHandlerOutput({
      raw: JSON.parse(result.raw_output_json!),
      limits: POLICY_ENVELOPE.limits,
      allowedNetworkOrigins: POLICY_ENVELOPE.allowed_network_origins,
      sandboxFilesRoot: result.sandbox_files_root,
    });
    expect(validation.ok).toBe(true);
    if (!validation.ok) return;
    expect(validation.output.items).toHaveLength(1);
    expect(validation.output.items[0]?.title).toBe("My Page Title");
    expect(validation.output.items[0]?.source_uri).toBe("https://example.com/list");
    expect(validation.output.items[0]?.excerpt).toContain("Hello world content here.");
  });

  it("list mode extracts one item per matching block, resolving relative links against endpoint_url", async () => {
    const html = `<html><body>
      <div class="article"><a href="/a1">First Title</a><p>First excerpt text.</p></div>
      <div class="article"><a href="/a2">Second Title</a><p>Second excerpt text.</p></div>
    </body></html>`;
    const result = await runGeneratedHandler(enabledSettings(), "article", html);
    expect(result.status).toBe("completed");
    if (result.status !== "completed") return;
    await cleanupSandbox(result.sandbox_files_root);

    const validation = await validateCustomSourceHandlerOutput({
      raw: JSON.parse(result.raw_output_json!),
      limits: POLICY_ENVELOPE.limits,
      allowedNetworkOrigins: POLICY_ENVELOPE.allowed_network_origins,
      sandboxFilesRoot: result.sandbox_files_root,
    });
    expect(validation.ok).toBe(true);
    if (!validation.ok) return;
    expect(validation.output.items).toHaveLength(2);
    expect(validation.output.items[0]?.title).toBe("First Title");
    expect(validation.output.items[0]?.source_uri).toBe("https://example.com/a1");
    expect(validation.output.items[1]?.title).toBe("Second Title");
    expect(validation.output.items[1]?.source_uri).toBe("https://example.com/a2");
  });

  it("produces no items and a diagnostic warning when the fetched page has no content", async () => {
    const result = await runGeneratedHandler(enabledSettings(), "article", "<html><body></body></html>");
    expect(result.status).toBe("completed");
    if (result.status !== "completed") return;
    await cleanupSandbox(result.sandbox_files_root);
    const output = JSON.parse(result.raw_output_json!);
    expect(output.items).toHaveLength(0);
    expect(output.diagnostics.warnings.length).toBeGreaterThan(0);
  });
});
