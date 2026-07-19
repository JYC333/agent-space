import type { ResearchNotebookSection } from '../../../types/api'

export const SECTION_LABELS: Record<ResearchNotebookSection['section_key'], string> = {
  understanding: 'Current understanding',
  questions: 'Open questions',
  ideas: 'Idea pool',
  experiments: 'Experiment log',
}
