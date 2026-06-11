import { describe, it, expect, vi, beforeEach } from 'vitest'
import { meApi, homeApi, setSpaceContext } from '../api/client'

/**
 * Home is user-scoped: its /me aggregate must NOT be filtered by the active Space, even when
 * one is selected. The space-scoped Space Today endpoint is the contrast.
 */
describe('Home aggregate is not filtered by the active space', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }) as unknown as typeof fetch
  })

  it('meApi.summary omits space_id/user_id even when a space is active', async () => {
    setSpaceContext('space-team', 'user-1')
    await meApi.summary()
    const url = (globalThis.fetch as unknown as { mock: { calls: string[][] } }).mock.calls[0][0]
    expect(url).toContain('/me/summary')
    expect(url).not.toContain('space_id')
    expect(url).not.toContain('user_id')
  })

  it('homeApi.summary (Space Today) IS space-scoped', async () => {
    setSpaceContext('space-team', 'user-1')
    await homeApi.summary()
    const url = (globalThis.fetch as unknown as { mock: { calls: string[][] } }).mock.calls[0][0]
    expect(url).toContain('/home/summary')
    expect(url).toContain('space_id=space-team')
  })
})
