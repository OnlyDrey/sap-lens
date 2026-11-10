import test from 'node:test'
import assert from 'node:assert/strict'
import { classifyFailure, isTransient, MAX_TRANSIENT_RETRIES, mayRestoreAutomatically, recordRestoreAttempt, RECOVERY_WINDOW_MS, retryDelay, shouldRetry, type Store } from '../../src/lib/startupRecovery.ts'

const memory = (): Store & { data: Record<string, string> } => { const data: Record<string, string> = {}; return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v } } }

test('only a missing answer or a gateway answer is transient', () => {
  for (const error of [{ kind: 'network', status: 0 }, { kind: 'server', status: 502 }, { kind: 'server', status: 503 }, { kind: 'server', status: 504 }]) assert.equal(isTransient(error), true)
  for (const error of [{ kind: 'server', status: 500 }, { kind: 'session', status: 403 }, { kind: 'authentication', status: 401 }, { kind: 'permission', status: 403 }, { kind: 'client', status: 404 }, { kind: 'format', status: 200 }]) assert.equal(isTransient(error), false)
})

test('failures are classified so a session message is never shown for a readiness or configuration problem', () => {
  assert.equal(classifyFailure({ kind: 'network', status: 0 }), 'unavailable')
  assert.equal(classifyFailure({ kind: 'server', status: 503 }), 'unavailable')
  assert.equal(classifyFailure({ kind: 'server', status: 503, detail: 'Synthetic configuration unavailable' }), 'failed')
  assert.equal(classifyFailure({ kind: 'session', status: 403 }), 'session')
  assert.equal(classifyFailure({ kind: 'authentication', status: 401 }), 'rejected')
  assert.equal(classifyFailure({ kind: 'permission', status: 403 }), 'rejected')
  assert.equal(classifyFailure({ kind: 'server', status: 500 }), 'failed')
  assert.equal(classifyFailure({ kind: 'format', status: 200 }), 'failed')
})

test('transient retries are bounded and back off', () => {
  const error = { kind: 'network', status: 0 }
  let total = 0
  for (let attempt = 0; shouldRetry(attempt, error); attempt++) total += retryDelay(attempt)
  assert.equal(shouldRetry(MAX_TRANSIENT_RETRIES, error), false)
  assert.ok(total >= 10_000 && total <= 20_000, `total wait ${total} ms`)
  assert.deepEqual([0, 1, 2, 3, 4, 5, 9].map(retryDelay), [500, 1000, 2000, 3000, 4000, 5000, 5000])
  assert.equal(shouldRetry(0, { kind: 'session', status: 403 }), false)   // a permanent failure is never retried
  assert.equal(shouldRetry(0, { kind: 'authentication', status: 401 }), false)
})

test('an automatic restore is allowed once per window and never in a loop', () => {
  const store = memory()
  assert.equal(mayRestoreAutomatically(store, 1_000_000), true)
  recordRestoreAttempt(store, 1_000_000)
  assert.equal(mayRestoreAutomatically(store, 1_000_000 + 1000), false)                    // the reloaded page is stale again: stop and tell the person
  assert.equal(mayRestoreAutomatically(store, 1_000_000 + RECOVERY_WINDOW_MS), false)
  assert.equal(mayRestoreAutomatically(store, 1_000_000 + RECOVERY_WINDOW_MS + 1), true)   // a later, genuine restart may restore again
})

test('unusable storage or a damaged record cannot cause a loop', () => {
  assert.equal(mayRestoreAutomatically(null, 5), false)
  const broken: Store = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') } }
  assert.equal(mayRestoreAutomatically(broken, 5), false)
  assert.doesNotThrow(() => recordRestoreAttempt(broken, 5))
  const garbage = memory(); garbage.data['sap-lens-session-recovery'] = '{not json'
  assert.equal(mayRestoreAutomatically(garbage, 5), true)    // readable storage with an unreadable record: one attempt, which then writes a valid record
  recordRestoreAttempt(garbage, 5)
  assert.equal(mayRestoreAutomatically(garbage, 6), false)
})
