import type { PaperMetadataInput } from "./types";
import { normalizeDoi, nonEmptyString, publicationYearFromDate } from "./identifiers";

interface CrossrefWorkMessage {
  DOI?: string;
  title?: string[];
  abstract?: string;
  author?: Array<{
    given?: string;
    family?: string;
    ORCID?: string;
    affiliation?: Array<{ name?: string }>;
  }>;
  "container-title"?: string[];
  type?: string;
  URL?: string;
  "is-referenced-by-count"?: number;
  "reference-count"?: number;
  published?: { "date-parts"?: number[][] };
  "published-print"?: { "date-parts"?: number[][] };
  "published-online"?: { "date-parts"?: number[][] };
}

export async function fetchCrossrefWork(doi: string, mailto?: string | null): Promise<PaperMetadataInput | null> {
  const normalized = normalizeDoi(doi);
  const url = new URL(`https://api.crossref.org/works/${encodeURIComponent(normalized)}`);
  if (mailto) url.searchParams.set("mailto", mailto);
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Crossref returned ${response.status}`);
  }
  const payload = await response.json() as { message?: CrossrefWorkMessage };
  if (!payload.message) return null;
  return crossrefMessageToPaperMetadata(payload.message);
}

export function crossrefMessageToPaperMetadata(message: CrossrefWorkMessage): PaperMetadataInput {
  const published = message["published-print"] ?? message["published-online"] ?? message.published;
  const publicationDate = datePartsToDate(published?.["date-parts"]?.[0]);
  const authors = (message.author ?? [])
    .map((author) => {
      const name = [author.given, author.family].filter(Boolean).join(" ").trim();
      return {
        name,
        orcid: author.ORCID ? author.ORCID.replace(/^https?:\/\/orcid\.org\//i, "") : null,
        affiliation: author.affiliation?.map((item) => item.name).filter(Boolean).join("; ") || null,
      };
    })
    .filter((author) => author.name !== "");
  const title = nonEmptyString(message.title?.[0]) ?? (message.DOI ? `DOI ${normalizeDoi(message.DOI)}` : "Untitled paper");
  const doi = message.DOI ? normalizeDoi(message.DOI) : null;
  return {
    title,
    abstract: nonEmptyString(message.abstract),
    publication_date: publicationDate,
    publication_year: publicationYearFromDate(publicationDate),
    paper_type: "article",
    venue_name: nonEmptyString(message["container-title"]?.[0]),
    venue_type: "journal",
    doi,
    best_oa_url: nonEmptyString(message.URL),
    cited_by_count: message["is-referenced-by-count"] ?? null,
    reference_count: message["reference-count"] ?? null,
    raw_author_names: authors.map((author) => author.name),
    authors,
    metadata_json: { crossref_type: message.type ?? null },
  };
}

function datePartsToDate(parts: number[] | undefined): string | null {
  if (!parts || parts.length === 0 || !parts[0]) return null;
  const [year, month = 1, day = 1] = parts;
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
