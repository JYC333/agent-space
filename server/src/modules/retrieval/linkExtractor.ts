export interface ExtractedRetrievalLink {
  origin: "markdown_link" | "wikilink" | "source_ref";
  target: string;
  label: string | null;
  evidenceText: string;
}

const MARKDOWN_LINK = /\[([^\]]+)\]\(([^)\s]+)(?:\s+["'][^)]*["'])?\)/g;
const WIKILINK = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
const DIRECT_URL = /\bhttps?:\/\/[^\s<>)"']+/g;

export function extractRetrievalLinks(text: string | null | undefined): ExtractedRetrievalLink[] {
  if (!text) return [];
  const links: ExtractedRetrievalLink[] = [];
  const seen = new Set<string>();
  const add = (link: ExtractedRetrievalLink): void => {
    const target = link.target.trim();
    if (!target) return;
    const key = `${link.origin}:${target}:${link.label ?? ""}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ ...link, target });
  };

  for (const match of text.matchAll(MARKDOWN_LINK)) {
    add({
      origin: "markdown_link",
      label: match[1]?.trim() || null,
      target: match[2]?.trim() ?? "",
      evidenceText: match[0],
    });
  }

  for (const match of text.matchAll(WIKILINK)) {
    add({
      origin: "wikilink",
      label: match[2]?.trim() || null,
      target: match[1]?.trim() ?? "",
      evidenceText: match[0],
    });
  }

  for (const match of text.matchAll(DIRECT_URL)) {
    add({
      origin: "source_ref",
      label: null,
      target: match[0],
      evidenceText: match[0],
    });
  }

  return links;
}
