import { describe, expect, it } from "vitest";
import { HttpError, type SpaceUserIdentity } from "../src/modules/routeUtils/common";
import {
  enforceSourceDerivedImportTarget,
  enforceSourceRetentionPolicy,
  normalizeSourceConnectionCreateGovernance,
  normalizeSourceConnectionReadGovernance,
  normalizeSourceConnectionUpdateGovernance,
} from "../src/modules/intake/sourceConsent";
import type { SourceConnectionRow } from "../src/modules/intake/intakeRepositoryRows";

const identity: SpaceUserIdentity = { spaceId: "space-1", userId: "user-1" };

describe("source connection consent policy", () => {
  it("normalizes new connections into a conservative versioned permission model", () => {
    const governance = normalizeSourceConnectionCreateGovernance(identity, {});

    expect(governance).toMatchObject({
      capturePolicy: "reference_only",
      trustLevel: "normal",
      consent: {
        schema_version: 1,
        owner_user_id: "user-1",
        subject_user_ids: ["user-1"],
        allowed_reader_user_ids: ["user-1"],
        allowed_agent_ids: [],
        allow_space_admins: true,
        allow_local_provider_egress: false,
        allow_external_model_egress: false,
      },
      policy: {
        schema_version: 1,
        source_egress_class: "internal_only",
        retention_policy: "metadata_only",
        import_trust_level: "normal",
        derived_write_policy: "proposal_required",
        allowed_import_targets: ["activity", "source_artifact"],
        revalidation: { required: true, viewer_scoped: true },
      },
    });
  });

  it("requires explicit consent before a source policy can allow external provider egress", () => {
    expect(() =>
      normalizeSourceConnectionCreateGovernance(identity, {
        policy: { source_egress_class: "external_provider_allowed" },
      }),
    ).toThrowError(HttpError);

    expect(
      normalizeSourceConnectionCreateGovernance(identity, {
        consent: { allow_external_model_egress: true },
        policy: { source_egress_class: "external_provider_allowed" },
      }).policy.source_egress_class,
    ).toBe("external_provider_allowed");
  });

  it("rejects derived write policies that bypass proposal review", () => {
    expect(() =>
      normalizeSourceConnectionCreateGovernance(identity, {
        policy: { derived_write_policy: "direct_write" },
      }),
    ).toThrowError(HttpError);
  });

  it("keeps retention at least as broad as the capture policy on update", () => {
    expect(() =>
      normalizeSourceConnectionUpdateGovernance(identity, existingConnection(), {
        capture_policy: "extract_text",
      }),
    ).toThrowError(HttpError);

    const governance = normalizeSourceConnectionUpdateGovernance(identity, existingConnection(), {
      capture_policy: "extract_text",
      policy: { retention_policy: "full_text" },
    });
    expect(governance.capturePolicy).toBe("extract_text");
    expect(governance.policy?.retention_policy).toBe("full_text");
  });

  it("enforces source retention policy before item content escalation", () => {
    expect(() =>
      enforceSourceRetentionPolicy({ retention_policy: "metadata_only" }, "summary_only"),
    ).toThrowError(HttpError);
    expect(() =>
      enforceSourceRetentionPolicy({ retention_policy: "full_text" }, "summary_only"),
    ).not.toThrow();
  });

  it("lazy-normalizes legacy connection policy from capture policy on read", () => {
    const legacy = existingConnection({
      capture_policy: "extract_text",
      policy_json: {},
    });
    const governance = normalizeSourceConnectionReadGovernance(legacy);

    expect(governance.policy).toMatchObject({
      retention_policy: "full_text",
      source_egress_class: "internal_only",
      allowed_import_targets: ["activity", "source_artifact"],
    });
    expect(() =>
      enforceSourceRetentionPolicy(governance.policy, "full_text"),
    ).not.toThrow();
  });

  it("enforces derived import target policy for source-derived proposals", () => {
    expect(() =>
      enforceSourceDerivedImportTarget({}, "memory_proposal"),
    ).toThrowError(HttpError);
    expect(() =>
      enforceSourceDerivedImportTarget({ derived_write_policy: "disabled", allowed_import_targets: ["memory_proposal"] }, "memory_proposal"),
    ).toThrowError(HttpError);
    expect(() =>
      enforceSourceDerivedImportTarget({ allowed_import_targets: ["memory_proposal"] }, "memory_proposal"),
    ).not.toThrow();
  });
});

function existingConnection(overrides: Partial<SourceConnectionRow> = {}): SourceConnectionRow {
  return {
    id: "conn-1",
    space_id: "space-1",
    connector_id: "connector-1",
    owner_user_id: "user-1",
    credential_id: null,
    name: "Inbox",
    endpoint_url: null,
    status: "active",
    fetch_frequency: "manual",
    capture_policy: "reference_only",
    trust_level: "normal",
    topic_hints_json: null,
    consent_json: {
      schema_version: 1,
      owner_user_id: "user-1",
      subject_user_ids: ["user-1"],
      allowed_reader_user_ids: ["user-1"],
      allowed_agent_ids: [],
      allow_space_admins: true,
      allow_local_provider_egress: false,
      allow_external_model_egress: false,
    },
    policy_json: {
      schema_version: 1,
      source_egress_class: "internal_only",
      retention_policy: "metadata_only",
      import_trust_level: "normal",
      derived_write_policy: "proposal_required",
      allowed_import_targets: ["activity", "source_artifact"],
      revalidation: { required: true, viewer_scoped: true },
    },
    config_json: {},
    last_checked_at: null,
    next_check_at: null,
    schedule_rule_json: null,
    handler_kind: "built_in",
    active_handler_version_id: null,
    active_recipe_version_id: null,
    repair_status: "ok",
    last_handler_run_id: null,
    created_at: "2026-06-24T00:00:00.000Z",
    updated_at: "2026-06-24T00:00:00.000Z",
    ...overrides,
  };
}
