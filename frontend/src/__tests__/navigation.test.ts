import { describe, it, expect } from 'vitest'
import {
  routeScopeForPath, sceneForPath, spacePath, stripSpacePrefix,
  RAIL_ITEMS, MOBILE_TAB_ITEMS,
} from '../core/navigation'

describe('navigation model', () => {
  it('treats Home/neutral surfaces as user-scoped and /spaces/:id routes as space-scoped', () => {
    expect(routeScopeForPath('/home')).toBe('home')
    expect(routeScopeForPath('/')).toBe('home')
    expect(routeScopeForPath('/settings')).toBe('home')
    expect(routeScopeForPath('/spaces/team-1/activity')).toBe('space')
    expect(routeScopeForPath('/spaces/team-1/knowledge')).toBe('space')
    expect(routeScopeForPath('/spaces/team-1/today')).toBe('space')
  })

  it('puts Home first in the Global Rail and lists no aggregate/PersonalView entry', () => {
    expect(RAIL_ITEMS[0].id).toBe('home')
    const labels = RAIL_ITEMS.map(i => i.label.toLowerCase())
    expect(labels).not.toContain('personal')
    expect(labels).not.toContain('my view')
    expect(labels).not.toContain('personalview')
    expect(labels).toEqual(expect.arrayContaining([
      'home', 'inbox', 'review', 'wiki', 'tasks', 'agents', 'workspaces', 'settings',
    ]))
  })

  it('marks Home and Settings as user-scoped rail items and the rest as space-scoped', () => {
    const byId = Object.fromEntries(RAIL_ITEMS.map(i => [i.id, i.scope]))
    expect(byId.home).toBe('home')
    expect(byId.settings).toBe('home')
    expect(byId.inbox).toBe('space')
    expect(byId.review).toBe('space')
    expect(byId.wiki).toBe('space')
  })

  it('keeps Home as the first mobile tab', () => {
    expect(MOBILE_TAB_ITEMS[0].id).toBe('home')
  })

  it('selects a scene per route, ignoring the /spaces/:id prefix', () => {
    expect(sceneForPath('/spaces/x/activity')?.id).toBe('inbox')
    expect(sceneForPath('/spaces/x/knowledge')?.id).toBe('wiki')
    expect(sceneForPath('/spaces/x/proposals')?.id).toBe('review')
    expect(sceneForPath('/spaces/x/agents')?.id).toBe('agents')
    expect(sceneForPath('/spaces/x/workspaces')?.id).toBe('workspaces')
    // Home requires no scene sidebar.
    expect(sceneForPath('/home')).toBeNull()
    expect(sceneForPath('/spaces/x/activity')?.id).not.toBe(sceneForPath('/spaces/x/knowledge')?.id)
  })
})

describe('spacePath / stripSpacePrefix', () => {
  it('prefixes in-space logical paths with the Space, preserving query strings', () => {
    expect(spacePath('team-1', '/proposals')).toBe('/spaces/team-1/proposals')
    expect(spacePath('team-1', '/activity?status=raw')).toBe('/spaces/team-1/activity?status=raw')
    expect(spacePath('team-1', '/agents/abc')).toBe('/spaces/team-1/agents/abc')
  })

  it('leaves user-scoped, already-scoped, and missing-space paths untouched', () => {
    expect(spacePath('team-1', '/home')).toBe('/home')
    expect(spacePath('team-1', '/settings')).toBe('/settings')
    expect(spacePath('team-1', '/spaces/other/today')).toBe('/spaces/other/today')
    expect(spacePath(null, '/proposals')).toBe('/proposals')
  })

  it('strips a leading /spaces/:id for matching', () => {
    expect(stripSpacePrefix('/spaces/x/proposals')).toBe('/proposals')
    expect(stripSpacePrefix('/spaces/x')).toBe('/')
    expect(stripSpacePrefix('/home')).toBe('/home')
  })
})
