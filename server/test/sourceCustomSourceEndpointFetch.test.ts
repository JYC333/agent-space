import { afterEach, describe, expect, it, vi } from "vitest";
import type { SourcePolicyEnvelope } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};
import { fetchCustomSourceEndpointHtml } from "../src/modules/sources/customSources/customSourceEndpointFetch";
import type { CustomSourceRunnerSettings } from "../src/modules/sources/customSources/customSourceRunner";

const ORIGIN = "https://sources.example";

const POLICY_ENVELOPE = {
  allowed_network_origins: [ORIGIN],
  capture_policy: "extract_text",
  retention_policy: "full_text",
  credential_ref: null,
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
} satisfies SourcePolicyEnvelope;

function runnerSettings(
  overrides: Partial<CustomSourceRunnerSettings> = {},
): CustomSourceRunnerSettings {
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
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchCustomSourceEndpointHtml", () => {
  it("fetches and follows same-origin redirects allowed by the handler envelope", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === `${ORIGIN}/redirect-same-origin`) {
        return new Response(null, { status: 302, headers: { location: "/ok" } });
      }
      return new Response("hello pi world", { status: 200 });
    });

    const html = await fetchCustomSourceEndpointHtml(`${ORIGIN}/redirect-same-origin`, runnerSettings(), POLICY_ENVELOPE);
    expect(html).toBe("hello pi world");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${ORIGIN}/ok`);
  });

  it("rejects an off-origin redirect before following it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 302, headers: { location: "https://other.example/off-origin" } }),
    );

    await expect(
      fetchCustomSourceEndpointHtml(`${ORIGIN}/redirect-off-origin`, runnerSettings(), POLICY_ENVELOPE),
    ).rejects.toThrow("not allowed by the handler policy envelope");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("truncates fetched HTML by UTF-8 byte length", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("hello pi world", { status: 200 }));

    const html = await fetchCustomSourceEndpointHtml(
      `${ORIGIN}/ok`,
      runnerSettings({ download_bytes_max: 8 }),
      { ...POLICY_ENVELOPE, limits: { ...POLICY_ENVELOPE.limits, max_download_bytes: 8 } },
    );
    expect(Buffer.byteLength(html, "utf8")).toBeLessThanOrEqual(8);
    expect(html).toBe("hello pi");
  });
});
