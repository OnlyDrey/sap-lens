import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  server: {
    host: '127.0.0.1', port: 18743, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18744', '/health': 'http://127.0.0.1:18744' },
  },
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
})