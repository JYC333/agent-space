import { randomUUID } from "node:crypto";
import type {
  RelationDiscoveryCandidate,
  RelationDiscoveryReport,
  RelationDiscoveryScanRequest,
  RelationDiscoverySourceType,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import { extractRetrievalLinks } from "../retrieval/linkExtractor";
import type { Queryable } from "../routeUtils/common";
import {
  loadSourceConnectionIdsForTargets,
  loadSourcePolicySnapshots,
  loadViewerSpaceRole,
  sourceConnectionIdsFromMetadata,
  sourcePolicyAllowsRead,
} from "../retrieval/sourcePolicy";
import { OBJECT_RELATION_TYPES, RELATION_TYPES } from "./knowledgeRepositoryRows";

/**
 * Slice F backend: deterministic candidate-relation discovery.
 *
 * Reads viewer-visible note / knowledge-item text plus policy-allowed Activity
 * and inline Artifact text, extracts typed internal links deterministically, and
 * resolves each target against the viewer-visible Knowledge items. Resolved
 * targets become candidate `knowledge_relation_create` edges; unresolved targets
 * (opt-in) become low-confidence candidate `knowledge_create` stubs. Output is a
 * single batched, confidence-tiered report. It writes nothing canonical — the
 * report only feeds the proposal-gated discovery packet, and even that creates
 * child pending proposals, not edges/items.
 *
 * Access-safety: every source row and every resolution target passes the same
 * readable space-object gate the Knowledge repository uses, so discovery can
 * neither read hidden text nor wire to hidden objects, and unresolved targets
 * leak nothing (they are just the link label the viewer already typed/can see).
 */

interface VisibleItemRow {
  id: string;
  title: string;
  slug: string | null;
  aliases_json: unknown;
  object_kind_id: string | null;
  object_kind: string | null;
  object_kind_label: string | null;
  content: string | null;
  plain_text: string | null;
  visibility: string;
  status: string;
  source_connection_ids: string[];
}

interface VisibleNoteRow {
  id: string;
  title: string;
  plain_text: string | null;
  status: string;
  object_kind_id: string | null;
  object_kind: string | null;
  object_kind_label: string | null;
}

interface VisibleActivityRow {
  id: string;
  title: string | null;
  content: string | null;
  visibility: string;
  owner_user_id: string | null;
  user_id: string | null;
  subject_user_id: string | null;
}

interface VisibleArtifactRow {
  id: string;
  title: string;
  content: string | null;
  visibility: string;
  owner_user_id: string | null;
  metadata_json: unknown;
  source_connection_ids: string[];
}

interface SourceText {
  objectType: RelationDiscoverySourceType;
  id: string;
  title: string;
  text: string;
  sourceConnectionIds: string[];
  objectKindId: string | null;
  objectKind: string | null;
  objectKindLabel: string | null;
}

interface RelationLink {
  target: string;
  label: string | null;
  relationType: string;
  origin: string;
}

export interface RelationDiscoveryRelationHint {
  id: string;
  object_kind_id: string;
  object_kind: string;
  object_kind_label: string;
  endpoint_object_type: string;
  endpoint_object_kind_id: string | null;
  endpoint_object_kind: string | null;
  endpoint_object_kind_label: string | null;
  relation_type: string;
  direction: "from" | "to" | "either";
  confidence_default: number;
  required: boolean;
}

export interface RelationDiscoveryLlmExtractor {
  extract(input: {
    spaceId: string;
    userId: string;
    sources: readonly SourceText[];
    visibleTargets: readonly ResolutionEntry[];
    relationHints: readonly RelationDiscoveryRelationHint[];
    maxCandidates: number;
    sourcePolicies: Readonly<Record<string, unknown>>;
    payloadSourceConnectionIds: readonly string[];
  }): Promise<RelationDiscoveryCandidate[]>;
}

type ConfidenceTier = "high" | "medium" | "low";

function readableClause(userParam: string, alias = "so"): string {
  return `(${alias}.visibility IN ('space_shared', 'workspace_shared') OR ${alias}.owner_user_id = ${userParam} OR ${alias}.created_by_user_id = ${userParam})`;
}

export interface RelationDiscoveryScanInput {
  spaceId: string;
  userId: string;
  request: RelationDiscoveryScanRequest;
  llmExtractor?: RelationDiscoveryLlmExtractor | null;
}

export interface RelationDiscoveryScanResult {
  report: RelationDiscoveryReport;
}

export async function runRelationDiscoveryScan(
  db: Queryable,
  input: RelationDiscoveryScanInput,
): Promise<RelationDiscoveryScanResult> {
  const sourceTypes = input.request.source_object_types ?? ["knowledge_item", "note", "activity", "artifact"];
  const limit = input.request.limit;

  // Resolution index always spans the full visible Knowledge-item set (targets),
  // regardless of which source types were requested.
  const items = await loadVisibleItems(db, input.spaceId, input.userId, limit);
  const index = buildResolutionIndex(items);

  const sources: SourceText[] = [];
  if (sourceTypes.includes("knowledge_item")) {
    for (const item of items) {
      sources.push({
        objectType: "knowledge_item",
        id: item.id,
        title: item.title,
        text: itemText(item),
        sourceConnectionIds: item.source_connection_ids,
        objectKindId: item.object_kind_id ?? null,
        objectKind: item.object_kind ?? null,
        objectKindLabel: item.object_kind_label ?? null,
      });
    }
  }
  if (sourceTypes.includes("note")) {
    const notes = await loadVisibleNotes(db, input.spaceId, input.userId, limit);
    for (const note of notes) {
      sources.push({
        objectType: "note",
        id: note.id,
        title: note.title,
        text: note.plain_text ?? "",
        sourceConnectionIds: [],
        objectKindId: note.object_kind_id ?? null,
        objectKind: note.object_kind ?? null,
        objectKindLabel: note.object_kind_label ?? null,
      });
    }
  }
  if (sourceTypes.includes("activity")) {
    const activities = await loadVisibleActivities(db, input.spaceId, input.userId, limit);
    for (const activity of activities) {
      sources.push({
        objectType: "activity",
        id: activity.id,
        title: activity.title ?? "Activity",
        text: activity.content ?? "",
        sourceConnectionIds: [],
        objectKindId: null,
        objectKind: null,
        objectKindLabel: null,
      });
    }
  }
  if (sourceTypes.includes("artifact")) {
    const artifacts = await loadVisibleArtifacts(db, input.spaceId, input.userId, limit);
    const visibleArtifacts = await filterBySourcePolicy(db, input.spaceId, input.userId, artifacts);
    for (const artifact of visibleArtifacts) {
      sources.push({
        objectType: "artifact",
        id: artifact.id,
        title: artifact.title,
        text: artifact.content ?? "",
        sourceConnectionIds: artifact.source_connection_ids,
        objectKindId: null,
        objectKind: null,
        objectKindLabel: null,
      });
    }
  }

  const candidates: RelationDiscoveryCandidate[] = [];
  let linksExtracted = 0;
  let sourcesScanned = 0;
  let capReached = false;
  const seenRelationPairs = new Set<string>();

  for (const source of sources) {
    if (capReached) break;
    sourcesScanned += 1;
    const links = extractRelationLinks(source.text);
    for (const link of links) {
      // Count only the links actually examined, so links_extracted stays
      // consistent when the candidate cap stops the scan mid-source.
      linksExtracted += 1;
      const resolved = resolveTarget(index, link.target, link.label);
      const relationType = link.relationType;
      if (resolved) {
        if (resolved.itemId === source.id) continue; // self-link
        const pairKey = `${source.id}->${resolved.itemId}:${relationType}`;
        if (seenRelationPairs.has(pairKey)) continue;
        seenRelationPairs.add(pairKey);
        // Two Knowledge items → the item-specific governed `knowledge_relation`.
        // A note source can't anchor that, so it proposes an FK-backed
        // `object_relation` over space_objects instead (note↔item).
        candidates.push(
          source.objectType === "knowledge_item"
            ? relationCandidate(source, resolved, relationType, link.target, link.label, link.origin)
            : source.objectType === "note"
              ? objectRelationCandidate(source, resolved, relationType, link.target, link.label, link.origin)
              : reviewRelationCandidate(source, resolved, relationType, link.target, link.label, link.origin),
        );
      } else if (input.request.include_unresolved_item_candidates) {
        const name = (link.label ?? cleanTypedTarget(link.target)).trim();
        if (name) candidates.push(itemCandidate(source, name, link.target));
      }
      // Truncation means the cap stopped the scan before all links were
      // examined — not merely that the candidate count equals the cap.
      if (candidates.length >= input.request.max_candidates) {
        capReached = true;
        break;
      }
    }
  }

  const requiredHintGaps = await detectRequiredRelationHintGaps(db, input, sources, candidates);
  for (const candidate of requiredHintGaps) {
    if (candidates.length >= input.request.max_candidates) {
      capReached = true;
      break;
    }
    candidates.push(candidate);
  }

  const llmExtraction = await runOptionalLlmExtraction(
    db,
    input,
    sources,
    [...uniqueResolutionEntries(index)],
    candidates.length,
  );
  for (const candidate of llmExtraction.candidates) {
    if (candidates.length >= input.request.max_candidates) {
      capReached = true;
      break;
    }
    candidates.push(candidate);
  }

  const truncated = capReached;
  const capped = candidates.slice(0, input.request.max_candidates);

  return {
    report: {
      candidates: capped,
      counts: countsFor(capped),
      sources_scanned: sourcesScanned,
      links_extracted: linksExtracted,
      truncated,
      access_safety: {
        only_visible_source_text: true,
        only_visible_targets: true,
        deterministic_extraction: true,
        source_policy_enforced: true,
        llm_extraction_requested: input.request.llm_extraction_enabled,
        llm_extraction_used: llmExtraction.used,
        canonical_write_performed: false,
      },
      llm_extraction: llmExtraction.summary,
    },
  };
}

// --- visibility-gated loads --------------------------------------------------

async function loadVisibleItems(
  db: Queryable,
  spaceId: string,
  userId: string,
  limit: number,
): Promise<VisibleItemRow[]> {
  const result = await db.query<Omit<VisibleItemRow, "source_connection_ids">>(
    `SELECT ki.object_id AS id, so.title, ki.slug, ki.aliases_json,
            kind.id AS object_kind_id, kind.key AS object_kind, kind.label AS object_kind_label,
            ki.content, ki.plain_text, so.visibility, so.status
       FROM knowledge_items ki
       JOIN space_objects so
         ON so.id = ki.object_id
        AND so.space_id = ki.space_id
        AND so.object_type = 'knowledge_item'
       LEFT JOIN space_object_kinds kind
         ON kind.space_id = ki.space_id
        AND kind.base_object_type = 'knowledge_item'
        AND kind.key = ki.knowledge_kind
        AND kind.status = 'active'
      WHERE ki.space_id = $1
        AND so.deleted_at IS NULL
        AND so.status = 'active'
        AND ${readableClause("$2")}
      ORDER BY so.updated_at DESC, ki.object_id DESC
      LIMIT $3`,
    [spaceId, userId, limit],
  );
  const sourceIdsByTarget = await loadSourceConnectionIdsForTargets(
    db,
    spaceId,
    "knowledge",
    result.rows.map((row) => row.id),
  );
  const rows = result.rows.map((row) => ({
    ...row,
    source_connection_ids: sourceIdsByTarget.get(row.id) ?? [],
  }));
  return filterBySourcePolicy(db, spaceId, userId, rows);
}

async function loadVisibleNotes(
  db: Queryable,
  spaceId: string,
  userId: string,
  limit: number,
): Promise<VisibleNoteRow[]> {
  const result = await db.query<VisibleNoteRow>(
    `SELECT n.object_id AS id, so.title, n.plain_text, so.status,
            kind.id AS object_kind_id, kind.key AS object_kind, kind.label AS object_kind_label
       FROM notes n
       JOIN space_objects so
         ON so.id = n.object_id
        AND so.space_id = n.space_id
        AND so.object_type = 'note'
       LEFT JOIN space_object_kinds kind
         ON kind.space_id = n.space_id
        AND kind.base_object_type = 'note'
        AND kind.key = 'note'
        AND kind.status = 'active'
      WHERE n.space_id = $1
        AND so.deleted_at IS NULL
        AND so.status = 'active'
        AND ${readableClause("$2")}
      ORDER BY so.updated_at DESC, n.object_id DESC
      LIMIT $3`,
    [spaceId, userId, limit],
  );
  return result.rows;
}

async function loadVisibleActivities(
  db: Queryable,
  spaceId: string,
  userId: string,
  limit: number,
): Promise<VisibleActivityRow[]> {
  const result = await db.query<VisibleActivityRow>(
    `SELECT id, title, content, visibility, owner_user_id, user_id, subject_user_id
       FROM activity_records
      WHERE space_id = $1
        AND status <> 'archived'
        AND (
          visibility = 'space_shared'
          OR owner_user_id = $2
          OR user_id = $2
          OR subject_user_id = $2
        )
      ORDER BY occurred_at DESC, created_at DESC, id DESC
      LIMIT $3`,
    [spaceId, userId, limit],
  );
  return result.rows;
}

async function loadVisibleArtifacts(
  db: Queryable,
  spaceId: string,
  userId: string,
  limit: number,
): Promise<VisibleArtifactRow[]> {
  const result = await db.query<Omit<VisibleArtifactRow, "source_connection_ids">>(
    `SELECT id, title, content, visibility, owner_user_id, metadata_json
       FROM artifacts
      WHERE space_id = $1
        AND content IS NOT NULL
        AND (
          visibility IN ('space_shared', 'public_template')
          OR owner_user_id = $2
          OR (owner_user_id IS NULL AND visibility NOT IN ('workspace_shared', 'restricted', 'selected_users'))
        )
      ORDER BY created_at DESC, id DESC
      LIMIT $3`,
    [spaceId, userId, limit],
  );
  return result.rows.map((row) => ({
    ...row,
    source_connection_ids: sourceConnectionIdsFromMetadata(row.metadata_json),
  }));
}

async function filterBySourcePolicy<T extends { source_connection_ids: string[] }>(
  db: Queryable,
  spaceId: string,
  userId: string,
  rows: readonly T[],
): Promise<T[]> {
  const sourceConnectionIds = uniqueSourceConnectionIds(rows);
  if (sourceConnectionIds.length === 0) return [...rows];
  const [snapshots, viewerSpaceRole] = await Promise.all([
    loadSourcePolicySnapshots(db, spaceId, sourceConnectionIds),
    loadViewerSpaceRole(db, spaceId, userId),
  ]);
  return rows.filter((row) =>
    row.source_connection_ids.every((sourceConnectionId) => {
      const snapshot = snapshots.get(sourceConnectionId);
      return snapshot
        ? sourcePolicyAllowsRead(snapshot, {
            viewerUserId: userId,
            viewerSpaceRole,
          })
        : false;
    }),
  );
}

// --- resolution --------------------------------------------------------------

interface ResolutionEntry {
  itemId: string;
  title: string;
  tier: ConfidenceTier;
}

interface ResolutionIndex {
  exact: Map<string, ResolutionEntry>;
  alias: Map<string, ResolutionEntry>;
}

function buildResolutionIndex(items: readonly VisibleItemRow[]): ResolutionIndex {
  const exact = new Map<string, ResolutionEntry>();
  const alias = new Map<string, ResolutionEntry>();
  for (const item of items) {
    const titleKey = normalizeKey(item.title);
    if (titleKey && !exact.has(titleKey)) exact.set(titleKey, { itemId: item.id, title: item.title, tier: "high" });
    const slugKey = normalizeKey(item.slug);
    if (slugKey && !exact.has(slugKey)) exact.set(slugKey, { itemId: item.id, title: item.title, tier: "high" });
    for (const aliasValue of aliasList(item.aliases_json)) {
      const aliasKey = normalizeKey(aliasValue);
      if (aliasKey && !alias.has(aliasKey)) alias.set(aliasKey, { itemId: item.id, title: item.title, tier: "medium" });
    }
  }
  return { exact, alias };
}

function resolveTarget(index: ResolutionIndex, target: string, label: string | null): ResolutionEntry | null {
  for (const candidate of [cleanTypedTarget(target), label]) {
    const key = normalizeKey(candidate);
    if (!key) continue;
    const exact = index.exact.get(key);
    if (exact) return exact;
    const alias = index.alias.get(key);
    if (alias) return alias;
  }
  return null;
}

function cleanTypedTarget(target: string): string {
  return parseRelationTarget(target).target;
}

function extractRelationLinks(text: string): RelationLink[] {
  const links: RelationLink[] = [];
  const seen = new Set<string>();
  const add = (link: RelationLink): void => {
    const target = link.target.trim();
    if (!target) return;
    const relationType = normalizeRelationType(link.relationType) ?? "related_to";
    const key = `${link.origin}:${relationType}:${target}:${link.label ?? ""}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ ...link, target, relationType });
  };

  for (const link of extractRetrievalLinks(text).filter((item) => item.origin === "wikilink")) {
    if (isTypedDirectiveWikilink(text, link.evidenceText)) continue;
    const parsed = parseRelationTarget(link.target);
    add({
      target: parsed.target,
      label: link.label,
      relationType: parsed.relationType,
      origin: "wikilink",
    });
  }

  const typedDirective = /(?:^|[\s;(])([a-z][a-z0-9_-]{1,32})\s*(?:->|=>|:)\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/gi;
  for (const match of text.matchAll(typedDirective)) {
    const relationType = normalizeRelationType(match[1]);
    if (!relationType) continue;
    add({
      target: match[2]?.trim() ?? "",
      label: match[3]?.trim() || null,
      relationType,
      origin: "typed_directive",
    });
  }

  return links;
}

function isTypedDirectiveWikilink(text: string, evidenceText: string): boolean {
  const escapedEvidence = escapeRegex(evidenceText);
  const directive = new RegExp(
    String.raw`(?:^|[\s;(])([a-z][a-z0-9_-]{1,32})\s*(?:->|=>|:)\s*${escapedEvidence}`,
    "i",
  );
  const match = directive.exec(text);
  return Boolean(normalizeRelationType(match?.[1]));
}

function parseRelationTarget(rawTarget: string): { target: string; relationType: string } {
  const target = rawTarget.trim();
  for (const separator of ["::", ":"]) {
    const idx = target.indexOf(separator);
    if (idx <= 0) continue;
    const relationType = normalizeRelationType(target.slice(0, idx));
    if (relationType) {
      return { target: target.slice(idx + separator.length).trim(), relationType };
    }
  }
  const hashIdx = target.lastIndexOf("#");
  if (hashIdx > 0 && hashIdx < target.length - 1) {
    const relationType = normalizeRelationType(target.slice(hashIdx + 1));
    if (relationType) {
      return { target: target.slice(0, hashIdx).trim(), relationType };
    }
  }
  return { target, relationType: "related_to" };
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeRelationType(value: string | null | undefined): string | null {
  const normalized = value?.trim().toLowerCase().replace(/[\s-]+/g, "_") ?? "";
  return RELATION_TYPES.has(normalized) || OBJECT_RELATION_TYPES.has(normalized)
    ? normalized
    : null;
}

// --- candidate builders ------------------------------------------------------

function relationCandidate(
  source: SourceText,
  resolved: ResolutionEntry,
  relationType: string,
  linkTarget: string,
  linkLabel: string | null,
  linkOrigin: string,
): RelationDiscoveryCandidate {
  const confidence = resolved.tier === "high" ? 0.6 : 0.45;
  return {
    id: randomUUID(),
    kind: "knowledge_relation_candidate",
    cluster_key: `source:${source.id}`,
    title: `Relate: ${shortTitle(source.title)} → ${shortTitle(resolved.title)}`,
    reason: `"${source.title}" links to "${resolved.title}" via ${linkOrigin}; propose a ${relationType} relation.`,
    confidence_tier: resolved.tier,
    evidence_refs: [
      {
        object_type: "knowledge_item",
        object_id: source.id,
        title: source.title,
        link_origin: linkOrigin,
        link_text: linkLabel ?? linkTarget,
      },
      {
        object_type: "knowledge_item",
        object_id: resolved.itemId,
        title: resolved.title,
        link_origin: null,
        link_text: null,
      },
    ],
    markers: { resolution_tier: resolved.tier, relation_type: relationType, link_origin: linkOrigin },
    proposed_action: {
      proposal_type: "knowledge_relation_create",
      from_item_id: source.id,
      to_item_id: resolved.itemId,
      relation_type: relationType,
      confidence,
      evidence_summary: `Discovered from ${linkOrigin} in "${source.title}".`,
    },
  };
}

function objectRelationCandidate(
  source: SourceText,
  resolved: ResolutionEntry,
  relationType: string,
  linkTarget: string,
  linkLabel: string | null,
  linkOrigin: string,
): RelationDiscoveryCandidate {
  const confidence = resolved.tier === "high" ? 0.6 : 0.45;
  // Object relations use a different valid-type set than knowledge relations;
  // fall back to related_to when the typed prefix isn't a valid object relation.
  const objectRelationType = OBJECT_RELATION_TYPES.has(relationType) ? relationType : "related_to";
  return {
    id: randomUUID(),
    kind: "object_relation_candidate",
    cluster_key: `source:${source.id}`,
    title: `Relate: ${shortTitle(source.title)} → ${shortTitle(resolved.title)}`,
    reason: `Note "${source.title}" links to "${resolved.title}" via ${linkOrigin}; propose a ${objectRelationType} object relation.`,
    confidence_tier: resolved.tier,
    evidence_refs: [
      {
        object_type: source.objectType,
        object_id: source.id,
        title: source.title,
        link_origin: linkOrigin,
        link_text: linkLabel ?? linkTarget,
      },
      {
        object_type: "knowledge_item",
        object_id: resolved.itemId,
        title: resolved.title,
        link_origin: null,
        link_text: null,
      },
    ],
    markers: { resolution_tier: resolved.tier, relation_type: objectRelationType, link_origin: linkOrigin },
    proposed_action: {
      proposal_type: "object_relation_create",
      from_object_id: source.id,
      to_object_id: resolved.itemId,
      relation_type: objectRelationType,
      confidence,
      evidence_summary: `Discovered from ${linkOrigin} in note "${source.title}".`,
    },
  };
}

function reviewRelationCandidate(
  source: SourceText,
  resolved: ResolutionEntry,
  relationType: string,
  linkTarget: string,
  linkLabel: string | null,
  linkOrigin: string,
): RelationDiscoveryCandidate {
  return {
    id: randomUUID(),
    kind: "relation_review_candidate",
    cluster_key: `source:${source.id}`,
    title: `Review relation evidence: ${shortTitle(source.title)} → ${shortTitle(resolved.title)}`,
    reason: `${source.objectType} "${source.title}" mentions "${resolved.title}" via ${linkOrigin}; review before creating a governed relation from an appropriate root object.`,
    confidence_tier: resolved.tier === "high" ? "medium" : "low",
    evidence_refs: [
      {
        object_type: source.objectType,
        object_id: source.id,
        title: source.title,
        link_origin: linkOrigin,
        link_text: linkLabel ?? linkTarget,
      },
      {
        object_type: "knowledge_item",
        object_id: resolved.itemId,
        title: resolved.title,
        link_origin: null,
        link_text: null,
      },
    ],
    markers: {
      resolution_tier: resolved.tier,
      relation_type: relationType,
      link_origin: linkOrigin,
      review_only: true,
      review_only_reason: `${source.objectType} is not a space_objects relation endpoint`,
      source_connection_ids: source.sourceConnectionIds,
    },
    proposed_action: null,
  };
}

function itemCandidate(source: SourceText, name: string, linkTarget: string): RelationDiscoveryCandidate {
  return {
    id: randomUUID(),
    kind: "knowledge_item_candidate",
    cluster_key: `source:${source.id}`,
    title: `Create stub: ${shortTitle(name)}`,
    reason: `"${source.title}" links to "${name}" but no visible Knowledge item matches; propose a stub for review.`,
    confidence_tier: "low",
    evidence_refs: [
      {
        object_type: source.objectType,
        object_id: source.id,
        title: source.title,
        link_origin: "internal_link",
        link_text: linkTarget,
      },
    ],
    markers: { unresolved_target: name, source_connection_ids: source.sourceConnectionIds },
    proposed_action: {
      proposal_type: "knowledge_create",
      title: name.slice(0, 200),
      knowledge_kind: "concept",
      content: `Stub created from a wikilink in "${source.title}". Reviewer should fill in the content.`,
      content_format: "markdown",
      visibility: "space_shared",
    },
  };
}

function countsFor(candidates: readonly RelationDiscoveryCandidate[]): Record<string, number> {
  const counts: Record<string, number> = {
    knowledge_relation_candidate: 0,
    object_relation_candidate: 0,
    knowledge_item_candidate: 0,
    relation_review_candidate: 0,
    proposal_candidate: 0,
    review_only_candidate: 0,
    high: 0,
    medium: 0,
    low: 0,
  };
  for (const candidate of candidates) {
    counts[candidate.kind] = (counts[candidate.kind] ?? 0) + 1;
    if (candidate.proposed_action) {
      counts.proposal_candidate += 1;
    } else {
      counts.review_only_candidate += 1;
    }
    counts[candidate.confidence_tier] = (counts[candidate.confidence_tier] ?? 0) + 1;
  }
  return counts;
}

// --- text helpers ------------------------------------------------------------

function itemText(item: VisibleItemRow): string {
  // Raw content first — wikilink syntax usually survives there; plain_text is a
  // fallback for items that only stored extracted text.
  return [item.content, item.plain_text].filter((value): value is string => Boolean(value)).join("\n");
}

function aliasList(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((entry): entry is string => typeof entry === "string");
  return [];
}

function normalizeKey(value: string | null | undefined): string {
  return value?.toLowerCase().replace(/\s+/g, " ").trim() ?? "";
}

function shortTitle(value: string): string {
  const trimmed = value.trim();
  return trimmed.length > 60 ? `${trimmed.slice(0, 57)}...` : trimmed;
}

function uniqueSourceConnectionIds(rows: readonly { source_connection_ids: readonly string[] }[]): string[] {
  const out: string[] = [];
  for (const row of rows) {
    for (const id of row.source_connection_ids) {
      const normalized = id.trim();
      if (normalized && !out.includes(normalized)) out.push(normalized);
    }
  }
  return out;
}

function uniqueResolutionEntries(index: ResolutionIndex): ResolutionEntry[] {
  const out = new Map<string, ResolutionEntry>();
  for (const entry of index.exact.values()) out.set(entry.itemId, entry);
  for (const entry of index.alias.values()) out.set(entry.itemId, entry);
  return [...out.values()];
}

async function loadRelationHintsForSources(
  db: Queryable,
  spaceId: string,
  sources: readonly SourceText[],
): Promise<RelationDiscoveryRelationHint[]> {
  const sourceKindIds = [...new Set(sources.map((source) => source.objectKindId).filter((id): id is string => Boolean(id)))];
  if (sourceKindIds.length === 0) return [];
  const result = await db.query<{
    id: string;
    object_kind_id: string;
    object_kind: string;
    object_kind_label: string;
    endpoint_object_type: string;
    endpoint_object_kind_id: string | null;
    endpoint_object_kind: string | null;
    endpoint_object_kind_label: string | null;
    relation_type: string;
    direction: string;
    confidence_default: number | string;
    required: boolean;
  }>(
    `SELECT h.id,
            h.object_kind_id,
            source_kind.key AS object_kind,
            source_kind.label AS object_kind_label,
            h.endpoint_object_type,
            h.endpoint_object_kind_id,
            endpoint_kind.key AS endpoint_object_kind,
            endpoint_kind.label AS endpoint_object_kind_label,
            h.relation_type,
            h.direction,
            h.confidence_default,
            h.required
       FROM space_object_kind_relation_hints h
       JOIN space_object_kinds source_kind
         ON source_kind.id = h.object_kind_id
        AND source_kind.space_id = h.space_id
        AND source_kind.status = 'active'
       LEFT JOIN space_object_kinds endpoint_kind
         ON endpoint_kind.id = h.endpoint_object_kind_id
        AND endpoint_kind.space_id = h.space_id
      WHERE h.space_id = $1
        AND h.object_kind_id = ANY($2::varchar[])
        AND (h.endpoint_object_kind_id IS NULL OR endpoint_kind.status = 'active')
      ORDER BY source_kind.key ASC, h.required DESC, h.relation_type ASC, h.id ASC`,
    [spaceId, sourceKindIds],
  );
  return result.rows
    .filter((row) => row.direction === "from" || row.direction === "to" || row.direction === "either")
    .map((row) => ({
      id: row.id,
      object_kind_id: row.object_kind_id,
      object_kind: row.object_kind,
      object_kind_label: row.object_kind_label,
      endpoint_object_type: row.endpoint_object_type,
      endpoint_object_kind_id: row.endpoint_object_kind_id,
      endpoint_object_kind: row.endpoint_object_kind,
      endpoint_object_kind_label: row.endpoint_object_kind_label,
      relation_type: row.relation_type,
      direction: row.direction as "from" | "to" | "either",
      confidence_default: relationHintConfidence(row.confidence_default),
      required: row.required === true,
    }));
}

async function detectRequiredRelationHintGaps(
  db: Queryable,
  input: RelationDiscoveryScanInput,
  sources: readonly SourceText[],
  existingCandidates: readonly RelationDiscoveryCandidate[],
): Promise<RelationDiscoveryCandidate[]> {
  const hints = (await loadRelationHintsForSources(db, input.spaceId, sources)).filter((hint) => hint.required);
  if (hints.length === 0) return [];
  const hintsBySourceKind = new Map<string, RelationDiscoveryRelationHint[]>();
  for (const hint of hints) {
    const arr = hintsBySourceKind.get(hint.object_kind_id) ?? [];
    arr.push(hint);
    hintsBySourceKind.set(hint.object_kind_id, arr);
  }

  const gaps: RelationDiscoveryCandidate[] = [];
  for (const source of sources) {
    if (!source.objectKindId) continue;
    const sourceHints = hintsBySourceKind.get(source.objectKindId) ?? [];
    for (const hint of sourceHints) {
      if (existingCandidateCoversHint(source, hint, existingCandidates)) continue;
      const hasRelation = await hasVisibleRequiredHintRelation(db, input.spaceId, input.userId, source, hint);
      if (!hasRelation) gaps.push(requiredRelationHintGapCandidate(source, hint));
    }
  }
  return gaps;
}

function existingCandidateCoversHint(
  source: SourceText,
  hint: RelationDiscoveryRelationHint,
  candidates: readonly RelationDiscoveryCandidate[],
): boolean {
  return candidates.some((candidate) => {
    const action = candidate.proposed_action;
    const relationType = action && "relation_type" in action && typeof action.relation_type === "string"
      ? action.relation_type
      : typeof candidate.markers?.relation_type === "string"
        ? candidate.markers.relation_type
        : null;
    if (relationType !== hint.relation_type) return false;
    return candidate.evidence_refs.some((ref) => ref.object_id === source.id && ref.object_type === source.objectType);
  });
}

async function hasVisibleRequiredHintRelation(
  db: Queryable,
  spaceId: string,
  userId: string,
  source: SourceText,
  hint: RelationDiscoveryRelationHint,
): Promise<boolean> {
  return source.objectType === "knowledge_item" && hint.endpoint_object_type === "knowledge_item"
    ? hasVisibleKnowledgeHintRelation(db, spaceId, userId, source.id, hint)
    : hasVisibleObjectHintRelation(db, spaceId, userId, source.id, hint);
}

async function hasVisibleKnowledgeHintRelation(
  db: Queryable,
  spaceId: string,
  userId: string,
  sourceObjectId: string,
  hint: RelationDiscoveryRelationHint,
): Promise<boolean> {
  const allowFrom = hint.direction !== "to";
  const allowTo = hint.direction !== "from";
  const result = await db.query<{ id: string }>(
    `SELECT r.id
       FROM knowledge_item_relations r
       JOIN knowledge_items other_ki
         ON other_ki.object_id = CASE WHEN r.from_item_id = $3 THEN r.to_item_id ELSE r.from_item_id END
        AND other_ki.space_id = r.space_id
       JOIN space_objects other_so
         ON other_so.id = other_ki.object_id
        AND other_so.space_id = other_ki.space_id
        AND other_so.object_type = 'knowledge_item'
       LEFT JOIN space_object_kinds endpoint_kind
         ON endpoint_kind.space_id = other_ki.space_id
        AND endpoint_kind.base_object_type = 'knowledge_item'
        AND endpoint_kind.key = other_ki.knowledge_kind
        AND endpoint_kind.status = 'active'
      WHERE r.space_id = $1
        AND r.status = 'active'
        AND r.relation_type = $2
        AND (($4::boolean AND r.from_item_id = $3) OR ($5::boolean AND r.to_item_id = $3))
        AND other_so.deleted_at IS NULL
        AND other_so.status = 'active'
        AND ${readableClause("$6", "other_so")}
        AND ($7::varchar IS NULL OR endpoint_kind.id = $7)
      LIMIT 1`,
    [spaceId, hint.relation_type, sourceObjectId, allowFrom, allowTo, userId, hint.endpoint_object_kind_id],
  );
  return result.rows.length > 0;
}

async function hasVisibleObjectHintRelation(
  db: Queryable,
  spaceId: string,
  userId: string,
  sourceObjectId: string,
  hint: RelationDiscoveryRelationHint,
): Promise<boolean> {
  const allowFrom = hint.direction !== "to";
  const allowTo = hint.direction !== "from";
  const result = await db.query<{ id: string }>(
    `SELECT r.id
       FROM object_relations r
       JOIN space_objects other_so
         ON other_so.id = CASE WHEN r.from_object_id = $3 THEN r.to_object_id ELSE r.from_object_id END
        AND other_so.space_id = r.space_id
       LEFT JOIN knowledge_items other_ki
         ON other_ki.object_id = other_so.id
        AND other_ki.space_id = other_so.space_id
        AND other_so.object_type = 'knowledge_item'
       LEFT JOIN claims other_claim
         ON other_claim.object_id = other_so.id
        AND other_claim.space_id = other_so.space_id
        AND other_so.object_type = 'claim'
       LEFT JOIN sources other_source
         ON other_source.object_id = other_so.id
        AND other_source.space_id = other_so.space_id
        AND other_so.object_type = 'source'
       LEFT JOIN memory_entries other_memory
         ON other_memory.id = other_so.id
        AND other_memory.space_id = other_so.space_id
        AND other_so.object_type = 'memory_entry'
       LEFT JOIN space_object_kinds endpoint_kind
         ON endpoint_kind.space_id = other_so.space_id
        AND endpoint_kind.base_object_type = other_so.object_type
        AND endpoint_kind.key = CASE
          WHEN other_so.object_type = 'knowledge_item' THEN other_ki.knowledge_kind
          WHEN other_so.object_type = 'claim' THEN other_claim.claim_kind
          WHEN other_so.object_type = 'source' THEN other_source.source_type
          WHEN other_so.object_type = 'note' THEN 'note'
          WHEN other_so.object_type = 'memory_entry' THEN other_memory.memory_type
          WHEN other_so.object_type = 'project_public_summary' THEN 'project_public_summary'
          ELSE NULL
        END
        AND endpoint_kind.status = 'active'
      WHERE r.space_id = $1
        AND r.status = 'active'
        AND r.relation_type = $2
        AND (($4::boolean AND r.from_object_id = $3) OR ($5::boolean AND r.to_object_id = $3))
        AND other_so.deleted_at IS NULL
        AND (
          (other_so.object_type = 'source' AND other_so.status <> 'archived')
          OR (other_so.object_type <> 'source' AND other_so.status = 'active')
        )
        AND other_so.object_type = $7
        AND ${readableClause("$6", "other_so")}
        AND ($8::varchar IS NULL OR endpoint_kind.id = $8)
      LIMIT 1`,
    [spaceId, hint.relation_type, sourceObjectId, allowFrom, allowTo, userId, hint.endpoint_object_type, hint.endpoint_object_kind_id],
  );
  return result.rows.length > 0;
}

function requiredRelationHintGapCandidate(
  source: SourceText,
  hint: RelationDiscoveryRelationHint,
): RelationDiscoveryCandidate {
  return {
    id: randomUUID(),
    kind: "relation_review_candidate",
    cluster_key: `schema_hint:${hint.id}`,
    title: `Review missing relation: ${shortTitle(source.title)}`,
    reason: `${source.objectKindLabel ?? source.objectKind ?? source.objectType} "${source.title}" has a required ${hint.relation_type} relation hint with no matching visible active relation.`,
    confidence_tier: "low",
    evidence_refs: [
      {
        object_type: source.objectType,
        object_id: source.id,
        title: source.title,
        link_origin: "schema_relation_hint",
        link_text: null,
      },
    ],
    markers: {
      review_only: true,
      review_only_reason: "required_relation_hint_gap",
      schema_relation_hint_id: hint.id,
      object_kind: source.objectKind,
      object_kind_label: source.objectKindLabel,
      endpoint_object_type: hint.endpoint_object_type,
      endpoint_object_kind: hint.endpoint_object_kind,
      endpoint_object_kind_label: hint.endpoint_object_kind_label,
      relation_type: hint.relation_type,
      relation_direction: hint.direction,
      required_hint_gap: true,
    },
    proposed_action: null,
  };
}

function relationHintConfidence(value: unknown): number {
  const n = typeof value === "number"
    ? value
    : typeof value === "string"
      ? Number(value)
      : Number.NaN;
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : 0.55;
}

async function runOptionalLlmExtraction(
  db: Queryable,
  input: RelationDiscoveryScanInput,
  sources: readonly SourceText[],
  visibleTargets: readonly ResolutionEntry[],
  existingCandidateCount: number,
): Promise<{
  candidates: RelationDiscoveryCandidate[];
  used: boolean;
  summary: Record<string, unknown>;
}> {
  if (!input.request.llm_extraction_enabled) {
    return { candidates: [], used: false, summary: { requested: false, used: false } };
  }
  if (!input.llmExtractor) {
    return {
      candidates: [],
      used: false,
      summary: { requested: true, used: false, skipped_reason: "llm_extractor_unavailable" },
    };
  }
  const llmSources = sources.slice(0, input.request.llm_max_sources);
  const sourceConnectionIds = [...new Set(llmSources.flatMap((source) => source.sourceConnectionIds))];
  const sourcePolicies = await loadSourcePolicySnapshotRecord(db, input.spaceId, sourceConnectionIds);
  const relationHints = await loadRelationHintsForSources(db, input.spaceId, llmSources);
  if (sourceConnectionIds.length > 0 && Object.keys(sourcePolicies).length !== sourceConnectionIds.length) {
    return {
      candidates: [],
      used: false,
      summary: { requested: true, used: false, skipped_reason: "source_policy_unavailable" },
    };
  }
  const maxCandidates = Math.max(0, input.request.max_candidates - existingCandidateCount);
  if (maxCandidates === 0) {
    return {
      candidates: [],
      used: false,
      summary: { requested: true, used: false, skipped_reason: "candidate_cap_reached" },
    };
  }
  try {
    const candidates = await input.llmExtractor.extract({
      spaceId: input.spaceId,
      userId: input.userId,
      sources: llmSources,
      visibleTargets,
      relationHints,
      maxCandidates,
      sourcePolicies,
      payloadSourceConnectionIds: sourceConnectionIds,
    });
    return {
      candidates: candidates.slice(0, maxCandidates),
      used: candidates.length > 0,
      summary: {
        requested: true,
        used: candidates.length > 0,
        candidate_count: Math.min(candidates.length, maxCandidates),
        source_count: llmSources.length,
        relation_hint_count: relationHints.length,
        payload_source_connection_count: sourceConnectionIds.length,
      },
    };
  } catch (error) {
    return {
      candidates: [],
      used: false,
      summary: {
        requested: true,
        used: false,
        skipped_reason: "llm_extraction_failed",
        error_class: error instanceof Error ? error.name : "unknown",
      },
    };
  }
}

async function loadSourcePolicySnapshotRecord(
  db: Queryable,
  spaceId: string,
  sourceConnectionIds: readonly string[],
): Promise<Record<string, unknown>> {
  const snapshots = await loadSourcePolicySnapshots(db, spaceId, sourceConnectionIds);
  const out: Record<string, unknown> = {};
  for (const [id, snapshot] of snapshots.entries()) out[id] = snapshot;
  return out;
}
