import { dairyApi } from '../../api/client'
import { SpaceLink } from '../../core/spaceNav'
import { useEffectivePlugins } from '../../modules/plugins/useEffectivePlugins'
import {
  createDairyPage,
  type DairyWebHost,
} from '../../../../../plugins/official/dairy/web/src/DairyPage'

const host: DairyWebHost = {
  api: dairyApi,
  Link: SpaceLink,
  usePluginState(pluginId) {
    const { isEnabled, loading } = useEffectivePlugins()
    return { enabled: isEnabled(pluginId), loading }
  },
}

export default createDairyPage(host)
