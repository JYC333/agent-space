import type {
  RunAdapterResultEnvelope,
  RunMaterializationItemSummary,
  RunPythonContextPortRequest,
  RunPythonContextPortResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { RunRecord } from "./repository";
import { redactEvidenceText, sanitizeEvidenceJson } from "./evidenceRedaction";

export interface RunMaterializationPortClient {
  call(request: RunPythonContextPortRequest): Promise<RunPythonContextPortResponse>;
  finalizeRun(runId: string, spaceId: string): Promise<RunPythonContextPortResponse>;
}

export interface RunMaterializationResult {
  items: RunMaterializationItemSummary[];
  errors: string[];
}

export class RunMaterializationService {
  constructor(private readonly ports: RunMaterializationPortClient) {}

  async materializeAdapterResult(input: {
    run: RunRecord;
    adapterResult: RunAdapterResultEnvelope;
    sandbox_cwd?: string | null;
  }): Promise<RunMaterializationResult> {
    const items: RunMaterializationItemSummary[] = [];
    const errors: string[] = [];

    // Port payloads carry the material to persist, not trace evidence: specs
    // and output text go through intact (the request schema still rejects
    // secret-bearing keys, and Python applies its own artifact redaction).
    // Evidence sanitization is applied to summaries/events, never here —
    // otherwise code patches and long outputs would be destroyed in transit.
    if (input.adapterResult.success && input.adapterResult.output_text) {
      const item = await this.callPort({
        operation: "artifact.persist",
        run: input.run,
        kind: "artifact",
        label: "runtime_output",
        payload_json: {
          artifact_type: "runtime_output",
          title: `Run output (${input.adapterResult.adapter_type})`,
          text: input.adapterResult.output_text,
          preview: input.run.mode === "dry_run",
        },
      });
      collect(item, items, errors);
    }

    for (const [index, entry] of arrayValue(
      (input.adapterResult as { produced_artifact_paths?: unknown }).produced_artifact_paths,
    ).entries()) {
      const item = await this.callPort({
        operation: "artifact.persist",
        run: input.run,
        kind: "artifact",
        label: `produced_artifact_path_${index}`,
        payload_json: {
          source: "produced_artifact_paths",
          entry: entry as Record<string, unknown> | string,
          sandbox_cwd: input.sandbox_cwd ?? null,
        },
      });
      collect(item, items, errors);
    }

    const output = recordValue(input.adapterResult.output_json);
    for (const [index, artifact] of arrayValue(output.artifacts).entries()) {
      const item = await this.callPort({
        operation: "artifact.persist",
        run: input.run,
        kind: "artifact",
        label: `output_artifact_${index}`,
        payload_json: {
          source: "adapter_output",
          adapter_type: input.adapterResult.adapter_type,
          spec: artifact as Record<string, unknown>,
        },
      });
      collect(item, items, errors);
    }

    for (const [index, proposal] of arrayValue(output.proposed_changes).entries()) {
      const item = await this.callPort({
        operation: "proposal.create",
        run: input.run,
        kind: "proposal",
        label: `output_proposal_${index}`,
        payload_json: {
          source: "adapter_output",
          adapter_type: input.adapterResult.adapter_type,
          spec: proposal as Record<string, unknown>,
        },
      });
      collect(item, items, errors);
    }

    for (const [index] of arrayValue(output.activities).entries()) {
      const item: RunMaterializationItemSummary = {
        kind: "activity",
        status: "failed",
        error_code: "output_activity_materialization_error",
        error_message: "Activity materialization remains Python-owned and has no Stage 4 port.",
        metadata_json: { label: `output_activity_${index}` },
      };
      collect(item, items, errors);
    }

    return { items, errors };
  }

  async finalizeRun(run: RunRecord): Promise<RunMaterializationItemSummary> {
    try {
      const response = await this.ports.finalizeRun(run.id, run.space_id);
      const resultJson = recordValue(response.result_json);
      if (response.status === "succeeded") {
        return {
          kind: "activity",
          status: "succeeded",
          activity_id: stringValue(resultJson.run_finalization_id),
          metadata_json: sanitizeEvidenceJson(resultJson) as RunMaterializationItemSummary["metadata_json"],
        };
      }
      return {
        kind: "activity",
        status: "failed",
        error_code: response.error_code ?? "finalization_failed",
        error_message: response.message ?? "Run finalization failed.",
        metadata_json: {
          operation: "finalization.finalize",
          port_status: response.status,
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

  private async callPort(input: {
    operation: "artifact.persist" | "proposal.create";
    run: RunRecord;
    kind: "artifact" | "proposal";
    label: string;
    payload_json: Record<string, unknown>;
  }): Promise<RunMaterializationItemSummary> {
    try {
      const response = await this.ports.call({
        operation: input.operation,
        run_id: input.run.id,
        space_id: input.run.space_id,
        payload_json: {
          ...input.payload_json,
          run_id: input.run.id,
          workspace_id: input.run.workspace_id,
          project_id: input.run.project_id,
          label: input.label,
        } as RunPythonContextPortRequest["payload_json"],
      });
      const resultJson = recordValue(response.result_json);
      const id = stringValue(
        input.kind === "artifact"
          ? resultJson.artifact_id
          : resultJson.proposal_id,
      );
      if (response.status === "succeeded") {
        return {
          kind: input.kind,
          status: "succeeded",
          artifact_id: input.kind === "artifact" ? id : null,
          proposal_id: input.kind === "proposal" ? id : null,
          metadata_json: {
            label: input.label,
            operation: input.operation,
          },
        };
      }
      return {
        kind: input.kind,
        status: response.status === "not_implemented" ? "skipped" : "failed",
        error_code:
          response.error_code ??
          (input.kind === "artifact"
            ? "output_artifact_materialization_error"
            : "output_proposal_materialization_error"),
        error_message: response.message ?? `${input.operation} did not succeed.`,
        metadata_json: {
          label: input.label,
          operation: input.operation,
          port_status: response.status,
        },
      };
    } catch (error) {
      return {
        kind: input.kind,
        status: "failed",
        error_code:
          input.kind === "artifact"
            ? "output_artifact_materialization_error"
            : "output_proposal_materialization_error",
        error_message: error instanceof Error ? error.message : `${input.operation} failed.`,
        metadata_json: {
          label: input.label,
          operation: input.operation,
        },
      };
    }
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

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}
