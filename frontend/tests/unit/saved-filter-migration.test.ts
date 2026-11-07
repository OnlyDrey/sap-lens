import test from 'node:test'
import assert from 'node:assert/strict'
import { migrateTransactionFilters } from '../../src/lib/savedFilterMigration.ts'

/** Playwright's toMatchObject: every expected key matches; other keys are ignored. */
function assertPartial(actual: Record<string, unknown>, expected: Record<string, unknown>) {
  for (const [key, value] of Object.entries(expected)) assert.deepEqual(actual[key], value, key)
}

// Moved from saved-filter-migration.spec.ts. Pure mapping from the earlier single list plus exclude switch to the independent include and exclude groups.
test('earlier AND-exclude restores as Exclude ALL and OR-exclude as Exclude ANY', () => {
  assert.deepEqual(migrateTransactionFilters({ tcodes: ['MIGO', 'ME21N'], transactionMode: 'and', transactionExclude: true, search: 'x' }),
    { search: 'x', tcodes: [], transactionMode: 'and', excludeTcodes: ['MIGO', 'ME21N'], excludeMode: 'all' })
  assert.deepEqual(migrateTransactionFilters({ tcodes: ['MIGO', 'ME21N'], transactionMode: 'or', transactionExclude: true }),
    { tcodes: [], transactionMode: 'and', excludeTcodes: ['MIGO', 'ME21N'], excludeMode: 'any' })
})

test('the earliest not-list and operator forms become Exclude ANY', () => {
  assert.deepEqual(migrateTransactionFilters({ notTcodes: ['SE16'], transactionOperator: 'not' }),
    { tcodes: [], transactionMode: 'and', excludeTcodes: ['SE16'], excludeMode: 'any' })
  assertPartial(migrateTransactionFilters({ tcodes: ['SE16'], transactionOperator: 'not' }), { tcodes: [], excludeTcodes: ['SE16'], excludeMode: 'any' })
})

test('plain include filters keep their codes and gain an empty exclude group; migrated filters are unchanged', () => {
  assert.deepEqual(migrateTransactionFilters({ tcodes: ['MIGO'], transactionMode: 'or' }), { tcodes: ['MIGO'], transactionMode: 'or', excludeTcodes: [], excludeMode: 'any' })
  const current = { tcodes: ['MIGO'], transactionMode: 'and', excludeTcodes: ['VA03'], excludeMode: 'all' }
  assert.equal(migrateTransactionFilters(current), current)
  assert.deepEqual(migrateTransactionFilters({ search: 'only text' }), { search: 'only text' })
  assertPartial(migrateTransactionFilters({ tcodes: ['A', 7, null], transactionExclude: true }), { excludeTcodes: ['A'] })
})
