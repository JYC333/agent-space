import { render, screen } from '@testing-library/react'
import type { ComponentType, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import ResearchAtlasPageAdapter from '../ResearchAtlasPageAdapter'

const graphViewSpy = vi.hoisted(() => vi.fn())

vi.mock('../../../api/client', () => ({
  researchAtlasApi: {},
}))

vi.mock('../../../core/spaceNav', () => ({
  SpaceLink: ({ to, children }: { to: string; children?: ReactNode }) => <a href={to}>{children}</a>,
}))

vi.mock('../../../modules/plugins/useEffectivePlugins', () => ({
  useEffectivePlugins: () => ({
    loading: false,
    isEnabled: (pluginId: string) => pluginId === 'research_atlas',
  }),
}))

vi.mock('../../../contexts/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: () => {}, toggleTheme: () => {} }),
}))

vi.mock('../../../components/graph', () => ({
  GraphView: (props: { projection: { nodes: unknown[] } | null; themeMode?: string }) => {
    graphViewSpy(props)
    return <div data-testid="host-graph-view">nodes:{props.projection?.nodes.length ?? 0}</div>
  },
}))

vi.mock('../../../../../../plugins/official/research_atlas/web/src/ResearchAtlasPage', () => ({
  createResearchAtlasPage: (host: {
    GraphView: ComponentType<{ projection: { nodes: unknown[] } | null }>
    usePluginState(pluginId: string): { enabled: boolean }
  }) => {
    return function MockResearchAtlasPage() {
      const GraphView = host.GraphView
      const state = host.usePluginState('research_atlas')
      return (
        <div>
          <span>{state.enabled ? 'enabled' : 'disabled'}</span>
          <GraphView projection={{ nodes: [{ id: 'paper:adapter' }] }} />
        </div>
      )
    }
  },
}))

describe('ResearchAtlasPageAdapter', () => {
  it('injects the shared GraphView through the plugin host', () => {
    render(<ResearchAtlasPageAdapter />)

    expect(screen.getByText('enabled')).toBeInTheDocument()
    expect(screen.getByTestId('host-graph-view')).toHaveTextContent('nodes:1')
    expect(graphViewSpy).toHaveBeenCalledWith(expect.objectContaining({
      projection: { nodes: [{ id: 'paper:adapter' }] },
      themeMode: 'dark',
    }))
  })
})
