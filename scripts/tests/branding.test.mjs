import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { branding, brandingDirectory, brandingPlugin } from '../branding.mjs'

const root = new URL('../../', import.meta.url)
test('canonical branding files exist with actual PNG/ICO formats and stable generic names', () => {
  assert.deepEqual(branding, { logo: 'logo.png', favicon: 'favicon.png', windowsIcon: 'app.ico', applicationImage: 'app.png' })
  for (const name of Object.values(branding)) {
    const bytes = readFileSync(new URL(name, brandingDirectory))
    assert.deepEqual([...bytes.subarray(0, name.endsWith('.ico') ? 4 : 8)], name.endsWith('.ico') ? [0, 0, 1, 0] : [137, 80, 78, 71, 13, 10, 26, 10])
  }
  for (const old of ['assets/sap-lens.png', 'assets/sap-lens.ico', 'frontend/public/sap-lens.png', 'frontend/public/favicon.png'])
    assert.equal(existsSync(new URL(old, root)), false, old)
})

test('production branding emission preserves source bytes and development serves the same assets', () => {
  const plugin = brandingPlugin()
  const emitted = []
  plugin.generateBundle.call({ emitFile: file => emitted.push(file) })
  assert.deepEqual(emitted.map(file => file.fileName), ['logo.png', 'favicon.png'])
  let handler
  plugin.configureServer({ middlewares: { use: callback => { handler = callback } } })
  for (const file of emitted) {
    assert.deepEqual(file.source, readFileSync(new URL(file.fileName, brandingDirectory)))
    let body, type
    handler({ url: `/${file.fileName}?test=1` }, { setHeader: (_, value) => { type = value }, end: value => { body = value } }, () => assert.fail('asset was not served'))
    assert.equal(type, 'image/png')
    assert.deepEqual(body, file.source)
  }
  let next = false
  handler({ url: '/api/settings' }, {}, () => { next = true })
  assert.equal(next, true)
})

test('Windows executables and both installers reference the canonical multi-size icon', () => {
  for (const file of ['backend/src/AuthLens.Api/AuthLens.Api.csproj', 'backend/src/AuthLens.Desktop/AuthLens.Desktop.csproj', 'backend/installer/AuthLens-Desktop.iss', 'backend/installer/AuthLens-Server.iss']) {
    const text = readFileSync(new URL(file, root), 'utf8')
    assert.ok(text.includes('assets\\branding\\app.ico'), file)
    assert.ok(!text.includes('sap-lens.ico'), file)
  }
})
