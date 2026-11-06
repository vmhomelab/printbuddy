import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Backend port for dev server proxy (default: 8000)
const backendPort = process.env.BACKEND_PORT || '8000'
const backendUrl = `http://localhost:${backendPort}`


export default defineConfig({
  // Default base ('/') emits absolute asset URLs (/assets/...). Required so
  // deep SPA routes (camera popup at /camera/<id>, /projects/<id>, refresh
  // on any nested route) resolve their <script>
  // and <link> tags to /assets/... instead of /<route-prefix>/assets/...,
  // which the SPA fallback would otherwise return as text/html and the
  // browser would refuse to execute (#1221). The earlier `base: ''` partial
  // fix for subpath reverse proxies (#1195, wontfix) is reverted — that
  // audience uses NPM + Cloudflare Tunnel at a real domain per the
  // documented workaround, which doesn't depend on this setting.
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 3000,
  },
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api/v1/ws': {
        target: backendUrl,
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
