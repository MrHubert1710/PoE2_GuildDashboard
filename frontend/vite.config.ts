import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { loadCatalog } from './scripts/locale-catalog.mjs'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? '/poe2guild/',
  plugins: [{ name: 'validate-locales', buildStart() { loadCatalog(fileURLToPath(new URL('./src/locales', import.meta.url))) } }, vue()],
  server: {
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:9002' },
  },
})
