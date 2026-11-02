// Generated package manifests mirror the single product resource; release identity may override artifacts.
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const source = JSON.parse(fs.readFileSync(root+'backend/resources/product-version.json','utf8')).version
let product=source
const identity=root+'backend/build/build-version.json'
if(process.env.GITHUB_ACTIONS==='true'&&fs.existsSync(identity)){
 const build=JSON.parse(fs.readFileSync(identity,'utf8'))
 if(build.base_version!==source.split('-')[0])throw Error('Build version differs from product base')
 product=build.version
}
if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(product)) throw Error('Invalid product version')
for (const name of ['frontend/package.json','frontend/package-lock.json']) {
  const path=root+name, data=JSON.parse(fs.readFileSync(path,'utf8'))
  if (process.argv.includes('--write')) {
    data.version=product
    if (data.packages?.['']) data.packages[''].version=product
    fs.writeFileSync(path,JSON.stringify(data,null,2)+'\n')
  } else if (data.version!==product || (data.packages?.[''] && data.packages[''].version!==product)) {
    throw Error(`${name} differs from the product version; run node scripts/product-version.mjs --write`)
  }
}
console.log(product)
