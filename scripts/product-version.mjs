// backend/product-version.json is the sole active product version. Builds never increment it.
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
export const root = fileURLToPath(new URL('../', import.meta.url))
export function readProduct(directory = root) {
  const value = JSON.parse(fs.readFileSync(path.join(directory, 'backend/product-version.json'), 'utf8'))
  const match = /^(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})(?:-(alpha|beta|rc)\.([1-9]\d{0,4}))?$/.exec(value.version)
  if (!match || [match[1], match[2], match[3], match[5] || 0].some(n => Number(n) > 65535)) throw Error('Invalid product version')
  return value.version
}
export function buildIdentity(directory = root, env = process.env) {
  const version = readProduct(directory)
  let sha = env.AUTHLENS_SOURCE_SHA || ''
  if (fs.existsSync(path.join(directory, '.git'))) sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: directory, encoding: 'utf8' }).trim()
  if (sha && !/^[a-f0-9]{40}$/.test(sha)) throw Error('Invalid build source commit')
  if (env.GITHUB_ACTIONS === 'true' && sha !== env.GITHUB_SHA) throw Error('Build identity belongs to another source commit')
  return { product: 'AuthLens', version, base_version: version.split('-')[0], mode: 'dotnet', source_sha: sha || null }
}
export function synchronize(directory = root, write = false) {
  const product = readProduct(directory)
  for (const name of ['frontend/package.json', 'frontend/package-lock.json']) {
    const filename = path.join(directory, name), data = JSON.parse(fs.readFileSync(filename, 'utf8'))
    if (write) {
      data.version = product
      if (data.packages?.['']) data.packages[''].version = product
      fs.writeFileSync(filename, JSON.stringify(data, null, 2) + '\n')
    } else if (data.version !== product || (data.packages?.[''] && data.packages[''].version !== product)) {
      throw Error(`${name} differs from backend/product-version.json; run node scripts/product-version.mjs --write`)
    }
  }
  return product
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log(synchronize(root, process.argv.includes('--write')))
