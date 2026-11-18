import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { readProduct, synchronize, buildIdentity } from '../product-version.mjs'
function fixture(run) {
 const root = mkdtempSync(path.join(tmpdir(), 'saplens-version-'))
 try { mkdirSync(path.join(root, 'backend')); mkdirSync(path.join(root, 'frontend'))
 writeFileSync(path.join(root, 'backend/product-version.json'), JSON.stringify({version:'2.0.0-alpha.1'}))
 for(const name of ['package.json','package-lock.json']) writeFileSync(path.join(root,'frontend',name), JSON.stringify({version:'0.1.0',packages:{'':{version:'0.1.0'}}}))
 run(root) } finally { rmSync(root,{recursive:true,force:true}) }
}
test('mirrors synchronize without changing the canonical resource', () => fixture(root => {
 const original=readFileSync(path.join(root,'backend/product-version.json'),'utf8')
 assert.throws(()=>synchronize(root),/differs/); assert.equal(synchronize(root,true),'2.0.0-alpha.1'); assert.equal(synchronize(root),'2.0.0-alpha.1')
 assert.equal(readFileSync(path.join(root,'backend/product-version.json'),'utf8'),original)
}))
test('identity rejects invalid and mismatched commits', () => fixture(root => {
 assert.throws(()=>buildIdentity(root,{SAP_LENS_SOURCE_SHA:'bad'}),/Invalid build/)
 assert.throws(()=>buildIdentity(root,{SAP_LENS_SOURCE_SHA:'a'.repeat(40),GITHUB_ACTIONS:'true',GITHUB_SHA:'b'.repeat(40)}),/another source/)
 assert.equal(buildIdentity(root,{SAP_LENS_SOURCE_SHA:'a'.repeat(40)}).source_sha,'a'.repeat(40))
}))
test('version grammar and Windows numeric bounds fail closed', () => fixture(root => {
 for(const version of ['2.0.0-alpha.0','2.0.0-beta-1','65536.0.0','02.0.0']) {
 writeFileSync(path.join(root,'backend/product-version.json'),JSON.stringify({version}));assert.throws(()=>readProduct(root),/Invalid product/)
 }
}))
