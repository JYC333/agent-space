import { RESEARCH_PACK } from "./researchPack";
import { getBuiltInCapabilityDefinition } from "./registry";
import { getBuiltInWorkflowTemplate } from "./workflowRegistry";
import type { CapabilityPackDescriptor } from "./types";

export function listBuiltInCapabilityPacks(): CapabilityPackDescriptor[] {
  return [RESEARCH_PACK].sort((a, b) => a.id.localeCompare(b.id));
}

export function getBuiltInCapabilityPack(id: string): CapabilityPackDescriptor | null {
  return listBuiltInCapabilityPacks().find((pack) => pack.id === id) ?? null;
}

export function assertPackReferencesValid(packs: readonly CapabilityPackDescriptor[]): void {
  for (const pack of packs) {
    for (const capabilityId of pack.capability_ids) {
      if (!getBuiltInCapabilityDefinition(capabilityId)) {
        throw new Error(`pack ${pack.id} references missing capability ${capabilityId}`);
      }
    }
    for (const workflowTemplateId of pack.workflow_template_ids) {
      if (!getBuiltInWorkflowTemplate(workflowTemplateId)) {
        throw new Error(`pack ${pack.id} references missing workflow ${workflowTemplateId}`);
      }
    }
  }
}

