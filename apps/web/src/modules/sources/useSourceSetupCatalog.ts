import { useEffect, useState } from 'react'
import { sourcesApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import type { SourceProvider, SourceProviderCategoryGroup } from '../../types/api'

interface SourceSetupCatalogState {
  providers: SourceProvider[]
  categoryGroups: readonly SourceProviderCategoryGroup[]
  loading: boolean
  error: string | null
}

/** Loads the provider metadata required by the reusable source setup form. */
export function useSourceSetupCatalog(enabled: boolean): SourceSetupCatalogState {
  const { activeSpaceId } = useSpace()
  const [state, setState] = useState<SourceSetupCatalogState>({
    providers: [],
    categoryGroups: [],
    loading: false,
    error: null,
  })

  useEffect(() => {
    if (!enabled || !activeSpaceId) return
    let cancelled = false
    setState(current => ({ ...current, loading: true, error: null }))
    void sourcesApi.providers()
      .then(providers => {
        if (cancelled) return
        setState({
          providers,
          categoryGroups: providers.find(provider => provider.provider_key === 'arxiv')?.setup_schema?.category_groups ?? [],
          loading: false,
          error: null,
        })
      })
      .catch(error => {
        if (cancelled) return
        setState(current => ({ ...current, loading: false, error: error instanceof Error ? error.message : 'Unable to load source platforms' }))
      })
    return () => { cancelled = true }
  }, [activeSpaceId, enabled])

  return state
}
