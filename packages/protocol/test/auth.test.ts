import { describe, it, expect } from "vitest";
import {
  IdentityIntrospectionResponseSchema,
  MODEL_PROVIDERS_READ_COLUMNS,
  MODEL_PROVIDERS_TABLE,
  PROVIDER_CATALOG_INFO,
  ProviderCatalogInfoSchema,
} from "../src/index";

describe("identity introspection contract", () => {
  it("parses the introspection response", () => {
    const parsed = IdentityIntrospectionResponseSchema.parse({
      space_id: "space-1",
      user_id: "user-1",
    });
    expect(parsed.space_id).toBe("space-1");
    expect(parsed.user_id).toBe("user-1");
  });

  it("rejects token/session/secret material on the identity port", () => {
    const base = { space_id: "space-1", user_id: "user-1" };
    expect(
      IdentityIntrospectionResponseSchema.safeParse({ ...base, token: "tok" }).success,
    ).toBe(false);
    expect(
      IdentityIntrospectionResponseSchema.safeParse({ ...base, session_id: "sess" }).success,
    ).toBe(false);
    expect(
      IdentityIntrospectionResponseSchema.safeParse({ ...base, api_key: "sk-leak" }).success,
    ).toBe(false);
    expect(IdentityIntrospectionResponseSchema.safeParse({ space_id: "s" }).success).toBe(false);
  });
});

describe("provider DB read allowlist", () => {
  it("pins the table and the exact column set the server reader may SELECT", () => {
    expect(MODEL_PROVIDERS_TABLE).toBe("model_providers");
    // Pins the model_providers columns exposed through the server read model.
    expect([...MODEL_PROVIDERS_READ_COLUMNS].sort()).toEqual(
      [
        "id",
        "space_id",
        "name",
        "provider_type",
        "base_url",
        "default_model",
        "enabled",
        "credential_id",
        "capabilities_json",
        "config_json",
        "created_at",
        "updated_at",
      ].sort(),
    );
  });
});

describe("provider catalog constant", () => {
  it("is a valid catalog payload with the documented catalog values", () => {
    expect(ProviderCatalogInfoSchema.parse(PROVIDER_CATALOG_INFO)).toEqual({
      id: "litellm",
      name: "LiteLLM (Open Format)",
      description:
        "Configure OpenAI, Anthropic, OpenRouter, Ollama, or custom OpenAI-compatible endpoints.",
      model_hint: "Set default_model and/or available_models on the provider",
      supported_params: ["model", "temperature", "max_tokens", "system"],
    });
  });
});
