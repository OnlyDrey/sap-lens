import { buildIdentity } from '../scripts/product-version.mjs'
import { brandingPlugin } from '../scripts/branding.mjs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const identity = buildIdentity()

export default defineConfig({
  server: {
    host: '127.0.0.1', port: 18743, strictPort: true,
    proxy: Object.fromEntries(['/api', '/health'].map(prefix => [prefix, { target: 'http://127.0.0.1:18744', headers: { 'X-SAP-Lens-Token': 'synthetic-browser-capability-0000000000000000' } }])),
  },
  plugins: [react(),brandingPlugin(),{name:'sap-lens-product-identity',generateBundle(){this.emitFile({type:'asset',fileName:'product-version.json',source:JSON.stringify(identity)})}}],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
})
