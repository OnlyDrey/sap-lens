import test from 'node:test'
import assert from 'node:assert/strict'
import { formatDate, formatTimestamp } from '../../src/lib/dateFormat.ts'

// Moved from live-filters-polish.spec.ts (a pure function needs no browser). Same inputs and expected values.
test('Norwegian date utilities preserve SAP dates and local/offset time semantics', () => {
  const previous = process.env.TZ
  process.env.TZ = 'America/Los_Angeles'
  try {
    assert.equal(formatDate('2026-10-23'), '23.10.2026')
    assert.equal(formatDate('0001-01-01'), '01.01.0001')
    assert.equal(formatDate('9999-12-31'), '31.12.9999')
    assert.equal(formatDate('2026-02-30'), 'Unknown')
    assert.equal(formatDate('0000-01-01'), 'Unknown')
    assert.equal(formatDate(null), 'Unknown')
    assert.equal(formatTimestamp('2026-10-23T14:50:34'), '23.10.2026 14:50')
    assert.equal(formatTimestamp('2026-10-23T21:50:34Z'), '23.10.2026 14:50')
    assert.equal(formatTimestamp('2026-10-23T14:50:34', 'Unknown', true), '23.10.2026 14:50:34')
    assert.equal(formatTimestamp('invalid'), 'Not available')
    assert.equal(formatTimestamp('2026-02-30T12:00:00Z'), 'Not available')
  } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous }
})
