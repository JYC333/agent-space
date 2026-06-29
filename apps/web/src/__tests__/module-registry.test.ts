import { describe, expect, it } from 'vitest'
import { MODULE_REGISTRY, modulesWithEffectivePlugins } from '../modules/registry'

describe('module registry official plugin overlay', () => {
  it('overlays official plugin enabled and visible state from the backend map', () => {
    const modules = modulesWithEffectivePlugins(MODULE_REGISTRY, {
      diary: { enabled: true, visible: false },
    })

    const diary = modules.find(module => module.id === 'diary')
    expect(diary?.enabled).toBe(true)
    expect(diary?.visible).toBe(false)
  })

  it('leaves built-in modules on their static registration state', () => {
    const original = MODULE_REGISTRY.find(module => module.id === 'today')
    const modules = modulesWithEffectivePlugins(MODULE_REGISTRY, {
      today: { enabled: false, visible: false },
    })
    const today = modules.find(module => module.id === 'today')

    expect(today?.enabled).toBe(original?.enabled)
    expect(today?.visible).toBe(original?.visible)
  })
})
