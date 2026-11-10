import test from 'node:test'
import assert from 'node:assert/strict'
import { RevisionTracker, compareRevision, parseRevision } from '../../src/lib/dataRevision.ts'

test('tokens parse strictly and anything else is ignored', () => {
  assert.deepEqual(parseRevision('a1b2c3.4.5'), { boot: 'a1b2c3', publication: 4, directory: 5 })
  for (const bad of [null, undefined, '', 'x.1.2', 'a.1', 'a.1.2.3', 'a.-1.2']) assert.equal(parseRevision(bad as string), null)
})

test('ordering is publication first, then directory, within one boot; another boot is always newer', () => {
  const a = parseRevision('aaaaaa.3.1')!
  assert.ok(compareRevision(parseRevision('aaaaaa.4.0')!, a) > 0)
  assert.ok(compareRevision(parseRevision('aaaaaa.3.2')!, a) > 0)
  assert.ok(compareRevision(parseRevision('aaaaaa.2.9')!, a) < 0)
  assert.equal(compareRevision(parseRevision('aaaaaa.3.1')!, a), 0)
  assert.ok(compareRevision(parseRevision('bbbbbb.1.0')!, a) > 0)
})

test('the first response only establishes the baseline; later ones are classified', () => {
  const tracker = new RevisionTracker()
  assert.equal(tracker.observe('aaaaaa.1.0'), 'first')
  assert.equal(tracker.observe('aaaaaa.1.0'), 'same')
  assert.equal(tracker.observe('aaaaaa.2.0'), 'newer')
  assert.equal(tracker.observe('aaaaaa.1.0'), 'stale')           // a slow response from before the publication never replaces newer data
  assert.equal(tracker.observe('aaaaaa.2.0'), 'same')
  assert.deepEqual(tracker.current, { boot: 'aaaaaa', publication: 2, directory: 0 })
})

test('a backend restart is newer, and a directory-only publication is noticed', () => {
  const tracker = new RevisionTracker()
  tracker.observe('aaaaaa.9.3')
  assert.equal(tracker.observe('aaaaaa.9.4'), 'newer')
  assert.equal(tracker.observe('cccccc.1.0'), 'newer')
  assert.equal(tracker.observe('aaaaaa.9.9'), 'newer')            // a response from a process that no longer exists cannot be told apart; it only causes a refresh
})

test('responses without a usable header change nothing', () => {
  const tracker = new RevisionTracker()
  assert.equal(tracker.observe(null), 'same')
  assert.equal(tracker.current, null)
  tracker.observe('aaaaaa.1.0')
  assert.equal(tracker.observe('garbage'), 'same')
  assert.equal(tracker.observe(undefined), 'same')
})

test('overlapping responses arriving out of order: the older one is stale whichever request was sent first', () => {
  const tracker = new RevisionTracker()
  assert.equal(tracker.observe('aaaaaa.1.0'), 'first')
  assert.equal(tracker.observe('aaaaaa.3.0'), 'newer')     // the later request answered first
  assert.equal(tracker.observe('aaaaaa.2.0'), 'stale')     // the earlier one answers late: discarded and repeated
  assert.equal(tracker.observe('aaaaaa.3.0'), 'same')      // the repeat is answered from current data
})

test('a stale answer never lowers the revision the application already knows', () => {
  const tracker = new RevisionTracker()
  tracker.observe('aaaaaa.5.2')
  for (const old of ['aaaaaa.4.9', 'aaaaaa.5.1', 'aaaaaa.1.0']) assert.equal(tracker.observe(old), 'stale')
  assert.equal(tracker.observe('aaaaaa.5.2'), 'same')
  assert.equal(tracker.observe('aaaaaa.5.3'), 'newer')
})
