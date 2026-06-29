import { diaryApi } from '../../api/client'
import { SpaceLink } from '../../core/spaceNav'
import { useEffectivePlugins } from '../../modules/plugins/useEffectivePlugins'
import {
  createDiaryPage,
  type DiaryWebHost,
} from '../../../../../plugins/official/diary/web/src/DiaryPage'

const host: DiaryWebHost = {
  api: diaryApi,
  Link: SpaceLink,
  usePluginState(pluginId) {
    const { isEnabled, loading } = useEffectivePlugins()
    return { enabled: isEnabled(pluginId), loading }
  },
}

export default createDiaryPage(host)
