// Build-time production dependency notices; no runtime data or application settings.
import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import { dirname, resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..')
const lock=JSON.parse(readFileSync(join(root,'frontend/package-lock.json'),'utf8'))
const sections=['Third-party frontend licenses (production dependency tree)']
for(const [name,row] of Object.entries(lock.packages).sort()){
  if(!name||row.dev)continue
  sections.push(`${name} ${row.version||''} — ${row.license||'See package license'}`)
  const directory=join(root,'frontend',name)
  for(const file of readdirSync(directory,{withFileTypes:true}).filter(f=>f.isFile()&&/^(license|licence|copying)/i.test(f.name)).sort((a,b)=>a.name.localeCompare(b.name)))
    sections.push(readFileSync(join(directory,file.name),'utf8'))
}
writeFileSync(join(root,'frontend/dist/THIRD-PARTY-LICENSES.txt'),sections.join('\n\n')+'\n')
