import { describe, expect, it } from 'vitest'
import clientSource from '../api/client.ts?raw'
import viteConfigSource from '../../vite.config.ts?raw'

describe('web API entrypoint', () => {
  it('uses same-origin API paths in browser code', () => {
    expect(clientSource).toContain("const BASE = '/api/v1'")
    expect(clientSource).not.toContain('http://localhost:8000')
    expect(clientSource).not.toContain('http://backend:8000')
  })

  it('defaults the Vite dev proxy to control-plane, not backend', () => {
    expect(viteConfigSource).toContain('CONTROL_PLANE_API_URL')
    expect(viteConfigSource).toContain("'http://localhost:8010'")
    expect(viteConfigSource).not.toContain("'http://localhost:8000'")
    expect(viteConfigSource).not.toContain('http://backend:8000')
  })
})
