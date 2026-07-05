import type { OfficialPluginDescriptor } from "@agent-space/protocol" with { "resolution-mode": "import" };

export const RESEARCH_ATLAS_PLUGIN_ID = "research_atlas";
export const RESEARCH_ATLAS_PLUGIN_VERSION = "0.1.0";

/**
 * research_atlas — official optional module descriptor.
 *
 * Runtime behavior lives under `plugins/official/research_atlas/` and is
 * loaded by PluginHost from the compiled official plugin artifact.
 */
export const researchAtlasDescriptor: OfficialPluginDescriptor = {
  id: RESEARCH_ATLAS_PLUGIN_ID,
  name: "Research Atlas",
  description:
    "A space-scoped scholarly graph for papers, scholars, institutions, venues, provenance, and project literature workflows.",
  version: RESEARCH_ATLAS_PLUGIN_VERSION,
  category: "knowledge",
  default_enabled: false,
  default_visible: true,
  scope: "space",
  lifecycle_status: "available",
  frontend_entries: [
    {
      module_id: "research_atlas",
      label: "Research Atlas",
      path: "/atlas",
      icon: "network",
      section: "knowledge",
      group: "knowledge",
    },
  ],
  backend_feature_ids: [
    "research_atlas_graph",
    "research_atlas_sources",
    "research_atlas_project_overlay",
  ],
  permissions: {
    creates_activity: false,
    can_propose_memory: false,
    can_contribute_context: "never",
    uses_ai: false,
    uses_scheduler: true,
  },
  settings_defaults: {
    intake_sync_enabled: true,
    crossref_enabled: true,
    openalex_enabled: true,
    auto_add_project_candidates: true,
    connector_email: null,
  },
};
