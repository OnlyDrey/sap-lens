// Run after changing the locked Lucide version; no network access is needed.
import { readFileSync, writeFileSync } from 'node:fs'
const source = readFileSync(new URL('../frontend/node_modules/lucide-react/dynamicIconImports.js', import.meta.url), 'utf8')
const names = [...source.matchAll(/"([a-z0-9-]+)": \(\) => import/g)].map(([, slug]) => slug.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join(''))
if (names.length < 100) throw Error('Lucide catalog could not be read; no files updated.')
const legacy = ['DollarSign', 'BarChart2', 'Package', 'Wrench', 'Users', 'TrendingUp', 'Cog', 'FolderKanban', 'CheckCircle', 'Server', 'Warehouse', 'Layers', 'Shield', 'Database', 'Truck', 'Building2', 'Globe', 'Code', 'FileText', 'Leaf', 'Hash']
const target = new URL('../backend/src/AuthLens.Api/V1Reference/registry.json', import.meta.url)
const registry = JSON.parse(readFileSync(target, 'utf8'))
const icons = [...new Set([...legacy, ...names])].sort()
if (process.argv.includes('--check')) {
  if (JSON.stringify(registry.icons) !== JSON.stringify(icons)) throw Error('Icon catalog is stale. Run node scripts/sync-lucide-catalog.mjs.')
} else {
  registry.icons = icons
  writeFileSync(target, JSON.stringify(registry, null, 1) + '\n')
}
console.log(`Verified ${names.length} Lucide icons; existing identifiers retained.`)
