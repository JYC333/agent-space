import { describe, expect, it } from "vitest";
import {
  CORE_GRAPH_EDGE_KINDS,
  CORE_GRAPH_NODE_KINDS,
  GraphProjectionSchema,
} from "../src/index";

describe("graph projection contract", () => {
  it("parses a core graph projection", () => {
    const projection = GraphProjectionSchema.parse({
      nodes: [
        {
          id: "node-1",
          kind: "knowledge_item",
          label: "Retrieval",
          subtitle: "Concept",
          degree: 2,
          metadata: { source: "wiki" },
        },
        {
          id: "cluster:claim",
          kind: "cluster",
          label: "Claims",
          size: 48,
          collapsed: true,
        },
      ],
      edges: [
        {
          id: "edge-1",
          source: "node-1",
          target: "cluster:claim",
          kind: "cluster_contains",
          weight: 3,
        },
      ],
      view: {
        mode: "global",
        generatedAt: "2026-07-04T12:00:00.000Z",
        truncated: true,
        totalNodeCount: 1200,
      },
      layout: { mode: "clustered", version: 1 },
    });

    expect(projection.nodes).toHaveLength(2);
    expect(projection.edges[0]?.kind).toBe("cluster_contains");
  });

  it("keeps plugin kinds open while exporting known core kinds", () => {
    const projection = GraphProjectionSchema.parse({
      nodes: [
        { id: "paper-1", kind: "paper", label: "A paper" },
        { id: "paper-2", kind: "paper", label: "Another paper" },
      ],
      edges: [
        {
          id: "edge-1",
          source: "paper-1",
          target: "paper-2",
          kind: "cites",
        },
      ],
      view: {
        mode: "local",
        rootId: "paper-1",
        depth: 1,
        generatedAt: "2026-07-04T12:00:00.000Z",
      },
    });

    expect(projection.nodes[0]?.kind).toBe("paper");
    expect(CORE_GRAPH_NODE_KINDS).toContain("cluster");
    expect(CORE_GRAPH_EDGE_KINDS).toContain("cluster_contains");
  });

  it("rejects invalid projection-level modes and negative weights", () => {
    expect(() =>
      GraphProjectionSchema.parse({
        nodes: [],
        edges: [],
        view: {
          mode: "raw_full_graph",
          generatedAt: "2026-07-04T12:00:00.000Z",
        },
      }),
    ).toThrow();

    expect(() =>
      GraphProjectionSchema.parse({
        nodes: [
          { id: "node-1", kind: "note", label: "Note" },
          { id: "node-2", kind: "note", label: "Another note" },
        ],
        edges: [
          {
            id: "edge-1",
            source: "node-1",
            target: "node-2",
            kind: "related_to",
            weight: -1,
          },
        ],
        view: {
          mode: "debug",
          generatedAt: "2026-07-04T12:00:00.000Z",
        },
      }),
    ).toThrow();
  });

  it("rejects edges whose endpoints are absent from the projection", () => {
    expect(() =>
      GraphProjectionSchema.parse({
        nodes: [{ id: "paper-1", kind: "paper", label: "A paper" }],
        edges: [
          {
            id: "edge-1",
            source: "paper-1",
            target: "paper-2",
            kind: "cites",
          },
        ],
        view: {
          mode: "local",
          rootId: "paper-1",
          depth: 1,
          generatedAt: "2026-07-04T12:00:00.000Z",
        },
      }),
    ).toThrow("edge target must reference a projection node");
  });

  it("rejects engine-specific fields outside metadata", () => {
    expect(() =>
      GraphProjectionSchema.parse({
        nodes: [
          {
            id: "node-1",
            kind: "note",
            label: "Note",
            style: { fill: "red" },
          },
        ],
        edges: [],
        view: {
          mode: "debug",
          generatedAt: "2026-07-04T12:00:00.000Z",
        },
      }),
    ).toThrow();

    const parsed = GraphProjectionSchema.parse({
      nodes: [
        {
          id: "node-1",
          kind: "note",
          label: "Note",
          metadata: { style: { fill: "red" } },
        },
      ],
      edges: [],
      view: {
        mode: "debug",
        generatedAt: "2026-07-04T12:00:00.000Z",
      },
    });
    expect(parsed.nodes[0]?.metadata).toEqual({ style: { fill: "red" } });
  });
});
