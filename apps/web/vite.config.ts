import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// Browser code calls same-origin /api/v1/*; in dev the Vite proxy forwards
// those requests to the server service inside the compose network. API_URL is
// only a local-shell override; compose does not inject a backend URL.
const apiProxyTarget = process.env.API_URL || 'http://server:8010'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/*.png', 'icons/*.svg'],
      manifest: {
        name: 'Agent Core',
        short_name: 'AgentCore',
        description: 'Agent-first memory system',
        theme_color: '#0f1117',
        background_color: '#0f1117',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html}'],
        runtimeCaching: [
          // POST/PATCH/DELETE mutations must never be served from cache.
          // Some operations (quota PTY refresh, workspace console runs) take
          // 20-30 s; the timeout below would cause a null response and a
          // TypeError in the client — so use NetworkOnly for all writes.
          {
            urlPattern: ({ request }) => request.method !== 'GET',
            handler: 'NetworkOnly',
          },
          // GET reads: try network first, fall back to cache after 10 s.
          {
            urlPattern: /^.*\/api\/v1\/.*/i,
            handler: 'NetworkFirst',
            options: { cacheName: 'api-cache', networkTimeoutSeconds: 10 },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    host: true,  // bind 0.0.0.0 so Docker port mapping works
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
    watch: {
      // polling needed in WSL2/Docker — inotify events don't propagate reliably
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      interval: 300,
    },
  },
})
