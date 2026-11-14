import test from 'node:test'
import assert from 'node:assert/strict'
import { actionLabel, confirmationText } from '../../src/lib/functionalGroupText.ts'

test('confirmation text reports a missing date and a missing reviewer separately and invents nothing', () => {
  assert.match(confirmationText('2026-03-04T10:00:00Z', 'Reviewer One', true)!, /^Last confirmed 04\.03\.2026 \d{2}:\d{2} by Reviewer One$/)
  assert.match(confirmationText('2026-03-04T10:00:00.123456+00:00', 'Reviewer One', true)!, /^Last confirmed 04\.03\.2026 \d{2}:\d{2} by Reviewer One$/)   // as the server stores it
  assert.equal(confirmationText('2026-03-04', 'Reviewer One', true), 'Last confirmed 04.03.2026 by Reviewer One')
  assert.equal(confirmationText('not a date', 'Reviewer One', true), 'Last confirmed by Reviewer One; date not recorded')
  for (const value of ['2026-03-04T10:00:00Z', 'not a date', null]) assert.doesNotMatch(confirmationText(value, 'Reviewer One', true)!, /Unknown|Not available/)
  assert.match(confirmationText('2026-03-04T10:00:00Z', '', true)!, /; reviewer not recorded$/)
  assert.match(confirmationText(null, 'Reviewer One', true)!, /^Last confirmed by Reviewer One; date not recorded$/)
  assert.equal(confirmationText(null, '  ', true), 'Confirmed; date and reviewer not recorded')
  assert.equal(confirmationText(null, '', false), null)
  assert.doesNotMatch(confirmationText('2026-03-04T10:00:00Z', undefined, true)!, /undefined|null/)
})

test('the action label names what happens next', () => {
  assert.equal(actionLabel(false, 'Unassigned'), 'Assign group')
  assert.equal(actionLabel(true, 'Confirmed'), 'Change group')
  assert.equal(actionLabel(true, 'Needs review'), 'Assign / Confirm')
  assert.equal(actionLabel(true, 'Unassigned'), 'Assign / Confirm')
})
