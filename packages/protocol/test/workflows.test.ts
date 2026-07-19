import { describe, expect, it } from "vitest";
import { WorkflowDefinitionSchema } from "../src";

function definition(inputBindings: unknown[] = []) {
  return {
    schema_version: "workflow_definition.v1",
    workflow_id: "workflow-1",
    name: "Workflow",
    description: "",
    input_schema_json: {},
    output_artifact_types: [],
    nodes: [
      { id: "source", title: "Source", depends_on: [], capability_id: "source", contract_json: {}, metadata_json: {} },
      { id: "consumer", title: "Consumer", depends_on: ["source"], input_bindings: inputBindings, capability_id: "consumer", contract_json: {}, metadata_json: {} },
    ],
    metadata_json: {},
  };
}

describe("workflow node input bindings", () => {
  it("accepts explicit bindings from direct dependencies", () => {
    const parsed = WorkflowDefinitionSchema.parse(definition([
      { name: "summary", from_node: "source", source: "output_text" },
      { name: "value", from_node: "source", source: "output_json", json_pointer: "/result/value" },
      { name: "report", from_node: "source", source: "artifact", artifact_type: "report" },
    ]));
    expect(parsed.nodes[1]?.input_bindings).toHaveLength(3);
  });

  it("rejects hidden dependencies and source-specific selector misuse", () => {
    expect(() => WorkflowDefinitionSchema.parse(definition([
      { name: "hidden", from_node: "other", source: "output_text" },
    ]))).toThrow(/direct dependency/);
    expect(() => WorkflowDefinitionSchema.parse(definition([
      { name: "bad", from_node: "source", source: "output_text", json_pointer: "/value" },
    ]))).toThrow(/json_pointer is only valid/);
    expect(() => WorkflowDefinitionSchema.parse(definition([
      { name: "bad", from_node: "source", source: "artifact" },
    ]))).toThrow(/artifact bindings require artifact_type/);
  });

  it("rejects duplicate binding names, invalid JSON pointers, and dependency cycles", () => {
    expect(() => WorkflowDefinitionSchema.parse(definition([
      { name: "same", from_node: "source", source: "output_text" },
      { name: "same", from_node: "source", source: "output_text" },
    ]))).toThrow(/duplicate input binding/);
    expect(() => WorkflowDefinitionSchema.parse(definition([
      { name: "bad", from_node: "source", source: "output_json", json_pointer: "result/value" },
    ]))).toThrow();
    const cyclic = definition();
    cyclic.nodes[0]!.depends_on = ["consumer"];
    expect(() => WorkflowDefinitionSchema.parse(cyclic)).toThrow(/dependency cycle/);
  });
});
