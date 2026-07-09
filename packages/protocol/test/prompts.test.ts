import { describe, expect, it } from "vitest";
import { PromptAssetContentSchema } from "../src/prompts";

describe("PromptAssetContentSchema", () => {
  it("accepts exactly one renderable prompt body", () => {
    expect(
      PromptAssetContentSchema.parse({
        schema_version: "prompt_asset.v1",
        prompt_type: "text",
        template: "Hello {name}",
      }),
    ).toMatchObject({
      prompt_type: "text",
      template: "Hello {name}",
      rendering: { engine: "plain" },
    });
  });

  it("rejects missing or ambiguous prompt bodies", () => {
    expect(() =>
      PromptAssetContentSchema.parse({
        schema_version: "prompt_asset.v1",
        prompt_type: "text",
      }),
    ).toThrow(/exactly one of messages or template/);

    expect(() =>
      PromptAssetContentSchema.parse({
        schema_version: "prompt_asset.v1",
        prompt_type: "chat",
        messages: [{ role: "system", content: "System" }],
        template: "Template",
      }),
    ).toThrow(/exactly one of messages or template/);
  });

  it("rejects unsupported rendering engines", () => {
    expect(() =>
      PromptAssetContentSchema.parse({
        schema_version: "prompt_asset.v1",
        prompt_type: "text",
        template: "Hello",
        rendering: { engine: "mustache" },
      }),
    ).toThrow();
  });
});
