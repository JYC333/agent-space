import type { ProjectPresetDescriptor } from "./types";

// Built-in Project presets. Static/code-owned, matching the capabilities
// module's packRegistry.ts pattern: presets are not DB-seeded.
//
// `source_preset_ids: ["arxiv"]` reflects the source presets that actually
// exist in core today (server/src/modules/sources/sourcePresets/). Crossref
// and OpenAlex do not have core connectors yet, so they are deliberately left
// out here rather than referencing a preset id that doesn't resolve to anything.
const ACADEMIC_RESEARCH_PRESET: ProjectPresetDescriptor = {
  key: "academic_research",
  name: "Academic Research",
  description: "Literature monitoring workflow over normal Project Sources with academic paper extraction defaults.",
  // Corpus and project graph are backed by the core Project Sources + Project
  // Corpus foundation. Paper/citation data uses the academic object extension
  // but remains reachable through the normal Project surface.
  sections: ["source_monitoring", "corpus", "project_graph"],
  source_preset_ids: ["arxiv"],
  extraction_profile_key: "academic_paper_v1",
  graph_lens_id: "academic_citation_v1",
};

const BUILT_IN_PROJECT_PRESETS: ProjectPresetDescriptor[] = [ACADEMIC_RESEARCH_PRESET];

let registryOverrideForTests: ProjectPresetDescriptor[] | null = null;

export function __setProjectPresetRegistryForTests(presets: ProjectPresetDescriptor[] | null): void {
  registryOverrideForTests = presets;
}

export function listBuiltInProjectPresets(): ProjectPresetDescriptor[] {
  return [...(registryOverrideForTests ?? BUILT_IN_PROJECT_PRESETS)].sort((a, b) => a.key.localeCompare(b.key));
}

export function getBuiltInProjectPreset(key: string): ProjectPresetDescriptor | null {
  return listBuiltInProjectPresets().find((preset) => preset.key === key) ?? null;
}
