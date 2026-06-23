export function normalizeTextForSearch(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function normalizeAlias(value: string | null | undefined): string {
  const normalized = normalizeTextForSearch(value);
  return normalized
    .replace(/^["'`[(]+/, "")
    .replace(/["'`\])]+$/, "")
    .trim();
}

export function normalizeSlugCandidate(value: string | null | undefined): string {
  const normalized = normalizeTextForSearch(value);
  return normalized
    .replace(/^\/+/, "")
    .replace(/\/+$/, "")
    .replace(/\s+/g, "-");
}

export function tokenizeSimple(value: string | null | undefined): string[] {
  const normalized = normalizeTextForSearch(value);
  if (!normalized) return [];
  return normalized
    .split(/[^a-z0-9_/-]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

export function stripMarkdownForSearch(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 $2")
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, "$1 $2")
    .replace(/\[\[([^\]]+)\]\]/g, "$1")
    .replace(/[#>*_~\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function excerptAroundQuery(text: string, query: string, maxLength = 240): string {
  const source = text.replace(/\s+/g, " ").trim();
  if (source.length <= maxLength) return source;
  const index = normalizeTextForSearch(source).indexOf(normalizeTextForSearch(query));
  if (index < 0) return `${source.slice(0, maxLength - 1).trim()}...`;
  const start = Math.max(0, index - Math.floor(maxLength / 3));
  const end = Math.min(source.length, start + maxLength);
  const prefix = start > 0 ? "..." : "";
  const suffix = end < source.length ? "..." : "";
  return `${prefix}${source.slice(start, end).trim()}${suffix}`;
}
