import { describe, expect, it } from "vitest";
import {
  RESEARCH_ATLAS_PLUGIN_ID,
  researchAtlasDescriptor,
} from "../src/modules/plugins/official/researchAtlas";
import { getOfficialPlugin } from "../src/modules/plugins/registry";
import { loadResearchAtlasRuntime } from "./researchAtlasRuntime";

const {
  plugin: { researchAtlasPlugin },
} = loadResearchAtlasRuntime();

const REQUIRED_BASE_TABLES = [
  "research_atlas_papers",
  "research_atlas_scholars",
  "research_atlas_institutions",
  "research_atlas_venues",
  "research_atlas_authorships",
  "research_atlas_external_ids",
  "research_atlas_source_records",
  "research_atlas_entity_sources",
  "research_atlas_curation_events",
  "research_atlas_sync_cursors",
  "research_atlas_project_papers",
  "research_atlas_departments",
  "research_atlas_topics",
  "research_atlas_research_groups",
  "research_atlas_affiliations",
  "research_atlas_citation_edges",
  "research_atlas_group_memberships",
  "research_atlas_paper_topics",
  "research_atlas_scholar_topics",
  "research_atlas_project_scholars",
  "research_atlas_project_groups",
  "research_atlas_saved_views",
];

describe("research atlas official plugin descriptor", () => {
  it("is registered as a space-scoped official optional module", () => {
    expect(getOfficialPlugin(RESEARCH_ATLAS_PLUGIN_ID)).toEqual(researchAtlasDescriptor);
    expect(researchAtlasDescriptor.scope).toBe("space");
    expect(researchAtlasDescriptor.default_enabled).toBe(false);
    expect(researchAtlasDescriptor.permissions.uses_scheduler).toBe(true);
  });
});

describe("research atlas plugin schema", () => {
  it("bundles an installer-managed migration for the base scholarly graph", () => {
    const migration = researchAtlasPlugin.migrations?.find(
      (candidate: { id: string }) => candidate.id === "0001_create_research_atlas_base",
    );

    expect(migration).toBeDefined();
    for (const table of REQUIRED_BASE_TABLES) {
      expect(migration!.sql).toContain(`CREATE TABLE public.${table}`);
    }
  });

  it("keeps base research atlas tables space scoped", () => {
    const migration = researchAtlasPlugin.migrations![0]!;
    for (const table of REQUIRED_BASE_TABLES) {
      const createIndex = migration.sql.indexOf(`CREATE TABLE public.${table}`);
      const nextCreate = migration.sql.indexOf("CREATE TABLE public.", createIndex + 1);
      const block = migration.sql.slice(createIndex, nextCreate === -1 ? undefined : nextCreate);
      expect(block).toContain("space_id");
      expect(block).toContain("CHECK (length(trim(space_id)) > 0)");
    }
  });
});
