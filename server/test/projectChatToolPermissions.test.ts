import {describe,expect,it} from "vitest";
import {projectChatCapabilities} from "../src/modules/agents/routes";
import {filterGenericActionCapabilities,proposalActionJsonSchema} from "../src/modules/systemActions/agentToolGateway";

describe("Project Chat tool permissions",()=>{
  const requested=["source.connection.propose_create","project.source.propose_bind","source.backfill.propose_start"];
  it("does not expose proposal tools without AgentVersion permission",()=>{
    expect(projectChatCapabilities({})).toEqual([]);
    expect(filterGenericActionCapabilities(requested,{})).toEqual([]);
  });
  it("exposes only explicitly allowed tools at both gates",()=>{
    const permissions={allowed_tools:["project.source.propose_bind"]};
    expect(projectChatCapabilities(permissions)).toEqual(["project.source.propose_bind"]);
    expect(filterGenericActionCapabilities(requested,permissions)).toEqual(["project.source.propose_bind"]);
  });
  it("publishes required model fields for proposal tools",()=>{
    expect(proposalActionJsonSchema("project.source.propose_bind")).toMatchObject({required:["source_channel_id"]});
    expect(proposalActionJsonSchema("source.backfill.propose_start")).toMatchObject({required:["source_channel_id","source_backfill_plan_id"]});
  });
});
