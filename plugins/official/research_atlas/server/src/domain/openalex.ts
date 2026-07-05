import type { PaperMetadataInput } from "./types";
import { normalizeDoi, nonEmptyString } from "./identifiers";

interface OpenAlexWork {
  id?: string;
  doi?: string;
  title?: string;
  abstract_inverted_index?: Record<string, number[]>;
  publication_year?: number;
  publication_date?: string;
  type?: string;
  cited_by_count?: number;
  referenced_works_count?: number;
  primary_location?: {
    source?: { display_name?: string; type?: string; issn_l?: string; issn?: string[] };
    landing_page_url?: string;
    pdf_url?: string;
  };
  authorships?: Array<{
    author_position?: string;
    raw_author_name?: string;
    author?: { id?: string; display_name?: string; orcid?: string };
    institutions?: Array<{ id?: string; display_name?: string; ror?: string; country_code?: string; type?: string }>;
  }>;
}

export async function fetchOpenAlexWorkByDoi(doi: string, mailto?: string | null): Promise<PaperMetadataInput | null> {
  const normalized = normalizeDoi(doi);
  const url = new URL(`https://api.openalex.org/works/doi:${encodeURIComponent(normalized)}`);
  if (mailto) url.searchParams.set("mailto", mailto);
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`OpenAlex returned ${response.status}`);
  return openAlexWorkToPaperMetadata(await response.json() as OpenAlexWork);
}

export function openAlexWorkToPaperMetadata(work: OpenAlexWork): PaperMetadataInput {
  const source = work.primary_location?.source;
  const authors = (work.authorships ?? [])
    .map((authorship) => ({
      name: nonEmptyString(authorship.author?.display_name) ?? nonEmptyString(authorship.raw_author_name) ?? "",
      orcid: authorship.author?.orcid?.replace(/^https?:\/\/orcid\.org\//i, "") ?? null,
      affiliation: authorship.institutions?.map((institution) => institution.display_name).filter(Boolean).join("; ") || null,
    }))
    .filter((author) => author.name !== "");
  return {
    title: nonEmptyString(work.title) ?? "Untitled paper",
    abstract: abstractFromInvertedIndex(work.abstract_inverted_index),
    publication_year: work.publication_year ?? null,
    publication_date: nonEmptyString(work.publication_date),
    paper_type: work.type === "preprint" ? "preprint" : "article",
    venue_name: nonEmptyString(source?.display_name),
    venue_type: source?.type === "repository" ? "repository" : source?.type === "conference" ? "conference" : "journal",
    doi: work.doi ? normalizeDoi(work.doi) : null,
    best_oa_url: nonEmptyString(work.primary_location?.pdf_url) ?? nonEmptyString(work.primary_location?.landing_page_url),
    cited_by_count: work.cited_by_count ?? null,
    reference_count: work.referenced_works_count ?? null,
    raw_author_names: authors.map((author) => author.name),
    authors,
    metadata_json: {
      openalex_id: work.id ?? null,
      source_issn_l: source?.issn_l ?? null,
      source_issn: source?.issn ?? null,
    },
  };
}

function abstractFromInvertedIndex(index: Record<string, number[]> | undefined): string | null {
  if (!index) return null;
  const words: Array<{ word: string; position: number }> = [];
  for (const [word, positions] of Object.entries(index)) {
    for (const position of positions) words.push({ word, position });
  }
  words.sort((left, right) => left.position - right.position);
  return words.map((item) => item.word).join(" ") || null;
}
