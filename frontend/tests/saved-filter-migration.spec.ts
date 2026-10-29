import { test, expect } from '@playwright/test'
import { migrateTransactionFilters } from '../src/lib/savedFilterMigration'

// Pure mapping from the earlier single list plus exclude switch to the independent include and exclude groups.
test('earlier AND-exclude restores as Exclude ALL and OR-exclude as Exclude ANY', () => {
  expect(migrateTransactionFilters({ tcodes: ['MIGO', 'ME21N'], transactionMode: 'and', transactionExclude: true, search: 'x' }))
    .toEqual({ search: 'x', tcodes: [], transactionMode: 'and', excludeTcodes: ['MIGO', 'ME21N'], excludeMode: 'all' })
  expect(migrateTransactionFilters({ tcodes: ['MIGO', 'ME21N'], transactionMode: 'or', transactionExclude: true }))
    .toEqual({ tcodes: [], transactionMode: 'and', excludeTcodes: ['MIGO', 'ME21N'], excludeMode: 'any' })
})

test('the earliest not-list and operator forms become Exclude ANY', () => {
  expect(migrateTransactionFilters({ notTcodes: ['SE16'], transactionOperator: 'not' }))
    .toEqual({ tcodes: [], transactionMode: 'and', excludeTcodes: ['SE16'], excludeMode: 'any' })
  expect(migrateTransactionFilters({ tcodes: ['SE16'], transactionOperator: 'not' }))
    .toMatchObject({ tcodes: [], excludeTcodes: ['SE16'], excludeMode: 'any' })
})

test('plain include filters keep their codes and gain an empty exclude group; migrated filters are unchanged', () => {
  expect(migrateTransactionFilters({ tcodes: ['MIGO'], transactionMode: 'or' })).toEqual({ tcodes: ['MIGO'], transactionMode: 'or', excludeTcodes: [], excludeMode: 'any' })
  const current = { tcodes: ['MIGO'], transactionMode: 'and', excludeTcodes: ['VA03'], excludeMode: 'all' }
  expect(migrateTransactionFilters(current)).toBe(current)
  expect(migrateTransactionFilters({ search: 'only text' })).toEqual({ search: 'only text' })
  expect(migrateTransactionFilters({ tcodes: ['A', 7, null], transactionExclude: true })).toMatchObject({ excludeTcodes: ['A'] })
})
