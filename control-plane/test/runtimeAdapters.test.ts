import { describe, expect, it } from "vitest";
import {
  getLocalCliRuntimeAdapterSpec,
  getRuntimeAdapterSpec,
  isVendorCliAdapter,
  listRuntimeAdapterSpecs,
  targetFormatForAdapter,
} from "../src/modules/runtimeAdapters";

describe("runtime adapter catalog", () => {
  it("keeps model-provider credentials separate from local CLI login state", () => {
    const specs = listRuntimeAdapterSpecs();
    const modelProviderSpecs = specs.filter(
      (spec) => spec.credentials.credential_mode === "model_provider_api_key",
    );
    expect(modelProviderSpecs.map((spec) => spec.adapter_type).sort()).toEqual([
      "model_api",
      "ts_agent_host",
    ]);

    for (const spec of specs.filter((item) => item.runtime_kind === "local_cli")) {
      expect(spec.model.model_provider_mode).toBe("none");
      expect(spec.credentials.credential_mode).toBe("cli_profile");
      expect(spec.credentials.credential_runtime_name).toBe(spec.adapter_type);
    }
  });

  it("exposes only implemented local CLI adapters as executable vendor CLIs", () => {
    expect(isVendorCliAdapter("claude_code")).toBe(true);
    expect(isVendorCliAdapter("codex_cli")).toBe(true);
    expect(isVendorCliAdapter("opencode")).toBe(false);
    expect(isVendorCliAdapter("gemini_cli")).toBe(false);
    expect(getLocalCliRuntimeAdapterSpec("opencode")?.implementation_status).toBe("planned");
  });

  it("owns adapter context target semantics outside providers", () => {
    expect(targetFormatForAdapter("claude_code")).toBe("claude");
    expect(targetFormatForAdapter("codex_cli")).toBe("codex_cli");
    expect(getRuntimeAdapterSpec("model_api")?.runtime_kind).toBe("managed_api");
  });
});
