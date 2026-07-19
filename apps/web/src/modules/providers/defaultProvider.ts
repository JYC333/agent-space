import type { ModelProviderOut } from '../../api/client'

/**
 * Resolve the provider a surface should preselect: the space default when it
 * is enabled (and passes the surface's own capability filter), otherwise the
 * first eligible provider. Mirrors the backend's run-time resolution, so what
 * the UI preselects is what an empty execution would run with anyway.
 */
export function defaultModelProvider(
  providers: ModelProviderOut[],
  selectable?: (provider: ModelProviderOut) => boolean,
): ModelProviderOut | null {
  const eligible = providers.filter(provider => provider.enabled && (selectable?.(provider) ?? true))
  return eligible.find(provider => provider.is_default) ?? eligible[0] ?? null
}
