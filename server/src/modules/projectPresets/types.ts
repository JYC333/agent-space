export interface ProjectPresetDescriptor {
  key: string;
  name: string;
  description: string;
  sections: string[];
  extraction_profile_key: string | null;
  graph_lens_id: string | null;
}
