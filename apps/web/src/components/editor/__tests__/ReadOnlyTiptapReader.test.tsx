import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ReadOnlyTiptapReader } from '../ReadOnlyTiptapReader'

describe('ReadOnlyTiptapReader', () => {
  it('creates a whole-block selection when a paragraph is clicked', async () => {
    const onTextSelected = vi.fn()
    render(
      <ReadOnlyTiptapReader
        contentJson={{
          type: 'doc',
          content: [
            { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph.' }] },
            { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
          ],
        }}
        normalizedText="First paragraph. Second paragraph."
        onTextSelected={onTextSelected}
      />,
    )

    fireEvent.click(await screen.findByText('Second paragraph.'))

    await waitFor(() => {
      expect(onTextSelected).toHaveBeenLastCalledWith(expect.objectContaining({
        quoteText: 'Second paragraph.',
        anchorDraft: expect.objectContaining({
          quote_text: 'Second paragraph.',
          block_ref: expect.objectContaining({ index: 1, node_type: 'paragraph' }),
        }),
      }))
    })
  })

  it('renders reader table nodes', async () => {
    render(
      <ReadOnlyTiptapReader
        contentJson={{
          type: 'doc',
          content: [{
            type: 'table',
            content: [{
              type: 'tableRow',
              content: [
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'No.' }] }] },
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: '行程概览' }] }] },
              ],
            }, {
              type: 'tableRow',
              content: [
                { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Day 1' }] }] },
                { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: '北京大兴→乌鲁木齐' }] }] },
              ],
            }],
          }],
        }}
        normalizedText="No. 行程概览 Day 1 北京大兴→乌鲁木齐"
      />,
    )

    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'No.' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Day 1' })).toBeInTheDocument()
  })
})
