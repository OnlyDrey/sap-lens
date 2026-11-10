import { execFileSync } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const product=JSON.parse(readFileSync(new URL('../backend/resources/product-version.json',import.meta.url),'utf8')).version
const identityPath=new URL('../backend/build/build-version.json',import.meta.url)
let identity=existsSync(identityPath)?JSON.parse(readFileSync(identityPath,'utf8')):{version:product,mode:'local',source_sha:''}

if(existsSync(new URL('../.git',import.meta.url))&&identity.source_sha&&identity.source_sha!==execFileSync('git',['rev-parse','HEAD'],{cwd:fileURLToPath(new URL('../',import.meta.url)),encoding:'utf8'}).trim()){
 if(process.env.GITHUB_ACTIONS==='true')throw Error('Build metadata belongs to another commit')
 identity={version:product,mode:'local',source_sha:''}
}
if(identity.base_version && identity.base_version!==product.split('-')[0])throw Error('Backend build identity differs from frontend product base')
if(process.env.GITHUB_ACTIONS==='true'&&identity.source_sha&&identity.source_sha!==process.env.GITHUB_SHA)throw Error('Build identity belongs to another source commit')

export default defineConfig({
  server: {
    host: '127.0.0.1', port: 18743, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18744', '/health': 'http://127.0.0.1:18744' },
  },
  plugins: [react(),{name:'sap-lens-product-identity',generateBundle(){this.emitFile({type:'asset',fileName:'product-version.json',source:JSON.stringify(identity)})}}],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
})