import test from 'node:test'
import assert from 'node:assert/strict'
import { blocksRequests, initialSession, nextSession, type SessionEvent } from '../../src/lib/sessionState.ts'

const run = (events: SessionEvent[]) => events.reduce((state, event) => nextSession(state, event, 1), initialSession(1))

test('clean startup connects without any warning state', () => {
  assert.equal(initialSession(1).phase, 'connecting')
  assert.equal(run(['success']).phase, 'connected')
})
test('a stale session needs manual action and is never cleared by a later success', () => {
  const state = run(['success', 'stale', 'success', 'success'])
  assert.equal(state.phase, 'manual'); assert.equal(state.category, 'stale_session')
  assert.equal(blocksRequests(state), true)
})
test('temporary connection loss recovers by itself and counts failures', () => {
  const lost = run(['success', 'network', 'network'])
  assert.equal(lost.phase, 'disconnected'); assert.equal(lost.failures, 2); assert.equal(blocksRequests(lost), false)
  assert.equal(nextSession(lost, 'success').phase, 'connected'); assert.equal(nextSession(lost, 'success').failures, 0)
})
test('reconnect is only possible from a broken state and a failed reconnect asks for another manual attempt', () => {
  assert.equal(run(['success', 'reconnect']).phase, 'connected')
  const reconnecting = run(['stale', 'reconnect'])
  assert.equal(reconnecting.phase, 'reconnecting'); assert.equal(blocksRequests(reconnecting), true)
  const failed = nextSession(reconnecting, 'reconnect_failed')
  assert.equal(failed.phase, 'failed'); assert.equal(nextSession(failed, 'success').phase, 'failed')
  assert.equal(nextSession(failed, 'reconnect').phase, 'reconnecting')
})
test('repeated identical events do not create new snapshots (no render loops)', () => {
  const stale = run(['stale'])
  assert.equal(nextSession(stale, 'stale'), stale)
  const connected = run(['success'])
  assert.equal(nextSession(connected, 'success'), connected)
})
