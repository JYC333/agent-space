import type { PromptResolveResult } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { resolvePrompt } from "../prompts/resolver";
import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import type { ProjectWorkflowProfile, WorkflowTemplate } from "./types";

export function workflowRunPromptAssetKey(workflowTemplateId: string): string {
  return `workflow.${workflowTemplateId}.run`;
}

export interface WorkflowRunPromptInput {
  identity: SpaceUserIdentity;
  projectId: string;
  template: WorkflowTemplate;
  profile: ProjectWorkflowProfile | null;
  config: Record<string, unknown>;
  outputArtifactTypes: readonly string[];
}

export interface ResolvedWorkflowRunPrompt {
  prompt: string;
  resolveResult: PromptResolveResult;
}

export type WorkflowRunPromptResolver = (
  input: WorkflowRunPromptInput,
) => Promise<ResolvedWorkflowRunPrompt | null>;

export function workflowRunPromptResolver(db: Queryable): WorkflowRunPromptResolver {
  return async (input) => resolveWorkflowRunPrompt(db, input);
}

export async function resolveWorkflowRunPrompt(
  db: Queryable,
  input: WorkflowRunPromptInput,
): Promise<ResolvedWorkflowRunPrompt | null> {
  const resolved = await resolvePrompt(db, {
    spaceId: input.identity.spaceId,
    userId: input.identity.userId,
    projectId: input.projectId,
    assetKey: workflowRunPromptAssetKey(input.template.id),
    variables: workflowPromptVariables(input),
  });
  if (resolved.validation_errors.length > 0 || !resolved.rendered_text) return null;
  return { prompt: resolved.rendered_text, resolveResult: resolved };
}

function workflowPromptVariables(input: WorkflowRunPromptInput): Record<string, string> {
  const query = stringValue(input.config.query);
  const sourceMode = stringValue(input.config.source_mode);
  return {
    workflow_name: input.template.name,
    workflow_template_id: input.template.id,
    workflow_preset_name: input.profile?.name ?? "Unsaved run",
    workflow_description: input.template.description,
    research_question_section: query ? `\nResearch question:\n${query}\n\n` : "\n",
    source_mode_section: sourceMode ? `Source mode: ${sourceMode}\n\n` : "",
    capabilities: input.template.capability_ids.map((id) => `- ${id}`).join("\n"),
    expected_outputs: input.outputArtifactTypes.map((artifactType) => `- ${artifactType}`).join("\n"),
  };
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
