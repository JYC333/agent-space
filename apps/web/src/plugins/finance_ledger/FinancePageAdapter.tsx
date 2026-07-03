import { financeApi } from '../../api/client'
import { SpaceLink } from '../../core/spaceNav'
import { useEffectivePlugins } from '../../modules/plugins/useEffectivePlugins'
import {
  createFinancePage,
  type FinanceWebHost,
} from '../../../../../plugins/official/finance_ledger/web/src/FinancePage'

const host: FinanceWebHost = {
  api: financeApi,
  Link: SpaceLink,
  usePluginState(pluginId) {
    const { isEnabled, loading } = useEffectivePlugins()
    return { enabled: isEnabled(pluginId), loading }
  },
}

export default createFinancePage(host)
