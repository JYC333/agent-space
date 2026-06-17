import { createHash } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce } from "../policy/service";
import { ContextCompiler, type CompiledContext } from "./compiler";
import {
  PgRunContextRepository,
  buildContextPackage,
  type ContextDigestRow,
  type DigestBundle,
  type RunContextRecord,
} from "./repository";
import type { ContextPackage, PolicyCheckRequest } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};

const COMPILER_VERSION = "context_digest.v1";
const STABLE_PREFIX_BUDGET_CHARS = 64_000;

const PERSONAL_CONTEXT_HEADER =
  "[Personal context granted for this run - reasoning only]";
const PERSONAL_CONTEXT_WARNING =
  "This personal context is granted for reasoning only. Do not quote or persist it directly.";
const PERSONAL_CONTEXT_FOOTER = "[End personal context]";

export interface ContextPrepareInput {
  runId: string;
  spaceId: string;
  adapterType: string | null;
  sandboxCwd: string | null;
  targetFormat: string | null;
  workspacePath: string | null;
}

export interface ContextPrepareResult {
  runtime_prompt: string;
  context_snapshot_id: string | null;
  context_rendered: boolean;
  target_format?: string | null;
  instruction_file_path?: string | null;
  total_chars?: number;
  budget_chars?: number;
  dropped_sections?: string[];
}

export class ContextPrepareError extends Error {
  constructor(
    readonly code:
      | "run_not_found"
      | "policy_denied"
      | "policy_requires_approval"
      | "policy_audit_persist_failed"
      | "context_prepare_failed",
    message: string,
  ) {
    super(message);
    this.name = "ContextPrepareError";
  }
}

export class ContextPrepareService {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly repository = PgRunContextRepository.fromConfig(config),
    private readonly compiler = new ContextCompiler(),
  ) {}

  async prepare(input: ContextPrepareInput): Promise<ContextPrepareResult> {
    try {
      return await this.repository.withTransaction(async (repo) => {
        const run = await repo.loadRun(input.spaceId, input.runId);
        if (!run) {
          throw new ContextPrepareError(
            "run_not_found",
            "Run not found in this space.",
          );
        }
        if (!run.context_snapshot_id) {
          throw new ContextPrepareError(
            "context_prepare_failed",
            `Run ${run.id} has no ContextSnapshot; execution blocked to preserve auditability.`,
          );
        }

        await this.enforceContextInjectMemory(run);

        const userId = run.instructed_by_user_id || "system";
        const memoryPolicy = recordValue(run.memory_policy_json);
        const includeSystemScope =
          Object.keys(memoryPolicy).length === 0 ||
          arrayOfStrings(memoryPolicy.readable_scopes).includes("system");
        const retrieval = await repo.retrieve({
          spaceId: run.space_id,
          userId,
          workspaceId: run.workspace_id,
          agentId: run.agent_id,
          query: run.prompt,
          agentMemoryPolicy: memoryPolicy,
          includeSystemScope,
        });
        await repo.recordContextMemoryAccess({
          memories: retrieval.memories,
          spaceId: run.space_id,
          userId,
          agentId: run.agent_id,
          runId: run.id,
          reason: `run_execution:${run.id}`,
        });

        const sessionSummary = await repo.loadLatestSessionSummary(
          run.space_id,
          run.session_id,
        );
        await this.enforceContextSelectEvidence(run);
        const evidenceSelections = await repo.selectEvidenceForContext({
          spaceId: run.space_id,
          workspaceId: run.workspace_id,
          projectId: run.project_id,
          runId: run.id,
        });
        const pkg = buildContextPackage({
          memories: retrieval.memories,
          activePolicies: retrieval.activePolicies,
          sourceRefs: retrieval.sourceRefs,
          retrievalTrace: retrieval.retrievalTrace,
          tokenBudget: retrieval.tokenBudget,
          userId,
          spaceId: run.space_id,
          workspaceId: run.workspace_id,
          sessionSummary,
          evidenceSelections,
        });

        const { digestBundle, digestTrace } = await loadDigestTrace(repo, run);
        const stableText = renderStablePrefix(pkg, run, digestBundle);
        const tailText = renderDynamicTail(pkg, run);
        const tokenBudget = buildTokenBudget(stableText, tailText);
        const sourceRefs: Record<string, unknown>[] = [...pkg.source_refs];
        sourceRefs.push(...digestSourceRefs(digestBundle));

        const retrievalTrace: Record<string, unknown> = {
          ...recordValue(pkg.retrieval_trace),
          token_budget: tokenBudget,
          ...digestTrace,
        };

        const grant = await repo.resolvePersonalGrantForRun(run);
        if (grant.metadata) {
          pkg.personal_context_block = grant.personal_context_block;
          sourceRefs.push({
            source_type: "personal_memory_grant",
            grant_id: grant.metadata.grant_id,
            granting_user_id: grant.metadata.granting_user_id,
            personal_space_id: grant.metadata.personal_space_id,
            target_space_id: grant.metadata.target_space_id,
            access_mode: grant.metadata.access_mode,
            memory_count: grant.metadata.memory_count,
            raw_memory_included: false,
            personal_summary_persisted: false,
            section: "ephemeral",
          });
          retrievalTrace.personal_memory_grant = {
            grant_id: grant.metadata.grant_id,
            access_mode: grant.metadata.access_mode,
            memory_count: grant.metadata.memory_count,
            raw_memory_included: false,
            personal_summary_persisted: false,
          };
          await repo.markRunPersonalGrantContext({
            runId: run.id,
            spaceId: run.space_id,
            metadata: grant.metadata,
          });
        } else {
          retrievalTrace.personal_memory_grant = null;
        }

        await repo.updateSnapshot({
          snapshotId: run.context_snapshot_id,
          spaceId: run.space_id,
          sourceRefs,
          includedEvidenceRefs: sourceRefs.filter((ref) => ref.source_type === "evidence"),
          retrievalTrace: [retrievalTrace],
          tokenBudget,
          compiledPrefixText: stableText,
          compiledTailText: tailText,
          prefixHash: sha256(stableText),
          tailHash: sha256(tailText),
          compilerVersion: COMPILER_VERSION,
          tokenEstimate: Math.floor((stableText.length + tailText.length) / 4),
          policyBundleVersion: digestBundle.policy_bundle
            ? String(digestBundle.policy_bundle.version)
            : null,
          workspaceDigestVersion: digestBundle.workspace
            ? String(digestBundle.workspace.version)
            : null,
        });

        await this.enforceContextRender(run, input.adapterType);

        const composedRuntimePrompt = composeRuntimePrompt(
          run.prompt ?? "",
          pkg.personal_context_block,
        );
        let compiled: CompiledContext | null = null;
        if (input.sandboxCwd && input.targetFormat) {
          compiled = await this.compiler.compile({
            context: pkg,
            target: input.targetFormat,
            taskGoal: composedRuntimePrompt,
            sandboxDir: input.sandboxCwd,
            workspacePath: input.workspacePath,
          });
        }

        return {
          runtime_prompt: composedRuntimePrompt,
          context_snapshot_id: run.context_snapshot_id,
          context_rendered: compiled !== null,
          target_format: compiled?.target ?? null,
          instruction_file_path: compiled?.instruction_file_path ?? null,
          total_chars: compiled?.total_chars,
          budget_chars: compiled?.budget_chars,
          dropped_sections: compiled?.dropped_sections,
        };
      });
    } catch (error) {
      if (error instanceof ContextPrepareError) throw error;
      throw new ContextPrepareError(
        "context_prepare_failed",
        `Context preparation failed: ${error instanceof Error ? error.message : String(error)}`.slice(
          0,
          1000,
        ),
      );
    }
  }

  private async enforceContextInjectMemory(run: RunContextRecord): Promise<void> {
    await enforcePolicyOrThrow(this.config, {
      action: "context.inject_memory",
      force_record: false,
      actor_type: "run",
      actor_id: run.id,
      space_id: run.space_id,
      resource_type: "memory",
      run_id: run.id,
      context: {
        trigger_origin: run.trigger_origin ?? "manual",
      },
      metadata_json: {
        agent_id: run.agent_id,
        workspace_id: run.workspace_id,
        data_exposure_level: run.data_exposure_level,
        trust_level: run.trust_level,
        has_personal_grant_context: Boolean(run.has_personal_grant_context),
      },
    });
  }

  private async enforceContextRender(
    run: RunContextRecord,
    adapterType: string | null,
  ): Promise<void> {
    await enforcePolicyOrThrow(this.config, {
      action: "context.render_for_runtime",
      force_record: false,
      actor_type: "run",
      actor_id: run.id,
      space_id: run.space_id,
      resource_type: "context",
      resource_id: run.context_snapshot_id,
      run_id: run.id,
      context: {
        has_personal_grant_context: Boolean(run.has_personal_grant_context),
      },
      metadata_json: {
        context_snapshot_id: run.context_snapshot_id,
        adapter_type: adapterType,
        data_exposure_level: run.data_exposure_level,
        trust_level: run.trust_level,
      },
    });
  }

  private async enforceContextSelectEvidence(run: RunContextRecord): Promise<void> {
    await enforcePolicyOrThrow(this.config, {
      action: "context.select_evidence",
      force_record: false,
      actor_type: "run",
      actor_id: run.id,
      space_id: run.space_id,
      resource_type: "evidence",
      run_id: run.id,
      context: {
        workspace_id: run.workspace_id,
        project_id: run.project_id,
      },
      metadata_json: {
        workspace_id: run.workspace_id,
        project_id: run.project_id,
      },
    });
  }
}

async function enforcePolicyOrThrow(
  config: ControlPlaneConfig,
  request: PolicyCheckRequest,
): Promise<void> {
  const registry = await loadActionRegistry();
  const result = await enforce(config, registry, request);
  if (result.status === "allow") return;
  throw new ContextPrepareError(
    result.error_code ?? "policy_denied",
    result.message ?? "Policy denied context preparation.",
  );
}

async function loadDigestTrace(
  repo: PgRunContextRepository,
  run: RunContextRecord,
): Promise<{
  digestBundle: DigestBundle;
  digestTrace: Record<string, unknown>;
}> {
  try {
    const digestBundle = await repo.loadDigestBundle({
      spaceId: run.space_id,
      workspaceId: run.workspace_id,
      agentId: run.agent_id,
    });
    if (digestUsed(digestBundle)) {
      return {
        digestBundle,
        digestTrace: {
          digest_used: true,
          digest_ids: allDigests(digestBundle).map((d) => d.id),
          digest_types: allDigests(digestBundle).map((d) => d.digest_type),
          digest_versions: allDigests(digestBundle).map((d) => Number(d.version)),
          dirty_digest_used: allDigests(digestBundle).some((d) => d.status === "dirty"),
          fallback_to_memory_retriever: false,
          digest_fallback_reason: null,
        },
      };
    }
    return {
      digestBundle,
      digestTrace: {
        digest_used: false,
        fallback_to_memory_retriever: true,
        digest_fallback_reason: "no_digest_available",
      },
    };
  } catch (error) {
    return {
      digestBundle: { policy_bundle: null, workspace: null, agent: null },
      digestTrace: {
        digest_used: false,
        fallback_to_memory_retriever: true,
        digest_fallback_reason: "load_error",
        digest_load_error: `${error instanceof Error ? error.name : "Error"}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      },
    };
  }
}

function renderStablePrefix(
  pkg: ContextPackage,
  run: RunContextRecord,
  digestBundle: DigestBundle,
): string {
  const parts: string[] = [];
  if (run.system_prompt?.trim()) {
    parts.push(`[system_prompt]\n${run.system_prompt.trim()}`);
  }
  if (digestUsed(digestBundle)) {
    for (const digest of allDigests(digestBundle)) {
      if (digest.content?.trim()) {
        parts.push(`[digest:${digest.digest_type}:v${digest.version}]\n${digest.content.trim()}`);
      }
    }
  } else {
    for (const policy of pkg.active_policies) {
      const p = recordValue(policy);
      const name = stringValue(p.name) ?? stringValue(p.id) ?? "policy";
      const domain = stringValue(p.domain) ?? "";
      parts.push(`[policy:${domain}:${name}]\n${JSON.stringify(recordValue(p.policy_json))}`);
    }
  }

  const stableIds = new Set(
    pkg.stable_prefix_refs
      .filter((r) => r.source_type === "memory" && typeof r.source_id === "string")
      .map((r) => r.source_id as string),
  );
  const sections = [
    pkg.system_policy,
    pkg.user_memory,
    pkg.workspace_memory,
    pkg.capability_memory,
    pkg.agent_memory,
  ];
  for (const section of sections) {
    for (const memory of section) {
      if (!stableIds.has(memory.id)) continue;
      const title = memory.title ?? "";
      const content = memory.content ?? "";
      parts.push(`[memory:${memory.id}:${title}]\n${content}`);
    }
  }
  return parts.join("\n\n").slice(0, STABLE_PREFIX_BUDGET_CHARS);
}

function renderDynamicTail(pkg: ContextPackage, run: RunContextRecord): string {
  const parts: string[] = [];
  const dynamicIds = new Set(
    pkg.dynamic_tail_refs
      .filter((r) => r.source_type === "memory" && typeof r.source_id === "string")
      .map((r) => r.source_id as string),
  );
  for (const memory of pkg.relevant_episodes) {
    if (dynamicIds.size > 0 && !dynamicIds.has(memory.id)) continue;
    parts.push(`[episode:${memory.id}:${memory.title ?? ""}]\n${memory.content ?? ""}`);
  }
  if (run.prompt?.trim()) {
    parts.push(`[prompt]\n${run.prompt.trim()}`);
  }
  for (const evidence of pkg.evidence_items) {
    const ev = recordValue(evidence);
    const excerpt = stringValue(ev.content_excerpt);
    if (!excerpt) continue;
    parts.push(
      `[evidence:${stringValue(ev.id) ?? ""}:${stringValue(ev.title) ?? "evidence"}]\n${excerpt}`,
    );
  }
  return parts.join("\n\n");
}

function buildTokenBudget(
  stableText: string,
  tailText: string,
): Record<string, unknown> {
  const stableChars = stableText.length;
  const tailChars = tailText.length;
  const totalChars = stableChars + tailChars;
  const stablePct = Math.round((stableChars / Math.max(totalChars, 1)) * 1000) / 10;
  const budget: Record<string, unknown> = {
    stable_prefix_chars: stableChars,
    dynamic_tail_chars: tailChars,
    total_chars: totalChars,
    stable_prefix_budget_chars: STABLE_PREFIX_BUDGET_CHARS,
    stable_prefix_pct: stablePct,
    stable_prefix_target_pct: 50,
    compiler_version: COMPILER_VERSION,
  };
  if (stablePct > 50) {
    budget.stable_prefix_warning =
      `stable_prefix occupies ${stablePct}% of total context (target <= 50%); truncation and digest-based compaction are not yet implemented`;
  }
  return budget;
}

function digestSourceRefs(bundle: DigestBundle): Record<string, unknown>[] {
  return allDigests(bundle).map((digest) => ({
    source_type: "context_digest",
    source_id: digest.id,
    digest_type: digest.digest_type,
    digest_version: Number(digest.version),
    section: "stable_prefix",
    source_memory_ids: arrayValue(digest.source_memory_ids_json),
    source_policy_ids: arrayValue(digest.source_policy_ids_json),
    source_relation_ids: arrayValue(digest.source_relation_ids_json),
    source_hash: digest.source_hash,
    content_hash: digest.content_hash,
    status: digest.status,
  }));
}

function digestUsed(bundle: DigestBundle): boolean {
  return allDigests(bundle).length > 0;
}

function allDigests(bundle: DigestBundle): ContextDigestRow[] {
  return [bundle.policy_bundle, bundle.workspace, bundle.agent].filter(
    (row): row is ContextDigestRow => row !== null,
  );
}

function composeRuntimePrompt(userPrompt: string, personalContextBlock: string): string {
  const block = personalContextBlock.trim();
  if (!block) return userPrompt;
  return [
    userPrompt,
    PERSONAL_CONTEXT_HEADER,
    PERSONAL_CONTEXT_WARNING,
    block,
    PERSONAL_CONTEXT_FOOTER,
  ].join("\n\n");
}

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function arrayOfStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
