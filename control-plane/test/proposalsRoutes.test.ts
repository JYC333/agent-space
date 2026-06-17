import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setProposalIdentityForTests,
  __setProposalServicesFactoryForTests,
} from "../src/modules/proposals";
import { ProposalApplyHttpError } from "../src/modules/proposals/applyService";
import { UnknownProposalApplierError } from "../src/modules/proposals/applierRegistry";
import type { ProposalOut, ProposalPage } from "@agent-space/protocol" with { "resolution-mode": "import" };

let app: FastifyInstance;

afterEach(async () => {
  __setProposalIdentityForTests(null);
  __setProposalServicesFactoryForTests(null);
  await app?.close();
});

function tsProposalsConfig() {
  return loadConfig({
    CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
  });
}

function proposal(overrides: Partial<ProposalOut> = {}): ProposalOut {
  return {
    id: "proposal-1",
    space_id: "space-1",
    user_id: "user-1",
    workspace_id: null,
    source_session_id: null,
    source_task_id: null,
    source_run_id: null,
    created_by_run_id: null,
    proposal_type: "memory_create",
    target_scope: "",
    target_namespace: "",
    memory_type: "",
    proposed_title: "Remember this",
    proposed_content: "content",
    rationale: "",
    status: "pending",
    risk_level: "low",
    urgency: "normal",
    visibility: "space_shared",
    preview: false,
    review_deadline: null,
    expires_at: null,
    expired: false,
    created_at: "2026-06-14T10:00:00.000Z",
    decided_at: null,
    resulting_memory_id: null,
    owner_user_id: null,
    subject_user_id: null,
    sensitivity_level: null,
    selected_user_ids: null,
    provenance_entries: null,
    source_activity_id: null,
    grant_id: null,
    required_approver_user_id: null,
    requires_approval_type: null,
    egress_approval_status: null,
    egress_approval_id: null,
    project_id: null,
    ...overrides,
  };
}

describe("proposal review routes", () => {
  it("serves proposal list from the TS read model", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: Array<Record<string, unknown>> = [];
    const page: ProposalPage = {
      items: [proposal()],
      total: 1,
      limit: 25,
      offset: 10,
    };
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible(spaceId, userId, filters) {
          calls.push({ spaceId, userId, filters });
          return page;
        },
        async getVisible() {
          throw new Error("getVisible should not run");
        },
      },
      applyService: {
        async accept() {
          throw new Error("accept should not run");
        },
        async reject() {
          throw new Error("reject should not run");
        },
        async approveEgressGrantingUser() {
          throw new Error("approval should not run");
        },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/proposals?limit=25&offset=10&type=code_patch&expired=false",
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual(page);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      spaceId: "space-1",
      userId: "user-1",
      filters: {
        status: "pending",
        proposalType: "code_patch",
        expired: false,
        limit: 25,
        offset: 10,
      },
    });
  });

  it("serves visible proposal details from the TS read model", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible() {
          throw new Error("listVisible should not run");
        },
        async getVisible(spaceId, userId, proposalId) {
          expect({ spaceId, userId, proposalId }).toEqual({
            spaceId: "space-1",
            userId: "user-1",
            proposalId: "proposal-1",
          });
          return proposal({ id: proposalId });
        },
      },
      applyService: {
        async accept() {
          throw new Error("accept should not run");
        },
        async reject() {
          throw new Error("reject should not run");
        },
        async approveEgressGrantingUser() {
          throw new Error("approval should not run");
        },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/proposals/proposal-1",
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ id: "proposal-1", status: "pending" });
  });

  it("applies accept, reject, and egress approval through the TS proposal service", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: string[] = [];
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible() {
          throw new Error("listVisible should not run");
        },
        async getVisible() {
          throw new Error("getVisible should not run");
        },
      },
      applyService: {
        async accept(proposalId, identity, options) {
          calls.push(`accept:${proposalId}:${identity.spaceId}:${identity.userId}:${options?.confirmIncompletePatch}`);
          return {
            proposal: proposal({ status: "accepted", decided_at: "2026-06-14T10:01:00.000Z" }),
            result_type: "code_patch_apply",
            result: { updated_paths: ["README.md"] },
          };
        },
        async reject(proposalId, identity) {
          calls.push(`reject:${proposalId}:${identity.spaceId}:${identity.userId}`);
          return proposal({ id: proposalId, status: "rejected" });
        },
        async approveEgressGrantingUser(proposalId, identity, grantId) {
          calls.push(`approval:${proposalId}:${grantId}`);
          return {
            id: "approval-1",
            proposal_id: proposalId,
            approval_type: "egress_granting_user",
            approver_user_id: identity.userId,
            grant_id: grantId,
            target_space_id: identity.spaceId,
            status: "approved",
            metadata_json: {},
            created_at: "2026-06-14T10:02:00.000Z",
            revoked_at: null,
          };
        },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });

    const accept = await app.inject({
      method: "POST",
      url: "/api/v1/proposals/proposal-1/accept?confirm_incomplete_patch=true",
    });
    const reject = await app.inject({
      method: "POST",
      url: "/api/v1/proposals/proposal-2/reject",
    });
    const approval = await app.inject({
      method: "POST",
      url: "/api/v1/proposals/proposal-3/approvals/egress-granting-user",
      payload: { grant_id: "grant-1" },
    });

    expect(accept.statusCode).toBe(200);
    expect(accept.json()).toMatchObject({ result_type: "code_patch_apply" });
    expect(reject.statusCode).toBe(200);
    expect(reject.json()).toMatchObject({ id: "proposal-2", status: "rejected" });
    expect(approval.statusCode).toBe(200);
    expect(approval.json()).toMatchObject({ id: "approval-1", status: "approved" });
    expect(calls).toEqual([
      "accept:proposal-1:space-1:user-1:true",
      "reject:proposal-2:space-1:user-1",
      "approval:proposal-3:grant-1",
    ]);
  });

  it("rejects invalid incomplete code patch confirmation query values", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible() { throw new Error("should not run"); },
        async getVisible() { throw new Error("should not run"); },
      },
      applyService: {
        async accept() { throw new Error("accept should not run"); },
        async reject() { throw new Error("reject should not run"); },
        async approveEgressGrantingUser() { throw new Error("approval should not run"); },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/proposals/proposal-1/accept?confirm_incomplete_patch=maybe",
    });

    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({
      detail: expect.stringContaining("confirm_incomplete_patch"),
    });
  });

  it("returns 422 when accept is called for an unregistered proposal type (fail-closed)", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible() { throw new Error("should not run"); },
        async getVisible() { throw new Error("should not run"); },
      },
      applyService: {
        async accept() { throw new UnknownProposalApplierError("code_patch"); },
        async reject() { throw new Error("should not run"); },
        async approveEgressGrantingUser() { throw new Error("should not run"); },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });
    const res = await app.inject({ method: "POST", url: "/api/v1/proposals/proposal-1/accept" });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({ detail: expect.stringContaining("code_patch") });
  });

  it("returns 403 when the policy gate blocks apply before the applier runs", async () => {
    __setProposalIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProposalServicesFactoryForTests(() => ({
      repository: {
        async listVisible() { throw new Error("should not run"); },
        async getVisible() { throw new Error("should not run"); },
      },
      applyService: {
        async accept() {
          throw new ProposalApplyHttpError(403, { code: "policy_denied", message: "policy denied" });
        },
        async reject() { throw new Error("should not run"); },
        async approveEgressGrantingUser() { throw new Error("should not run"); },
      },
    }));
    app = buildServer(tsProposalsConfig(), { logger: false });
    const res = await app.inject({ method: "POST", url: "/api/v1/proposals/proposal-1/accept" });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ detail: { code: "policy_denied" } });
  });
});
