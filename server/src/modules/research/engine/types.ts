export const RESEARCH_PROVIDER_KEYS = ["arxiv", "openalex", "semantic_scholar", "web_search"] as const;
export type ResearchProviderKey = typeof RESEARCH_PROVIDER_KEYS[number];

export interface ResearchProviderQuery {
  provider_key: ResearchProviderKey;
  query: Record<string, unknown>;
  rationale: string;
}

export interface ResearchQueryPlan {
  question: string;
  scope: Record<string, unknown>;
  providers: ResearchProviderQuery[];
  filters: Record<string, unknown>;
  time_window: { from: string | null; to: string | null } | null;
}

export interface ResearchCandidate {
  candidate_id: string;
  kind: "academic_paper" | "web_page";
  title: string;
  authors: string[];
  occurred_at: string | null;
  source_uri: string | null;
  excerpt: string | null;
  doi: string | null;
  arxiv_id: string | null;
  openalex_id: string | null;
  semantic_scholar_id: string | null;
  providers: ResearchProviderKey[];
  trust_level: "normal" | "untrusted";
  metadata: Record<string, unknown>;
}
