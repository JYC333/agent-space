export const CONTEXT_ATTACHABLE_ARTIFACT_TYPES = [
  'retrieval_brief',
  'retrieval_eval_report',
  'retrieval_explain_report',
  'retrieval_maintenance_report',
  'memory_maintenance_report',
] as const

const CONTEXT_ATTACHABLE_ARTIFACT_TYPE_SET = new Set<string>(CONTEXT_ATTACHABLE_ARTIFACT_TYPES)

export function isContextAttachableArtifactType(type: string): boolean {
  return CONTEXT_ATTACHABLE_ARTIFACT_TYPE_SET.has(type)
}
