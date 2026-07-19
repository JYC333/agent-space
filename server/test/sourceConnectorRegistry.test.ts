import { describe, expect, it } from "vitest";
import { sourceConnectorRegistry } from "../src/modules/sources/catalog/sourceConnectorRegistry";

describe("arXiv source connector query compilation", () => {
  const handler = sourceConnectorRegistry.get("arxiv_api");

  it("compiles an explicit all-papers scope without a user query", () => {
    const compiled = handler.compileQuery({ query: { mode: "all" } });

    expect(compiled.query).toEqual({ mode: "all" });
    expect(compiled.providerQuery).toMatchObject({ mode: "all", search_query: "all:*" });
    expect(new URL(compiled.endpointUrl!).searchParams.get("search_query")).toBe("all:*");
  });

  it("still rejects an unscoped arXiv source", () => {
    expect(() => handler.compileQuery({ query: {} })).toThrow("query.search_query");
  });

  it("auto-wraps plain-language search text as an all: field search", () => {
    const compiled = handler.compileQuery({ query: { search_query: "agent memory systems" } });

    expect(compiled.providerQuery).toMatchObject({ search_query: 'all:"agent memory systems"' });
  });

  it("strips surrounding quotes and escapes embedded quotes before wrapping", () => {
    const compiled = handler.compileQuery({ query: { search_query: '"agent \'memory" systems"' } });

    expect(compiled.providerQuery.search_query).toBe('all:"agent \'memory\' systems"');
  });

  it("leaves an already field-prefixed query untouched", () => {
    const compiled = handler.compileQuery({ query: { search_query: 'cat:cs.AI AND abs:"agent memory"' } });

    expect(compiled.providerQuery).toMatchObject({ search_query: 'cat:cs.AI AND abs:"agent memory"' });
  });
});
