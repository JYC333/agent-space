export type ExternalIdType =
  | "doi"
  | "arxiv"
  | "pmid"
  | "pmcid"
  | "openalex"
  | "s2"
  | "mag"
  | "orcid"
  | "ror"
  | "issn"
  | "isbn"
  | "zotero_key"
  | "homepage_url";

const DOI_PREFIX_RE = /^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i;
const ARXIV_PREFIX_RE = /^(?:arxiv:|https?:\/\/arxiv\.org\/(?:abs|pdf|html)\/)/i;
const ARXIV_VERSION_RE = /v\d+$/i;

export function normalizeDoi(value: string): string {
  return value.trim().replace(DOI_PREFIX_RE, "").toLowerCase();
}

export function normalizeArxivId(value: string): string {
  return value
    .trim()
    .replace(ARXIV_PREFIX_RE, "")
    .replace(/\.pdf$/i, "")
    .replace(ARXIV_VERSION_RE, "");
}

export function normalizeExternalId(type: ExternalIdType, value: string): string {
  if (type === "doi") return normalizeDoi(value);
  if (type === "arxiv") return normalizeArxivId(value);
  if (type === "orcid") return value.trim().replace(/^https?:\/\/orcid\.org\//i, "");
  if (type === "ror") return value.trim().replace(/^https?:\/\/ror\.org\//i, "").toLowerCase();
  return value.trim();
}

export function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

export function publicationYearFromDate(value: string | null | undefined): number | null {
  if (!value) return null;
  const year = Number(value.slice(0, 4));
  return Number.isInteger(year) && year >= 1000 && year <= 3000 ? year : null;
}
