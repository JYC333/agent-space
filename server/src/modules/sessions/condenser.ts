/**
 * Session condensers.
 *
 * Two condenser versions produce a `SessionSummary` body from a slice of session
 * messages:
 *
 * - `pattern.v1` — deterministic, no LLM. A pure function (`buildPatternSummary`)
 *   of role counts, top keywords, and a compact highlight transcript. Free,
 *   instant, fully reproducible, but it does not understand meaning. Used as the
 *   always-available fallback.
 * - `llm.v1` — an LLM writes a real running summary (`buildCondensePrompt`
 *   produces the prompt; `buildLlmSummary` wraps the returned text into a body).
 *   Higher quality and language-agnostic, at the cost of a model call.
 *
 * Either way the output is derived context (never a `MemoryEntry`, never a
 * `Proposal`) and is freely regenerable.
 */

export const SESSION_CONDENSER_VERSION = "pattern.v1";
export const LLM_CONDENSER_VERSION = "llm.v1";

/**
 * Recent messages are kept raw in the conversation window; everything older than
 * this tail is what `condenseSession` summarizes. Aligned with the chat
 * conversation-window recent-message limit so the raw tail and the summary
 * cover-range stay adjacent.
 */
export const DEFAULT_CONDENSE_KEEP_RECENT = 12;

/**
 * Re-condense only once at least this many new messages have aged past the last
 * summary's watermark. Bounds version churn to roughly one new summary per batch
 * instead of one per chat turn.
 */
export const DEFAULT_CONDENSE_BATCH = 8;

/** Defensive bound on the transcript handed to the LLM (chars). */
export const CONDENSE_PROMPT_MAX_CHARS = 12_000;

const MAX_HIGHLIGHTS = 6;
const HIGHLIGHT_MAX_CHARS = 160;
const MAX_KEYWORDS = 8;
const MIN_KEYWORD_LENGTH = 3;

// Small English stopword set; `pattern.v1` keyword extraction is intentionally
// ASCII-oriented and deterministic, not linguistically complete.
const STOPWORDS = new Set([
  "the", "and", "for", "are", "but", "not", "you", "your", "with", "this",
  "that", "have", "has", "had", "was", "were", "will", "would", "can", "could",
  "should", "from", "into", "about", "what", "when", "where", "which", "who",
  "how", "why", "all", "any", "did", "does", "doing", "done", "get", "got",
  "let", "lets", "its", "our", "out", "now", "use", "using", "than", "then",
  "they", "them", "their", "there", "here", "some", "such", "just", "like",
  "want", "need", "please", "thanks", "thank", "okay", "yes", "no",
]);

export interface CondenserMessage {
  id: string;
  role: string;
  content: string;
}

export interface SessionSummaryBody {
  summary_text: string;
  summary_json: Record<string, unknown>;
  source_first_message_id: string;
  source_last_message_id: string;
  source_message_count: number;
  token_estimate_before: number;
  token_estimate_after: number;
  condenser_version: string;
}

interface SourceStats {
  usable: CondenserMessage[];
  roleCounts: Record<string, number>;
  first: CondenserMessage;
  last: CondenserMessage;
  charsBefore: number;
}

/**
 * Deterministic `pattern.v1` body. `null` when the slice has no non-empty
 * content. The caller chooses which messages to pass (typically all messages
 * older than the recent raw tail).
 */
export function buildPatternSummary(
  messages: readonly CondenserMessage[],
): SessionSummaryBody | null {
  const stats = sourceStats(messages);
  if (!stats) return null;

  const keywords = topKeywords(stats.usable);
  const highlights = pickHighlights(stats.usable);
  const lines: string[] = [
    `Earlier conversation condensed (${stats.usable.length} message${
      stats.usable.length === 1 ? "" : "s"
    }${roleSummary(stats.roleCounts) ? `: ${roleSummary(stats.roleCounts)}` : ""}).`,
  ];
  if (keywords.length > 0) lines.push(`Topics: ${keywords.join(", ")}.`);
  if (highlights.length > 0) {
    lines.push("Highlights:");
    for (const highlight of highlights) {
      lines.push(`- ${highlight.role}: ${highlight.text}`);
    }
  }
  const summaryText = lines.join("\n");

  return summaryBody(stats, summaryText, SESSION_CONDENSER_VERSION, {
    top_keywords: keywords,
  });
}

/**
 * Condenser scenario profiles. The summary acts on chat-session messages, but a
 * session's content varies by who the user is talking to. `adaptive` (the
 * default) safely handles mixed personal + coding + project content; the others
 * specialize when the agent is dedicated to one scenario. Selected per agent via
 * `AgentVersion.context_policy_json.condenser.profile`; unknown / absent →
 * `adaptive`.
 */
export type CondenserProfile = "adaptive" | "general" | "coding" | "project";
export const DEFAULT_CONDENSER_PROFILE: CondenserProfile = "adaptive";

export interface CondenserPromptConfig {
  profile?: CondenserProfile | string | null;
  custom_system?: string | null;
  custom_instructions?: string | null;
}

export interface CondenserPresetPrompt {
  profile: CondenserProfile;
  system: string;
  instructions: string;
  shared_system_rules: string;
  effective_system: string;
}

export function resolveCondenserProfile(
  value: string | null | undefined,
): CondenserProfile {
  return value === "general" || value === "coding" || value === "project" || value === "adaptive"
    ? value
    : DEFAULT_CONDENSER_PROFILE;
}

// Appended to every profile system prompt: the cross-cutting rules.
const SHARED_SYSTEM_RULES =
  " Be strictly factual — never invent details that are not present. Write the " +
  "summary in the same language as the conversation. Output a concise running " +
  "summary with no preamble.";

const PROFILE_PROMPTS: Record<CondenserProfile, { system: string; instructions: string }> = {
  adaptive: {
    system:
      "You condense the earlier part of a conversation with a personal assistant " +
      "so it can be dropped from context without losing continuity. The " +
      "conversation may mix everyday discussion with coding and project work.",
    instructions:
      "Summarize the conversation so far. Include:\n" +
      "- The user's goals, requests, and stated preferences\n" +
      "- Key facts, decisions, and conclusions reached\n" +
      "- Open questions and anything left unresolved\n" +
      "- The current state and the natural next step\n" +
      "When the conversation involves coding or a project, also preserve the " +
      "concrete technical state: relevant file paths and identifiers, commands or " +
      "config values, technical decisions, errors encountered and how they were " +
      "resolved, and what remains to be done. Include technical detail only when " +
      "the conversation contains it. Keep it concise but do not drop actionable " +
      "specifics.",
  },
  general: {
    system:
      "You condense the earlier part of a personal-assistant conversation so it " +
      "can be dropped from context without losing continuity.",
    instructions:
      "Summarize the conversation so far in short prose, covering the user's " +
      "goals and requests, the key facts and decisions established, any open " +
      "questions, and the current state with the natural next step.",
  },
  coding: {
    system:
      "You are a conversation summarizer for a coding assistant. Your summary " +
      "replaces the earlier conversation, so it must preserve everything needed " +
      "to keep working without repeating past steps.",
    instructions:
      "Summarize the conversation so far. You MUST include:\n" +
      "1. The original task or goal the user requested\n" +
      "2. A checklist of completed steps vs. remaining steps\n" +
      "3. Key file paths, identifiers, commands, config values, and intermediate results\n" +
      "4. Any errors encountered and how they were resolved\n" +
      "5. The current state and what to do next\n" +
      "Be concise but preserve ALL actionable details. Do NOT omit code, search " +
      "results, or computed values that will be needed.",
  },
  project: {
    system:
      "You summarize project-oriented conversations. Your summary replaces the " +
      "earlier conversation, so it must preserve the project's state and direction.",
    instructions:
      "Summarize the conversation so far. Include:\n" +
      "- The project objective and scope\n" +
      "- Decisions made and their rationale\n" +
      "- Milestones or tasks: done vs. remaining\n" +
      "- Blockers, risks, and open questions\n" +
      "- Owners and deadlines if mentioned\n" +
      "- Current status and the next step\n" +
      "Be concise but keep all actionable specifics.",
  },
};

const CONDENSER_PROFILE_ORDER: readonly CondenserProfile[] = [
  "adaptive",
  "general",
  "coding",
  "project",
];

export function listCondenserPresetPrompts(): CondenserPresetPrompt[] {
  return CONDENSER_PROFILE_ORDER.map((profile) => {
    const prompt = PROFILE_PROMPTS[profile];
    return {
      profile,
      system: prompt.system,
      instructions: prompt.instructions,
      shared_system_rules: SHARED_SYSTEM_RULES.trim(),
      effective_system: `${prompt.system}${SHARED_SYSTEM_RULES}`,
    };
  });
}

/**
 * Build the LLM condense prompt for a scenario profile. `priorSummary` (when
 * present) lets the model update a running summary incrementally from only the
 * new turns, bounding token cost; `messages` are the turns to fold in.
 */
export function buildCondensePrompt(input: {
  profile?: CondenserProfile | string | null;
  config?: CondenserPromptConfig | null;
  priorSummary?: string | null;
  messages: readonly CondenserMessage[];
}): { system: string; user: string } {
  const profile = resolveCondenserProfile(
    typeof input.config?.profile === "string"
      ? input.config.profile
      : typeof input.profile === "string"
        ? input.profile
        : null,
  );
  const prompt = PROFILE_PROMPTS[profile];
  const systemBase = nonEmptyString(input.config?.custom_system) ?? prompt.system;
  const instructions = nonEmptyString(input.config?.custom_instructions) ?? prompt.instructions;
  const prior = (input.priorSummary ?? "").trim();
  const transcript = input.messages
    .filter((message) => message.content.trim().length > 0)
    .map((message) => `${message.role}: ${collapseWhitespace(message.content)}`)
    .join("\n")
    .slice(0, CONDENSE_PROMPT_MAX_CHARS);

  const user = prior
    ? `${instructions}\n\n` +
      "Update this running summary so it also covers the new turns below.\n\n" +
      `Existing summary:\n${prior}\n\n` +
      `New turns:\n${transcript}\n\n` +
      "Updated running summary:"
    : `${instructions}\n\nTurns:\n${transcript}\n\nRunning summary:`;

  return { system: `${systemBase}${SHARED_SYSTEM_RULES}`, user };
}

/**
 * Wrap an LLM-produced summary string into an `llm.v1` body. `null` when the
 * slice has no content or the LLM returned empty text (so the caller falls back
 * to `pattern.v1`). `messages` is the full covered range — it sets the source
 * range / counts the summary claims to cover, independent of how many turns were
 * actually fed to the model.
 */
export function buildLlmSummary(
  messages: readonly CondenserMessage[],
  llmText: string,
): SessionSummaryBody | null {
  const stats = sourceStats(messages);
  if (!stats) return null;
  const text = llmText.trim();
  if (!text) return null;
  return summaryBody(stats, text, LLM_CONDENSER_VERSION, { generated_by: "llm" });
}

function sourceStats(messages: readonly CondenserMessage[]): SourceStats | null {
  const usable = messages.filter((message) => message.content.trim().length > 0);
  if (usable.length === 0) return null;
  const roleCounts: Record<string, number> = {};
  for (const message of usable) {
    roleCounts[message.role] = (roleCounts[message.role] ?? 0) + 1;
  }
  return {
    usable,
    roleCounts,
    first: usable[0]!,
    last: usable[usable.length - 1]!,
    charsBefore: usable.reduce((sum, m) => sum + m.content.trim().length, 0),
  };
}

function summaryBody(
  stats: SourceStats,
  summaryText: string,
  condenserVersion: string,
  extraJson: Record<string, unknown>,
): SessionSummaryBody {
  return {
    summary_text: summaryText,
    summary_json: {
      condenser_version: condenserVersion,
      role_counts: stats.roleCounts,
      source_range: {
        first_message_id: stats.first.id,
        last_message_id: stats.last.id,
        message_count: stats.usable.length,
      },
      ...extraJson,
    },
    source_first_message_id: stats.first.id,
    source_last_message_id: stats.last.id,
    source_message_count: stats.usable.length,
    token_estimate_before: estimateTokensFromChars(stats.charsBefore),
    token_estimate_after: estimateTokensFromChars(summaryText.length),
    condenser_version: condenserVersion,
  };
}

function roleSummary(roleCounts: Record<string, number>): string {
  return Object.keys(roleCounts)
    .sort()
    .map((role) => `${roleCounts[role]} from ${role}`)
    .join(", ");
}

function topKeywords(messages: readonly CondenserMessage[]): string[] {
  const counts = new Map<string, number>();
  for (const message of messages) {
    for (const token of tokenize(message.content)) {
      counts.set(token, (counts.get(token) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .slice(0, MAX_KEYWORDS)
    .map(([word]) => word);
}

function tokenize(text: string): string[] {
  const matches = text.toLowerCase().match(/[a-z0-9]+/g);
  if (!matches) return [];
  return matches.filter(
    (word) => word.length >= MIN_KEYWORD_LENGTH && !STOPWORDS.has(word),
  );
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function pickHighlights(
  messages: readonly CondenserMessage[],
): Array<{ role: string; text: string }> {
  // Prefer the user turns (they carry intent); fall back to the full transcript
  // when there are not enough user turns to fill the highlight budget. Either
  // way take the oldest first so the summary reads chronologically.
  const userTurns = messages.filter((message) => message.role === "user");
  const base = userTurns.length >= MAX_HIGHLIGHTS ? userTurns : messages;
  return base.slice(0, MAX_HIGHLIGHTS).map((message) => ({
    role: message.role,
    text: truncate(collapseWhitespace(message.content), HIGHLIGHT_MAX_CHARS),
  }));
}

function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function truncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function estimateTokensFromChars(chars: number): number {
  return chars > 0 ? Math.ceil(chars / 4) : 0;
}
