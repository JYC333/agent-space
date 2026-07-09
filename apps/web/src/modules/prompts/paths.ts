export function promptLibraryPath(assetKey?: string | null): string {
  const key = assetKey?.trim()
  return key ? `/prompts?asset=${encodeURIComponent(key)}` : '/prompts'
}
