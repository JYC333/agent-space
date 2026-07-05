import type { ImportFilePaperInput } from "./types";
import { normalizeArxivId, normalizeDoi, nonEmptyString, publicationYearFromDate } from "./identifiers";

export type ResearchAtlasImportFormat = "bibtex" | "ris" | "csl_json";

export function parseImportFile(format: ResearchAtlasImportFormat, input: unknown): ImportFilePaperInput[] {
  if (format === "csl_json") return parseCslJson(input);
  const text = typeof input === "string" ? input : "";
  if (!text.trim()) return [];
  if (format === "bibtex") return parseBibtex(text);
  return parseRis(text);
}

function parseBibtex(text: string): ImportFilePaperInput[] {
  const entries = text.match(/@\w+\s*\{[\s\S]*?(?=\n@\w+\s*\{|$)/g) ?? [];
  return entries.map<ImportFilePaperInput>((entry) => {
    const fields = bibFields(entry);
    const doi = fields.doi ? normalizeDoi(fields.doi) : null;
    const arxivId = fields.eprint ? normalizeArxivId(fields.eprint) : arxivFromText(fields.url ?? fields.note ?? "");
    return {
      title: fields.title ?? (doi ? `DOI ${doi}` : arxivId ? `arXiv ${arxivId}` : "Untitled paper"),
      abstract: fields.abstract ?? null,
      publication_year: fields.year ? Number(fields.year) : null,
      publication_date: fields.year ? `${fields.year}-01-01` : null,
      paper_type: fields.archiveprefix?.toLowerCase() === "arxiv" || arxivId ? "preprint" : "article",
      venue_name: fields.journal ?? fields.booktitle ?? null,
      venue_type: fields.booktitle ? "conference" : fields.journal ? "journal" : null,
      doi,
      arxiv_id: arxivId,
      raw_author_names: splitAuthors(fields.author),
      authors: splitAuthors(fields.author).map((name) => ({ name })),
      metadata_json: { import_format: "bibtex" },
    };
  }).filter(hasIdentifier);
}

function bibFields(entry: string): Record<string, string> {
  const fields: Record<string, string> = {};
  const re = /(\w+)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|"([^"]*)")/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(entry)) !== null) {
    fields[match[1]!.toLowerCase()] = cleanBibValue(match[2] ?? match[3] ?? "");
  }
  return fields;
}

function cleanBibValue(value: string): string {
  return value.replace(/[{}]/g, "").replace(/\s+/g, " ").trim();
}

function parseRis(text: string): ImportFilePaperInput[] {
  const records = text.split(/\nER\s*-\s*/i).map((record) => record.trim()).filter(Boolean);
  return records.map<ImportFilePaperInput>((record) => {
    const fields = risFields(record);
    const doi = fields.DO?.[0] ? normalizeDoi(fields.DO[0]) : null;
    const arxivId = arxivFromText([...(fields.UR ?? []), ...(fields.N1 ?? [])].join(" "));
    const year = fields.PY?.[0]?.match(/\d{4}/)?.[0] ?? null;
    const authors = fields.AU ?? fields.A1 ?? [];
    return {
      title: fields.TI?.[0] ?? fields.T1?.[0] ?? (doi ? `DOI ${doi}` : arxivId ? `arXiv ${arxivId}` : "Untitled paper"),
      publication_year: year ? Number(year) : null,
      publication_date: year ? `${year}-01-01` : null,
      paper_type: arxivId ? "preprint" : "article",
      venue_name: fields.JO?.[0] ?? fields.JF?.[0] ?? fields.T2?.[0] ?? null,
      venue_type: fields.T2?.[0] ? "conference" : fields.JO?.[0] || fields.JF?.[0] ? "journal" : null,
      doi,
      arxiv_id: arxivId,
      raw_author_names: authors,
      authors: authors.map((name) => ({ name })),
      metadata_json: { import_format: "ris" },
    };
  }).filter(hasIdentifier);
}

function risFields(record: string): Record<string, string[]> {
  const fields: Record<string, string[]> = {};
  for (const line of record.split(/\r?\n/)) {
    const match = line.match(/^([A-Z0-9]{2})\s*-\s*(.*)$/);
    if (!match) continue;
    const key = match[1]!;
    const value = match[2]!.trim();
    fields[key] = [...(fields[key] ?? []), value];
  }
  return fields;
}

function parseCslJson(input: unknown): ImportFilePaperInput[] {
  const items = Array.isArray(input) ? input : [input];
  return items.map<ImportFilePaperInput>((item) => {
    const rec = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const doi = nonEmptyString(rec.DOI) ?? nonEmptyString(rec.doi);
    const issued = rec.issued && typeof rec.issued === "object"
      ? rec.issued as { "date-parts"?: number[][] }
      : {};
    const dateParts = issued["date-parts"]?.[0];
    const date = dateParts?.[0] ? `${String(dateParts[0]).padStart(4, "0")}-${String(dateParts[1] ?? 1).padStart(2, "0")}-${String(dateParts[2] ?? 1).padStart(2, "0")}` : null;
    const authors = Array.isArray(rec.author)
      ? rec.author.map((author) => cslAuthorName(author)).filter((name) => name !== "")
      : [];
    return {
      title: nonEmptyString(rec.title) ?? (doi ? `DOI ${normalizeDoi(doi)}` : "Untitled paper"),
      publication_date: date,
      publication_year: publicationYearFromDate(date),
      paper_type: rec.type === "paper-conference" ? "article" : "article",
      venue_name: nonEmptyString(rec["container-title"]),
      venue_type: rec.type === "paper-conference" ? "conference" : "journal",
      doi: doi ? normalizeDoi(doi) : null,
      arxiv_id: arxivFromText(`${String(rec.URL ?? "")} ${String(rec.note ?? "")}`),
      raw_author_names: authors,
      authors: authors.map((name) => ({ name })),
      metadata_json: { import_format: "csl_json", zotero_key: nonEmptyString(rec.id) },
    };
  }).filter(hasIdentifier);
}

function cslAuthorName(value: unknown): string {
  const author = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const literal = nonEmptyString(author.literal);
  if (literal) return literal;
  return [nonEmptyString(author.given), nonEmptyString(author.family)].filter(Boolean).join(" ").trim();
}

function splitAuthors(value: string | undefined): string[] {
  if (!value) return [];
  return value.split(/\s+and\s+|;/i).map((item) => item.trim()).filter(Boolean);
}

function arxivFromText(value: string): string | null {
  const match = value.match(/(?:arxiv:|arxiv\.org\/(?:abs|pdf|html)\/)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?\/\d{7}(?:v\d+)?)/i);
  return match ? normalizeArxivId(match[1]!) : null;
}

function hasIdentifier(input: ImportFilePaperInput): boolean {
  return Boolean(input.doi || input.arxiv_id);
}
