import { createHash, randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { basename, dirname, extname, isAbsolute, relative, resolve } from "node:path";
import type {
  RunAdapterResultEnvelope,
  RunMaterializationItemSummary,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce, type EnforceResult } from "../policy/service";
import { PostRunFinalizationService } from "./finalizationService";
import { redactEvidenceText, sanitizeEvidenceJson } from "./evidenceRedaction";
import {
  PgRunRepository,
  type Queryable,
  type RunFinalizationRecord,
  type RunRecord,
} from "./repository";
import { assertProjectInSpace } from "../projects/access";
import { loadProtocol } from "../providers/protocolRuntime";
import { insertProposalRow } from "../proposals/reviewPackets";
import { EvolutionRepository } from "../evolution/repository";
import { EvolutionSolidifier } from "../evolution/solidifier";
import {
  AgentGroupRuntimeDelegationMaterializer,
  type RuntimeDelegationMaterializerPort,
} from "../agentGroups/runtimeDelegationMaterializer";

export interface RunMaterializationResult {
  items: RunMaterializationItemSummary[];
  errors: string[];
}

type MaterializationPolicyEnforcer = (
  request: Parameters<typeof enforce>[2],
) => Promise<EnforceResult>;

interface RunFinalizer {
  finalize(runId: string, spaceId: string): Promise<RunFinalizationRecord>;
}

const SUPPORTED_PROPOSAL_TYPES = new Set([
  "memory_create",
  "memory_update",
  "memory_archive",
  "knowledge_create",
  "knowledge_update",
  "knowledge_archive",
  "claim_create",
  "claim_update",
  "claim_archive",
  "object_relation_create",
  "object_relation_delete",
  "follow_up_task",
  "code_patch",
]);

const STRUCTURED_PACKET_PROPOSAL_TYPES = new Set([
  "claim_create",
  "claim_update",
  "claim_archive",
  "object_relation_create",
  "object_relation_delete",
]);

export class RunMaterializationService {
  constructor(
    private readonly config: ServerConfig,
    private readonly db: Queryable,
    private readonly finalizer: RunFinalizer = new PostRunFinalizationService(
      new PgRunRepository(db),
      new EvolutionSolidifier(new EvolutionRepository(db)),
    ),
    policyEnforcer?: MaterializationPolicyEnforcer,
    private readonly runtimeDelegationMaterializer: RuntimeDelegationMaterializerPort =
      AgentGroupRuntimeDelegationMaterializer.fromConfig(config),
  ) {
    this.policyEnforcer =
      policyEnforcer ??
      (async (request) => enforce(this.config, await loadActionRegistry(), request));
  }

  private readonly policyEnforcer: MaterializationPolicyEnforcer;

  static fromConfig(config: ServerConfig): RunMaterializationService {
    if (!config.databaseUrl) {
      throw new Error("Run materialization requires SERVER_DATABASE_URL");
    }
    return new RunMaterializationService(config, getDbPool(config.databaseUrl));
  }

  async materializeAdapterResult(input: {
    run: RunRecord;
    adapterResult: RunAdapterResultEnvelope;
    sandbox_cwd?: string | null;
  }): Promise<RunMaterializationResult> {
    const items: RunMaterializationItemSummary[] = [];
    const errors: string[] = [];

    for (const [index, entry] of arrayValue(
      (input.adapterResult as { produced_artifact_paths?: unknown }).produced_artifact_paths,
    ).entries()) {
      const item = await this.persistProducedArtifactPath({
        run: input.run,
        entry,
        sandboxCwd: input.sandbox_cwd ?? null,
        label: `produced_artifact_path_${index}`,
      });
      collect(item, items, errors);
    }

    const output = recordValue(input.adapterResult.output_json);
    for (const [index, artifact] of arrayValue(output.artifacts).entries()) {
      const item = await this.persistOutputArtifact({
        run: input.run,
        artifact,
        adapterType: input.adapterResult.adapter_type,
        label: `output_artifact_${index}`,
      });
      collect(item, items, errors);
    }

    for (const [index, proposal] of arrayValue(output.proposed_changes).entries()) {
      const item = await this.persistProposal({
        run: input.run,
        proposal,
        adapterType: input.adapterResult.adapter_type,
        label: `output_proposal_${index}`,
      });
      collect(item, items, errors);
    }

    for (const [index] of arrayValue(output.activities).entries()) {
      const item: RunMaterializationItemSummary = {
        kind: "activity",
        status: "failed",
        error_code: "output_activity_materialization_error",
        error_message: "Activity materialization is intentionally deferred in the server backend.",
        metadata_json: { label: `output_activity_${index}` },
      };
      collect(item, items, errors);
    }

    const delegationResult = await this.runtimeDelegationMaterializer.materialize({
      run: input.run,
      output_json: output,
    });
    items.push(...delegationResult.items);
    errors.push(...delegationResult.errors);

    return { items, errors };
  }

  async finalizeRun(run: RunRecord): Promise<RunMaterializationItemSummary> {
    try {
      const finalization = await this.finalizer.finalize(run.id, run.space_id);
      return {
        kind: "activity",
        status: "succeeded",
        activity_id: finalization.id,
        metadata_json: {
          operation: "finalization.finalize",
          run_finalization_id: finalization.id,
          run_evaluation_id: finalization.run_evaluation_id,
          task_evaluation_id: finalization.task_evaluation_id,
          finalizer_version: finalization.finalizer_version,
        },
      };
    } catch (error) {
      return {
        kind: "activity",
        status: "failed",
        error_code: "finalization_failed",
        error_message: error instanceof Error ? error.message : "Run finalization failed.",
        metadata_json: { operation: "finalization.finalize" },
      };
    }
  }

  private async persistProducedArtifactPath(input: {
    run: RunRecord;
    entry: unknown;
    sandboxCwd: string | null;
    label: string;
  }): Promise<RunMaterializationItemSummary> {
    try {
      if (!input.sandboxCwd) {
        throw new Error("sandbox_cwd is required for produced_artifact_paths");
      }
      const sourcePath = producedPath(input.entry);
      if (!sourcePath) throw new Error("produced artifact entry is missing a path");
      if (sourcePath.includes("\0") || isAbsolute(sourcePath)) {
        throw new Error("produced artifact path must be relative to the sandbox");
      }
      const sandboxRoot = resolve(input.sandboxCwd);
      const absoluteSource = resolve(sandboxRoot, sourcePath);
      if (!isInside(absoluteSource, sandboxRoot)) {
        throw new Error("produced artifact path escapes the sandbox");
      }
      const info = await stat(absoluteSource);
      if (!info.isFile()) {
        throw new Error("produced artifact path must reference a regular file");
      }
      const extension = safeExtension(extname(sourcePath));
      const fileId = randomUUID();
      const relativePath = `${safeSegment(input.run.space_id)}/runs/${safeSegment(input.run.id)}/${fileId}${extension}`;
      const absoluteTarget = resolve(this.config.artifactStorageRoot, relativePath);
      await mkdir(dirname(absoluteTarget), { recursive: true });
      await copyFile(absoluteSource, absoluteTarget);
      const bytes = await readFile(absoluteTarget);
      const metadata = {
        source: "produced_artifact_paths",
        source_path: relative(sandboxRoot, absoluteSource),
        size_bytes: info.size,
        sha256: createHash("sha256").update(bytes).digest("hex"),
      };
      const entryRecord = recordValue(input.entry);
      const artifactId = await this.insertArtifact({
        run: input.run,
        artifactType: stringValue(entryRecord.artifact_type) ?? "adapter_file",
        title: stringValue(entryRecord.title) ?? basename(sourcePath),
        content: null,
        storagePath: relativePath,
        mimeType: stringValue(entryRecord.mime_type) ?? "application/octet-stream",
        preview: booleanValue(entryRecord.preview) ?? false,
        metadata,
      });
      return {
        kind: "artifact",
        status: "succeeded",
        artifact_id: artifactId,
        metadata_json: { label: input.label, operation: "artifact.persist", ...metadata },
      };
    } catch (error) {
      return materializationError("artifact", input.label, "output_artifact_materialization_error", error);
    }
  }

  private async persistOutputArtifact(input: {
    run: RunRecord;
    artifact: unknown;
    adapterType: string;
    label: string;
  }): Promise<RunMaterializationItemSummary> {
    try {
      const spec = recordValue(input.artifact);
      const content = stringValue(spec.content);
      if (content === null) throw new Error("output artifact content is required");
      const artifactId = await this.insertArtifact({
        run: input.run,
        artifactType: stringValue(spec.artifact_type) ?? "adapter_output",
        title: stringValue(spec.title) ?? `Adapter artifact (${input.adapterType})`,
        content,
        storagePath: null,
        mimeType: stringValue(spec.mime_type) ?? "text/plain; charset=utf-8",
        preview: booleanValue(spec.preview) ?? input.run.mode === "dry_run",
        visibility: normalizeArtifactVisibility(stringValue(spec.visibility)),
        workspaceId: stringValue(spec.workspace_id) ?? input.run.workspace_id,
        metadata: {
          source: "adapter_output",
          adapter_type: input.adapterType,
          ...recordValue(spec.metadata_json),
        },
      });
      return {
        kind: "artifact",
        status: "succeeded",
        artifact_id: artifactId,
        metadata_json: { label: input.label, operation: "artifact.persist" },
      };
    } catch (error) {
      return materializationError("artifact", input.label, "output_artifact_materialization_error", error);
    }
  }

  private async persistProposal(input: {
    run: RunRecord;
    proposal: unknown;
    adapterType: string;
    label: string;
  }): Promise<RunMaterializationItemSummary> {
    try {
      const spec = recordValue(input.proposal);
      const proposalType = stringValue(spec.proposal_type) ?? stringValue(spec.type);
      if (!proposalType) throw new Error("proposal_type is required");
      if (!SUPPORTED_PROPOSAL_TYPES.has(proposalType)) {
        throw new Error(`unsupported proposal_type ${JSON.stringify(proposalType)}`);
      }
      const payload = proposalPayload(spec, proposalType, input.run, STRUCTURED_PACKET_PROPOSAL_TYPES.has(proposalType));
      if (proposalType === "code_patch") validateCodePatchPayload(payload);
      if (STRUCTURED_PACKET_PROPOSAL_TYPES.has(proposalType)) {
        await validateClaimObjectProposalPacket(proposalType, payload);
      }
      const projectId = stringValue(spec.project_id)
        ?? stringValue(payload.project_id)
        ?? input.run.project_id;
      await assertProjectInSpace(this.db, input.run.space_id, projectId);
      if (projectId) payload.project_id = projectId;
      else delete payload.project_id;

      const policy = await this.policyEnforcer({
        action: "proposal.create",
        actor_type: "run",
        actor_id: input.run.id,
        space_id: input.run.space_id,
        resource_type: "proposal",
        resource_space_id: input.run.space_id,
        run_id: input.run.id,
        context: {
          proposal_type: proposalType,
          workspace_id: stringValue(spec.workspace_id) ?? input.run.workspace_id,
          adapter_type: input.adapterType,
        },
        metadata_json: {
          proposal_type: proposalType,
          adapter_type: input.adapterType,
          label: input.label,
        },
        force_record: true,
      });
      if (policy.status !== "allow") {
        throw new Error(policy.message ?? policy.error_code ?? "proposal.create denied by policy");
      }

      const proposalId = await this.insertProposal({
        run: input.run,
        proposalType,
        title: stringValue(spec.title) ?? stringValue(spec.proposed_title) ?? titleForProposal(proposalType),
        summary: stringValue(spec.summary),
        payload,
        rationale: stringValue(spec.rationale) ?? `Proposed by run output (${input.adapterType}).`,
        riskLevel: normalizeRisk(stringValue(spec.risk_level), proposalType),
        urgency: normalizeUrgency(stringValue(spec.urgency)),
        preview: booleanValue(spec.preview) ?? input.run.mode === "dry_run",
        visibility: normalizeVisibility(stringValue(spec.visibility)),
        workspaceId: stringValue(spec.workspace_id) ?? input.run.workspace_id,
        projectId,
      });
      return {
        kind: "proposal",
        status: "succeeded",
        proposal_id: proposalId,
        metadata_json: {
          label: input.label,
          operation: "proposal.create",
          proposal_type: proposalType,
        },
      };
    } catch (error) {
      return materializationError("proposal", input.label, "output_proposal_materialization_error", error);
    }
  }

  private async insertArtifact(input: {
    run: RunRecord;
    artifactType: string;
    title: string;
    content: string | null;
    storagePath: string | null;
    mimeType: string;
    preview: boolean;
    visibility?: string;
    workspaceId?: string | null;
    metadata: Record<string, unknown>;
  }): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const workspaceId = input.workspaceId ?? input.run.workspace_id ?? null;
    const visibility = input.visibility ?? "space_shared";
    const policy = await this.policyEnforcer({
      action: "artifact.persist",
      actor_type: "run",
      actor_id: input.run.id,
      space_id: input.run.space_id,
      resource_type: "artifact",
      resource_id: id,
      resource_space_id: input.run.space_id,
      run_id: input.run.id,
      context: {
        artifact_type: input.artifactType,
        title: input.title,
        mime_type: input.mimeType,
        visibility,
        workspace_id: workspaceId,
        project_id: input.run.project_id ?? null,
        storage_path: input.storagePath,
        content_inline: input.content !== null,
      },
      metadata_json: {
        artifact_type: input.artifactType,
        visibility,
        workspace_id: workspaceId,
      },
      force_record: true,
    });
    if (policy.status !== "allow") {
      throw new Error(policy.message ?? policy.error_code ?? "artifact.persist denied by policy");
    }
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, run_id, proposal_id, artifact_type, title, content,
         storage_ref, storage_path, mime_type, exportable, export_formats_json,
         canonical_format, preview, relevant_period_start, relevant_period_end,
         created_at, updated_at, metadata_json, visibility, owner_user_id,
         trust_level, project_id, workspace_id
       ) VALUES (
         $1, $2, $3, NULL, $4, $5, $6,
         NULL, $7, $8, true, $9::jsonb,
         NULL, $10, NULL, NULL,
         $11, $11, $12::jsonb, $13, $14,
         'medium', $15, $16
       )`,
      [
        id,
        input.run.space_id,
        input.run.id,
        input.artifactType,
        input.title,
        input.content,
        input.storagePath,
        input.mimeType,
        JSON.stringify([input.mimeType]),
        input.preview,
        now,
        JSON.stringify(sanitizeEvidenceJson(input.metadata)),
        visibility,
        input.run.instructed_by_user_id ?? null,
        input.run.project_id ?? null,
        workspaceId,
      ],
    );
    return id;
  }

  private async insertProposal(input: {
    run: RunRecord;
    proposalType: string;
    title: string;
    summary: string | null;
    payload: Record<string, unknown>;
    rationale: string;
    riskLevel: string;
    urgency: string;
    preview: boolean;
    visibility: string;
    workspaceId: string | null;
    projectId: string | null;
  }): Promise<string> {
    const row = await insertProposalRow(this.db, {
      spaceId: input.run.space_id,
      createdByRunId: input.run.id,
      proposalType: input.proposalType,
      title: input.title,
      summary: input.summary,
      payload: input.payload,
      rationale: input.rationale,
      riskLevel: input.riskLevel,
      urgency: input.urgency,
      preview: input.preview,
      visibility: input.visibility,
      workspaceId: input.workspaceId,
      projectId: input.projectId,
      createdByAgentId: input.run.agent_id ?? null,
      createdByUserId: input.run.instructed_by_user_id ?? null,
    });
    return row.id;
  }
}

function collect(
  item: RunMaterializationItemSummary,
  items: RunMaterializationItemSummary[],
  errors: string[],
): void {
  items.push(item);
  if (item.status === "failed" || item.status === "warning" || item.status === "skipped") {
    errors.push(
      `${item.kind}:${item.error_code ?? item.status}:${redactEvidenceText(item.error_message) ?? ""}`,
    );
  }
}

function materializationError(
  kind: "artifact" | "proposal",
  label: string,
  code: string,
  error: unknown,
): RunMaterializationItemSummary {
  return {
    kind,
    status: "failed",
    error_code: code,
    error_message: error instanceof Error ? error.message : `${label} materialization failed.`,
    metadata_json: {
      label,
      operation: kind === "artifact" ? "artifact.persist" : "proposal.create",
    },
  };
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function producedPath(entry: unknown): string | null {
  if (typeof entry === "string" && entry.trim()) return entry.trim();
  const record = recordValue(entry);
  return (
    stringValue(record.path) ??
    stringValue(record.relative_path) ??
    stringValue(record.file_path)
  );
}

function proposalPayload(
  spec: Record<string, unknown>,
  proposalType: string,
  run: RunRecord,
  requireStructuredPayload = false,
): Record<string, unknown> {
  const explicit = recordValue(spec.payload_json);
  const alternate = recordValue(spec.payload);
  const payload = Object.keys(explicit).length > 0
    ? { ...explicit }
    : Object.keys(alternate).length > 0
      ? { ...alternate }
      : requireStructuredPayload
        ? null
        : stripProposalEnvelope(spec);
  if (!payload) {
    throw new Error(`${proposalType} requires structured payload_json or payload`);
  }
  payload.source_run_id = stringValue(payload.source_run_id) ?? run.id;
  payload.created_by_run_id = stringValue(payload.created_by_run_id) ?? run.id;
  payload.proposal_type = stringValue(payload.proposal_type) ?? proposalType;
  if (run.project_id && payload.project_id === undefined) payload.project_id = run.project_id;
  return payload;
}

async function validateClaimObjectProposalPacket(
  proposalType: string,
  payload: Record<string, unknown>,
): Promise<void> {
  const protocol = await loadProtocol();
  const parsed = protocol.ClaimObjectProposalPayloadSchema.safeParse(payload);
  if (!parsed.success) {
    throw new Error(`invalid structured ${proposalType} packet: ${formatZodIssues(parsed.error.issues)}`);
  }
  if (parsed.data.operation !== proposalType) {
    throw new Error(`structured packet operation ${JSON.stringify(parsed.data.operation)} does not match proposal_type ${JSON.stringify(proposalType)}`);
  }
}

function formatZodIssues(issues: Array<{ path: Array<string | number>; message: string }>): string {
  return issues
    .map((issue) => `${issue.path.length > 0 ? issue.path.join(".") : "(root)"}: ${issue.message}`)
    .join("; ");
}

function stripProposalEnvelope(spec: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  const envelope = new Set([
    "proposal_type",
    "type",
    "title",
    "proposed_title",
    "summary",
    "rationale",
    "risk_level",
    "urgency",
    "preview",
    "visibility",
    "workspace_id",
    "project_id",
  ]);
  for (const [key, value] of Object.entries(spec)) {
    if (!envelope.has(key)) payload[key] = value;
  }
  return payload;
}

function validateCodePatchPayload(payload: Record<string, unknown>): void {
  const patch = recordValue(payload.patch);
  const operations = patch.operations;
  if (!Array.isArray(operations) || operations.length === 0) {
    throw new Error("code_patch proposal requires patch.operations");
  }
}

function normalizeRisk(value: string | null, proposalType: string): string {
  if (value && ["low", "medium", "high", "critical"].includes(value)) return value;
  if (proposalType === "code_patch") return "high";
  return "medium";
}

function normalizeUrgency(value: string | null): string {
  return value && ["low", "normal", "high", "critical"].includes(value)
    ? value
    : "normal";
}

function normalizeVisibility(value: string | null): string {
  return value && ["space_shared", "workspace_shared", "selected_users", "restricted"].includes(value)
    ? value
    : "space_shared";
}

function normalizeArtifactVisibility(value: string | null): string {
  return value && ["private", "space_shared", "workspace_shared", "selected_users", "restricted"].includes(value)
    ? value
    : "space_shared";
}

function titleForProposal(proposalType: string): string {
  return proposalType
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function isInside(path: string, root: string): boolean {
  return path === root || path.startsWith(root.endsWith("/") ? root : `${root}/`);
}

function safeSegment(value: string): string {
  return value.replace(/[^a-zA-Z0-9_.-]/g, "_");
}

function safeExtension(value: string): string {
  return value && /^[.][a-zA-Z0-9_-]{1,16}$/.test(value) ? value : "";
}
