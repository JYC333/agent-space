import { describe, expect, it } from "vitest";
import { AskSpaceRequestSchema } from "../src/index";

describe("Ask Space protocol contracts", () => {
  it("accepts intake as an opt-in domain", () => {
    const request = AskSpaceRequestSchema.parse({
      query: "recent relevant papers",
      domains: ["knowledge", "intake"],
    });

    expect(request.domains).toEqual(["knowledge", "intake"]);
  });

  it("accepts all four fixed domains but rejects unknown domains", () => {
    expect(AskSpaceRequestSchema.safeParse({
      query: "alpha",
      domains: ["knowledge", "memory", "project", "intake"],
    }).success).toBe(true);

    expect(AskSpaceRequestSchema.safeParse({
      query: "alpha",
      domains: ["knowledge", "sources"],
    }).success).toBe(false);
  });
});
