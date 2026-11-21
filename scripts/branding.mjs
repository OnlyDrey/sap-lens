import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export const brandingDirectory = new URL('../assets/branding/', import.meta.url)
export const branding = JSON.parse(readFileSync(new URL('manifest.json', brandingDirectory), 'utf8'))
const webAssets = ['logo', 'favicon']

// Read source bytes on every build/request: no checked-in copies or generated images.
export function brandingPlugin() {
  return {
    name: 'authlens-branding',
    buildStart() {
      for (const key of webAssets) this.addWatchFile(fileURLToPath(new URL(branding[key], brandingDirectory)))
    },
    generateBundle() {
      for (const key of webAssets) this.emitFile({ type: 'asset', fileName: branding[key], source: readFileSync(new URL(branding[key], brandingDirectory)) })
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const name = webAssets.map(key => branding[key]).find(name => request.url?.split('?')[0] === `/${name}`)
        if (!name) return next()
        response.setHeader('Content-Type', 'image/png')
        response.end(readFileSync(new URL(name, brandingDirectory)))
      })
    },
  }
}
