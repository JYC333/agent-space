import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Dedicated test config — avoids the Tailwind/PWA plugins used by the app build.
export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: ['../..'],
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
    testTimeout: 15000,
  },
})
