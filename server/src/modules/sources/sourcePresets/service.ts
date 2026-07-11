import type { ServerConfig } from "../../../config";
import {
  HttpError,
  optionalString,
  type Queryable,
  type SpaceUserIdentity,
} from "../../routeUtils/common";
import {
  ARXIV_SORT_BY_VALUES,
  ARXIV_SORT_ORDER_VALUES,
  buildArxivQueryUrl,
  parseArxivFeed,
  type ArxivPaper,
  type ArxivQueryConfig,
  type ArxivSortBy,
  type ArxivSortOrder,
} from "../connectors/arxiv";
import { acquireArxivRequestSlot } from "../connectors/arxivThrottle";
import { PgCustomSourceHandlerRepository } from "../customSources/customSourceHandlerRepository";
import { fetchSource } from "../sourceFetch";
import { SourceConnectionService } from "../sourceConnectionService";
import { ARXIV_CATEGORY_GROUPS, ARXIV_CATEGORY_ID_SET } from "./arxivCategoryTaxonomy";

export interface SourcePresetCategoryOption {
  value: string;
  label: string;
}

export interface SourcePresetCategoryGroup {
  group: string;
  options: readonly SourcePresetCategoryOption[];
}

export interface SourcePreset {
  id: string;
  category: string;
  display_name: string;
  description: string;
  connector_key: string;
  fields: string[];
  category_options?: readonly SourcePresetCategoryGroup[];
}

/** Code-defined source preset registry. V1 ships arXiv only — no table. */
const SOURCE_PRESETS: SourcePreset[] = [
  {
    id: "arxiv",
    category: "academic",
    display_name: "arXiv",
    description: "Monitor arXiv papers by API query.",
    connector_key: "arxiv",
    category_options: ARXIV_CATEGORY_GROUPS,
    fields: [
      "name",
      "mode",
      "search_query",
      "categories",
      "max_results",
      "sort_by",
      "sort_order",
      "fetch_frequency",
      "capture_policy",
    ],
  },
];

export interface ArxivPresetPreviewResult {
  preset_id: "arxiv";
  query_url: string;
  items: ArxivPaper[];
  warnings: string[];
}

const FETCH_FREQUENCIES = new Set(["manual", "hourly", "daily", "weekly"]);
const ARXIV_PRESET_MODES = ["search", "recent_by_category"] as const;
type ArxivPresetMode = (typeof ARXIV_PRESET_MODES)[number];
const ARXIV_SEARCH_QUERY_MAX_LENGTH = 500;
const ARXIV_CATEGORY_MAX_LENGTH = 64;
const ARXIV_CATEGORY_MAX_COUNT = 10;
const ARXIV_CATEGORY_PATTERN = /^[a-z]+(?:-[a-z]+)*(?:\.(?:[A-Z]{2}|[a-z]+(?:-[a-z]+)*))?$/;
const ARXIV_PREVIEW_DEFAULT_MAX_RESULTS = 50;
const ARXIV_CREATE_DEFAULT_MAX_RESULTS = 50;

export function listSourcePresets(): { items: SourcePreset[] } {
  return { items: SOURCE_PRESETS };
}

export function normalizeArxivQueryConfig(
  body: Record<string, unknown>,
  defaults: { maxResults: number },
): ArxivQueryConfig & { mode: ArxivPresetMode; categories: string[] } {
  const rawMode = optionalString(body.mode) ?? "search";
  if (!(ARXIV_PRESET_MODES as readonly string[]).includes(rawMode)) {
    throw new HttpError(422, `mode must be one of: ${ARXIV_PRESET_MODES.join(", ")}`);
  }
  const mode = rawMode as ArxivPresetMode;
  let searchQuery: string;
  let categories: string[] = [];
  if (mode === "recent_by_category") {
    categories = normalizeArxivCategories(body);
    searchQuery = buildArxivCategoryQuery(categories);
  } else {
    const rawSearchQuery = optionalString(body.search_query);
    if (!rawSearchQuery) throw new HttpError(422, "search_query is required");
    if (rawSearchQuery.length > ARXIV_SEARCH_QUERY_MAX_LENGTH) {
      throw new HttpError(422, `search_query must be at most ${ARXIV_SEARCH_QUERY_MAX_LENGTH} characters`);
    }
    searchQuery = rawSearchQuery;
  }
  let maxResults = defaults.maxResults;
  if (body.max_results !== undefined && body.max_results !== null) {
    if (typeof body.max_results !== "number" || !Number.isInteger(body.max_results)) {
      throw new HttpError(422, "max_results must be an integer between 1 and 100");
    }
    if (body.max_results < 1 || body.max_results > 100) {
      throw new HttpError(422, "max_results must be an integer between 1 and 100");
    }
    maxResults = body.max_results;
  }
  const sortBy = optionalString(body.sort_by) ?? (mode === "recent_by_category" ? "submittedDate" : "lastUpdatedDate");
  if (!(ARXIV_SORT_BY_VALUES as readonly string[]).includes(sortBy)) {
    throw new HttpError(422, `sort_by must be one of: ${ARXIV_SORT_BY_VALUES.join(", ")}`);
  }
  const sortOrder = optionalString(body.sort_order) ?? "descending";
  if (!(ARXIV_SORT_ORDER_VALUES as readonly string[]).includes(sortOrder)) {
    throw new HttpError(422, `sort_order must be one of: ${ARXIV_SORT_ORDER_VALUES.join(", ")}`);
  }
  return {
    mode,
    categories,
    search_query: searchQuery,
    max_results: maxResults,
    sort_by: sortBy as ArxivSortBy,
    sort_order: sortOrder as ArxivSortOrder,
  };
}

function normalizeArxivCategories(body: Record<string, unknown>): string[] {
  if (body.categories === undefined) throw new HttpError(422, "at least one category is required");
  if (!Array.isArray(body.categories)) {
    throw new HttpError(422, "categories must be an array of strings");
  }
  const rawCategories = body.categories as string[];
  if (rawCategories.some((value) => typeof value !== "string")) {
    throw new HttpError(422, "categories must be an array of strings");
  }
  const values = rawCategories;
  if (values.length === 0) throw new HttpError(422, "at least one category is required");

  const categories = [...new Set(values.map((value) => normalizeArxivCategory(value)))];
  if (categories.length > ARXIV_CATEGORY_MAX_COUNT) {
    throw new HttpError(422, `categories must contain at most ${ARXIV_CATEGORY_MAX_COUNT} entries`);
  }
  return categories;
}

function normalizeArxivCategory(value: string | null | undefined): string {
  const raw = value?.trim();
  if (!raw) throw new HttpError(422, "category is required");
  if (raw.length > ARXIV_CATEGORY_MAX_LENGTH) {
    throw new HttpError(422, `category must be at most ${ARXIV_CATEGORY_MAX_LENGTH} characters`);
  }
  const [prefix, suffix, extra] = raw.split(".");
  if (extra !== undefined || !prefix) throw new HttpError(422, "category must be an arXiv category such as cs.AI");
  const normalizedSuffix = suffix === undefined
    ? undefined
    : /^[a-z]{2}$/i.test(suffix) ? suffix.toUpperCase() : suffix.toLowerCase();
  const normalized = suffix === undefined
    ? prefix.toLowerCase()
    : `${prefix.toLowerCase()}.${normalizedSuffix}`;
  if (!ARXIV_CATEGORY_PATTERN.test(normalized)) {
    throw new HttpError(422, "category must be an arXiv category such as cs.AI");
  }
  if (!ARXIV_CATEGORY_ID_SET.has(normalized)) {
    throw new HttpError(422, "category must be in the official arXiv taxonomy");
  }
  return normalized;
}

function buildArxivCategoryQuery(categories: string[]): string {
  return categories.map((category) => `cat:${category}`).join(" OR ");
}

export class SourcePresetService {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  /** Runs a bounded arXiv API query; writes no durable rows. */
  async previewArxiv(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
  ): Promise<ArxivPresetPreviewResult> {
    const queryConfig = normalizeArxivQueryConfig(body, { maxResults: ARXIV_PREVIEW_DEFAULT_MAX_RESULTS });
    const queryUrl = buildArxivQueryUrl(queryConfig);
    const maxDownloadBytes = await new PgCustomSourceHandlerRepository(this.db, this.config)
      .getRunnerSettingsForSpace(identity.spaceId)
      .then((settings) => settings.download_bytes_max);
    await acquireArxivRequestSlot();
    const response = await fetchSource(queryUrl, { maxDownloadBytes });
    if (!response.ok) {
      throw new HttpError(502, `Failed to fetch arXiv API (${response.status})`);
    }
    if (!response.isText || response.text === null) {
      throw new HttpError(415, `arXiv API returned unsupported content (${response.contentType ?? "unknown"})`);
    }
    const items = parseArxivFeed(response.text).slice(0, queryConfig.max_results);
    return {
      preset_id: "arxiv",
      query_url: queryUrl,
      items,
      warnings: items.length === 0 ? ["arXiv query returned no papers"] : [],
    };
  }

  /** Creates an active built-in arXiv source connection. */
  async createArxiv(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    return new SourceConnectionService(this.db, this.config).createConnection(identity, arxivConnectionDraft(body));
  }
}

export function arxivConnectionDraft(body:Record<string,unknown>){
    const queryConfig = normalizeArxivQueryConfig(body, { maxResults: ARXIV_CREATE_DEFAULT_MAX_RESULTS });
    const fetchFrequency = optionalString(body.fetch_frequency) ?? "weekly";
    if (!FETCH_FREQUENCIES.has(fetchFrequency)) {
      throw new HttpError(422, `fetch_frequency must be one of: ${[...FETCH_FREQUENCIES].join(", ")}`);
    }
    const name = optionalString(body.name) ??
      (queryConfig.mode === "recent_by_category"
        ? `arXiv new: ${queryConfig.categories.join(" + ")}`
        : `arXiv: ${queryConfig.search_query}`);
    return {
      connector_key: "arxiv",
      name: name.slice(0, 200),
      endpoint_url: buildArxivQueryUrl(queryConfig),
      fetch_frequency: fetchFrequency,
      next_check_at: body.next_check_at,
      schedule_rule: body.schedule_rule,
      capture_policy: optionalString(body.capture_policy) ?? "extract_text",
      config: { preset_id: "arxiv", ...queryConfig },
    };
}
