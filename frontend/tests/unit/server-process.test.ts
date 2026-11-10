import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { mkdtemp, access, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { ChildProcess } from 'node:child_process'
import { observeTestServer, stopTestServer, removeTestServerDirectory } from '../server-process.ts'

function fixture() {
  const child = Object.assign(new EventEmitter(), { pid: 4242, exitCode: null as number | null, signalCode: null })
  return { child, owned: observeTestServer(child as unknown as ChildProcess) }
}
test('Windows teardown targets only the owned tree and waits for close after exit', async () => {
  const { child, owned } = fixture()
  let finished = false
  const stopping = stopTestServer(owned, { platform: 'win32', terminateTree: async pid => {
    assert.equal(pid, 4242)
    child.exitCode = 1; child.emit('exit', 1)
  } }).then(() => { finished = true })
  await new Promise<void>(resolve => setImmediate(resolve))
  assert.equal(finished, false)
  child.emit('close', 1)
  await stopping
  assert.equal(finished, true)
})
test('completed processes are not signalled and tree-kill failures are not suppressed', async () => {
  const { child, owned } = fixture()
  child.exitCode = 0; child.emit('close', 0)
  await stopTestServer(owned, { platform: 'win32', terminateTree: async () => { assert.fail('already closed') } })
  const active = fixture()
  await assert.rejects(stopTestServer(active.owned, { platform: 'win32', terminateTree: async () => { throw Error('tree kill failed') } }), /tree kill failed/)
  active.child.emit('close', 0)
})
test('missing close is bounded and cannot be mistaken for successful shutdown', async () => {
  const { child, owned } = fixture()
  await assert.rejects(stopTestServer(owned, { platform: 'win32', deadline: 10, terminateTree: async () => {} }), /shutdown deadline/)
  child.emit('close', 0)
})
test('directory removal completes and permanent filesystem failures propagate', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'sap-lens-cleanup-unit-'))
  await writeFile(path.join(root, 'synthetic.txt'), 'synthetic')
  await removeTestServerDirectory(root, 'win32')
  await assert.rejects(access(root))
  await assert.rejects(removeTestServerDirectory('invalid\0path', 'win32'))
})
