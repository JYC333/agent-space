import type { PromptResolveResult } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { resolvePrompt } from "../prompts/resolver";
import type { Queryable } from "../routeUtils/common";
import {
  CONDENSE_PROMPT_MAX_CHARS,
  resolveCondenserProfile,
  type CondenserMessage,
  type CondenserProfile,
} from "./condenser";

export function condenserPromptAssetKey(profile: CondenserProfile): string {
  return `session.condenser.${profile}`;
}

export interface ResolvedCondenserPrompt {
  system: string;
  user: string;
  resolveResult: PromptResolveResult;
}

export async function resolveCondenserPrompt(
  db: Queryable,
  input: {
    spaceId: string;
    userId: string;
    profile?: CondenserProfile | string | null;
    priorSummary?: string | null;
    messages: readonly CondenserMessage[];
  },
): Promise<ResolvedCondenserPrompt | null> {
  const profile = resolveCondenserProfile(input.profile);
  const resolved = await resolvePrompt(db, {
    spaceId: input.spaceId,
    userId: input.userId,
    assetKey: condenserPromptAssetKey(profile),
    variables: condenserPromptVariables(input.priorSummary, input.messages),
  });
  if (resolved.validation_errors.length > 0 || !resolved.rendered_messages) return null;
  const system = firstMessageContent(resolved.rendered_messages, "system");
  const user = firstMessageContent(resolved.rendered_messages, "user");
  return system && user ? { system, user, resolveResult: resolved } : null;
}

function condenserPromptVariables(
  priorSummary: string | null | undefined,
  messages: readonly CondenserMessage[],
): Record<string, string> {
  const prior = (priorSummary ?? "").trim();
  return {
    prior_summary_block: prior
      ? `Update this running summary so it also covers the new turns below.\n\nExisting summary:\n${prior}\n\n`
      : "",
    turns_heading: prior ? "New turns:" : "Turns:",
    transcript: messages
      .filter((message) => message.content.trim().length > 0)
      .map((message) => `${message.role}: ${collapseWhitespace(message.content)}`)
      .join("\n")
      .slice(0, CONDENSE_PROMPT_MAX_CHARS),
    output_label: prior ? "Updated running summary:" : "Running summary:",
  };
}

function firstMessageContent(
  messages: readonly { role: "system" | "user" | "assistant"; content: string }[],
  role: "system" | "user" | "assistant",
): string | null {
  const content = messages.find((message) => message.role === role)?.content.trim();
  return content ? content : null;
}

function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
