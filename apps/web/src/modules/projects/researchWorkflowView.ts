import type { ProjectResearchWorkflow } from '../../types/api'

export function researchWorkflowForDisplayFrom(workflows: ProjectResearchWorkflow[]): ProjectResearchWorkflow | null {
  return workflows.find(workflow => workflow.status === 'active')
    ?? workflows
      .filter(workflow => workflow.status !== 'archived')
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
    ?? null
}
