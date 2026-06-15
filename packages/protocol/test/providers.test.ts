import { describe, it, expect, expectTypeOf } from "vitest";
import {
  CredentialChannelMetadataSchema,
  LitellmProvidersResponseSchema,
  ModelProviderCreateRequestSchema,
  ModelProviderDTOSchema,
  ModelProviderModelsResponseSchema,
  ModelProviderUpdateRequestSchema,
  ProviderCatalogInfoSchema,
  ProviderChatRequestSchema,
  ProviderChatResponseSchema,
  ProviderConnectionTestResultSchema,
  isCredentialChannel,
  isProviderType,
  type ModelProviderDTO,
} from "../src/index";

describe("provider contracts", () => {
  it("parses the current public ModelProviderOut shape", () => {
    const parsed = ModelProviderDTOSchema.parse({
      id: "mp1",
      space_id: "s1",
      name: "Main",
      provider_type: "anthropic",
      base_url: null,
      default_model: "claude-sonnet-4-6",
      available_models: ["claude-sonnet-4-6"],
      enabled: true,
      is_default: true,
      has_api_key: true,
      created_at: "2026-06-11T12:00:00+00:00",
      updated_at: "2026-06-11T12:00:00+00:00",
    });
    expect(parsed.provider_type).toBe("anthropic");
    expect(parsed.has_api_key).toBe(true);
  });

  it("rejects secret material in provider response contracts", () => {
    const base = {
      id: "mp1",
      space_id: "s1",
      name: "Main",
      provider_type: "openai",
      base_url: null,
      default_model: "gpt-4o",
      available_models: [],
      enabled: true,
      is_default: false,
      has_api_key: true,
      created_at: "2026-06-11T12:00:00+00:00",
      updated_at: "2026-06-11T12:00:00+00:00",
    };
    expect(ModelProviderDTOSchema.safeParse({ ...base, api_key: "sk-live" }).success).toBe(
      false,
    );
    expect(
      ModelProviderDTOSchema.safeParse({ ...base, secret_ref: "model_provider_api_key:v1:x" })
        .success,
    ).toBe(false);
  });

  it("allows request-only api_key on create/update payloads", () => {
    expect(
      ModelProviderCreateRequestSchema.parse({
        name: "Main",
        provider_type: "openai",
        api_key: "sk-test",
        default_model: "gpt-4o",
      }).api_key,
    ).toBe("sk-test");

    expect(ModelProviderUpdateRequestSchema.parse({ api_key: "sk-new" }).api_key).toBe(
      "sk-new",
    );
  });

  it("parses provider support responses and chat request/response bodies", () => {
    expect(
      ModelProviderModelsResponseSchema.parse({
        models: ["gpt-4o"],
        source: "configured",
      }).source,
    ).toBe("configured");
    expect(
      ProviderConnectionTestResultSchema.parse({
        success: true,
        message: "ok",
        model: "gpt-4o",
      }).success,
    ).toBe(true);
    expect(
      ProviderChatRequestSchema.parse({
        provider_id: "mp1",
        messages: [{ role: "user", content: "hi" }],
        max_tokens: 128,
      }).messages,
    ).toHaveLength(1);
    expect(
      ProviderChatResponseSchema.parse({
        content: "hello",
        provider: "openai",
        model: "gpt-4o",
        usage: { total_tokens: 8 },
      }).usage.total_tokens,
    ).toBe(8);
    expect(
      ProviderChatResponseSchema.safeParse({
        content: "hello",
        provider: "openai",
        model: "gpt-4o",
        usage: {},
        api_key: "sk-leak",
      }).success,
    ).toBe(false);
  });

  it("parses the static catalog and litellm-providers read shapes", () => {
    const catalogInfo = {
      id: "litellm",
      name: "LiteLLM (Open Format)",
      description: "Configure endpoints.",
      model_hint: "Set default_model",
      supported_params: ["model", "temperature"],
    };
    expect(ProviderCatalogInfoSchema.parse(catalogInfo).id).toBe("litellm");
    expect(
      ProviderCatalogInfoSchema.safeParse({ ...catalogInfo, api_key: "sk-leak" }).success,
    ).toBe(false);
    expect(LitellmProvidersResponseSchema.parse(["openai", "anthropic"])).toHaveLength(2);
    expect(LitellmProvidersResponseSchema.safeParse([{ id: "openai" }]).success).toBe(false);
  });

  it("documents provider and credential-channel value sets without constraining provider_type", () => {
    expect(ModelProviderDTOSchema.safeParse({
      id: "mp1",
      space_id: "s1",
      name: "Future",
      provider_type: "future_provider",
      base_url: null,
      default_model: null,
      available_models: [],
      enabled: true,
      is_default: false,
      has_api_key: false,
      created_at: "2026-06-11T12:00:00+00:00",
      updated_at: "2026-06-11T12:00:00+00:00",
    }).success).toBe(true);
    expect(isProviderType("anthropic")).toBe(true);
    expect(isProviderType("future_provider")).toBe(false);
    expect(isCredentialChannel("model_provider_api_key")).toBe(true);
    expect(isCredentialChannel("other")).toBe(false);
  });

  it("keeps credential channel metadata explicit and non-secret", () => {
    expect(
      CredentialChannelMetadataSchema.parse({
        channel: "model_provider_api_key",
        pooled: true,
        rotated: true,
      }),
    ).toEqual({
      channel: "model_provider_api_key",
      pooled: true,
      rotated: true,
    });
    expect(
      CredentialChannelMetadataSchema.safeParse({
        channel: "cli_login_state",
        pooled: true,
        rotated: false,
      }).success,
    ).toBe(false);
    expect(
      CredentialChannelMetadataSchema.safeParse({
        channel: "cli_login_state",
        pooled: false,
        rotated: false,
      }).success,
    ).toBe(true);
  });
});

describe("provider type-level contracts", () => {
  it("infers provider DTO types from schemas", () => {
    expectTypeOf<ModelProviderDTO>().toHaveProperty("space_id");
    expectTypeOf<ModelProviderDTO["has_api_key"]>().toEqualTypeOf<boolean>();
  });
});
