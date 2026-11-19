import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readdirSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const script = fileURLToPath(new URL('../browser-server.mjs', import.meta.url))
test('missing SDK fails promptly, removes only its owned data and keeps unrelated files', () => {
 const directory=mkdtempSync(path.join(tmpdir(),'saplens-host-contract-'))
 try {
  writeFileSync(path.join(directory,'keep.txt'),'unchanged')
  const result=spawnSync(process.execPath,[script],{encoding:'utf8',timeout:5000,env:{...process.env,DOTNET:path.join(directory,'missing-dotnet'),TMPDIR:directory,TEMP:directory,TMP:directory,AUTHLENS_BROWSER_TEST_PORT:'18857'}})
  assert.equal(result.status,1,result.stderr)
  assert.match(result.stderr,/Disposable .NET host failed/)
  assert.deepEqual(readdirSync(directory),['keep.txt'])
  assert.equal(readFileSync(path.join(directory,'keep.txt'),'utf8'),'unchanged')
 } finally {rmSync(directory,{recursive:true,force:true})}
})
test('invalid ports fail before starting a child or creating a data directory', () => {
 for (const port of ['0','-1','65536','not-a-port','1.5']) {
  const result=spawnSync(process.execPath,[script],{encoding:'utf8',timeout:5000,env:{...process.env,AUTHLENS_BROWSER_TEST_PORT:port}})
  assert.equal(result.status,1);assert.match(result.stderr,/Invalid test port/)
 }
})
