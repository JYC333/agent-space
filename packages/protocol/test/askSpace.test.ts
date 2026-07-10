import { describe, expect, it } from "vitest";
import { AskSpaceRequestSchema } from "../src/index";

describe("Ask Space protocol contracts", () => {
  it("accepts source as an opt-in domain", () => {
    const request = AskSpaceRequestSchema.parse({
      query: "recent relevant papers",
      domains: ["knowledge", "source"],
    });

    expect(request.domains).toEqual(["knowledge", "source"]);
  });

  it("accepts all four fixed domains but rejects unknown domains", () => {
    expect(AskSpaceRequestSchema.safeParse({
      query: "alpha",
      domains: ["knowledge", "memory", "project", "source"],
    }).success).toBe(true);

    expect(AskSpaceRequestSchema.safeParse({
      query: "alpha",
      domains: ["knowledge", "sources"],
    }).success).toBe(false);
  });
});
