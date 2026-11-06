import test from 'node:test'
import assert from 'node:assert/strict'
import { formatTime, formatTimestamp, normalizeTimeOfDay } from '../../src/lib/dateFormat.ts'

// The formatting must not depend on the machine's locale or clock convention: fix the zone, assert 24-hour output.
process.env.TZ = 'Europe/Oslo'

test('midnight, noon and afternoon are 24-hour times without AM/PM', () => {
  assert.equal(formatTime('2026-11-06T23:00:00Z'), '00:00')            // 00:00 in Oslo (CET, UTC+1)
  assert.equal(formatTime('2026-11-06T11:00:00Z'), '12:00')            // noon
  assert.equal(formatTime('2026-11-06T13:30:00Z'), '14:30')            // 02:30 PM must read 14:30
  assert.equal(formatTime('2026-11-06T05:00:00Z'), '06:00')            // 06:00 AM must read 06:00
  for (const value of ['2026-11-06T23:00:00Z', '2026-11-06T11:00:00Z', '2026-11-06T13:30:00Z']) assert.doesNotMatch(formatTime(value), /AM|PM|am|pm/)
})

test('timestamps are dd.MM.yyyy HH:mm in the local zone, including summer time and the date change', () => {
  assert.equal(formatTimestamp('2026-11-06T23:30:00Z'), '07.11.2026 00:30')   // UTC date 06.11 is 07.11 in Oslo
  assert.equal(formatTimestamp('2026-07-01T12:00:00Z'), '01.07.2026 14:00')   // CEST (UTC+2)
  assert.equal(formatTimestamp('2026-11-06T13:30:00Z'), '06.11.2026 14:30')
  assert.equal(formatTimestamp('2026-11-06T00:00:00+00:00'), '06.11.2026 01:00')
  assert.equal(formatTimestamp(null, 'Never'), 'Never')
  assert.equal(formatTime('not a time', 'n/a'), 'n/a')
})

test('seconds stay 24-hour when requested', () => {
  assert.equal(formatTime('2026-11-06T13:05:09Z', 'x', true), '14:05:09')
})

test('a typed or stored time of day is validated and canonicalised as HH:mm', () => {
  assert.equal(normalizeTimeOfDay('00:00'), '00:00')
  assert.equal(normalizeTimeOfDay('12:00'), '12:00')
  assert.equal(normalizeTimeOfDay('14:30'), '14:30')
  assert.equal(normalizeTimeOfDay('6:05'), '06:05')
  assert.equal(normalizeTimeOfDay(' 23:59 '), '23:59')
  for (const bad of ['24:00', '12:60', '2:30 PM', '06:00 AM', '', 'abc', '1230']) assert.equal(normalizeTimeOfDay(bad), null, bad)
})
