export type AddProviderMode = 'chat' | 'embedding' | 'rerank'

export interface ProviderCapability {
  key: string
  label: string
  detail: string
  variant: 'default' | 'secondary' | 'muted' | 'outline'
}

export interface ModelFieldCopy {
  defaultLabel: string
  availableLabel: string
  defaultPlaceholder: string
  availablePlaceholder: string
  help: string
}
