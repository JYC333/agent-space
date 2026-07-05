import { useLocation } from 'react-router-dom'
import { researchAtlasApi } from '../../api/client'
import { GraphView as AppGraphView } from '../../components/graph'
import { SpaceLink } from '../../core/spaceNav'
import { useTheme } from '../../contexts/ThemeContext'
import { useEffectivePlugins } from '../../modules/plugins/useEffectivePlugins'
import {
  createResearchAtlasPage,
  type ResearchAtlasGraphViewProps,
  type ResearchAtlasWebHost,
} from '../../../../../plugins/official/research_atlas/web/src/ResearchAtlasPage'

function ResearchAtlasGraphView(props: ResearchAtlasGraphViewProps) {
  const { theme } = useTheme()
  return <AppGraphView {...props} themeMode={theme} />
}

const host: ResearchAtlasWebHost = {
  api: researchAtlasApi,
  Link: SpaceLink,
  GraphView: ResearchAtlasGraphView,
  usePluginState(pluginId) {
    const { isEnabled, loading } = useEffectivePlugins()
    return { enabled: isEnabled(pluginId), loading }
  },
  usePathname() {
    return useLocation().pathname
  },
}

export default createResearchAtlasPage(host)
