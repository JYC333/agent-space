import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Artifact } from '../../../types/api'
import { ArtifactInlineRenderer } from '../ArtifactRendererRegistry'

function artifact(overrides: Partial<Artifact>): Artifact {
  return {
    id: 'artifact-1',
    space_id: 'space-1',
    run_id: null,
    proposal_id: null,
    artifact_type: 'research_brief.v1',
    title: 'Research artifact',
    mime_type: 'application/json',
    exportable: true,
    preview: false,
    storage_ref: null,
    storage_path: null,
    has_inline_content: true,
    content: '',
    created_at: '2026-06-20T00:00:00.000Z',
    updated_at: '2026-06-20T00:00:00.000Z',
    ...overrides,
  }
}

describe('ArtifactInlineRenderer', () => {
  it('renders structured research briefs', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          content: JSON.stringify({
            title: 'Storage strategy',
            summary: 'Use project-scoped evidence before broader synthesis.',
            findings: [
              { finding: 'Source metadata should be preserved.', confidence: 'high' },
            ],
            citations: [
              { title: 'Architecture note', url: 'https://example.com/arch' },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Storage strategy')).toBeInTheDocument()
    expect(screen.getByText('Source metadata should be preserved.')).toBeInTheDocument()
    expect(screen.getByText('Architecture note')).toBeInTheDocument()
  })

  it('renders source tables from JSON rows', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'research_source_table.v1',
          content: JSON.stringify({
            sources: [
              {
                title: 'Primary source',
                publisher: 'Example Org',
                date: '2026-06-20',
                relevance: 'core',
                summary: 'Contains the source claim.',
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Primary source')).toBeInTheDocument()
    expect(screen.getByText('Example Org')).toBeInTheDocument()
    expect(screen.getByText('Contains the source claim.')).toBeInTheDocument()
  })

  it('falls back to inline text for unstructured content', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'research_idea_candidates.v1',
          mime_type: 'text/plain',
          content: 'Plain candidate notes',
        })}
      />,
    )

    expect(screen.getByText('Plain candidate notes')).toBeInTheDocument()
  })
})
