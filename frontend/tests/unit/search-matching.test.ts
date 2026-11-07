import test from 'node:test'
import assert from 'node:assert/strict'
import { textMatches, transactionMatches, matchingTransactions } from '../../src/lib/searchMatching.ts'
import { presentRoleDescription } from '../../src/lib/rolePresentation.ts'

// Moved from refinement-search-layout.spec.ts and stabilization.spec.ts. Same cases and expected values.
const cases: [string, string, boolean][] = [['ME23N', 'ME*', true], ['ME23N', '*23N', true], ['ME23N', '*me*', true], ['ME23N', 'ME*23*', true], ['XME23N', 'ME*', false], ['ME23NX', '*23N', false], ['abc', '', true], ['abc', 'b', true], ['[a].+', '[a].*', true], ['abc', 'a?c', false], ['a', 'a*a', false], ['Åse', 'å*', true], ['ab', 'a**b', true], ['', '**', true]]
test('literal SAP wildcard matching agrees with backend semantics', () => {
  for (const [value, query, result] of cases) assert.equal(textMatches(value, query), result, `${value} ~ ${query}`)
})

test('display descriptions and transaction matching preserve literal evidence semantics', () => {
  assert.deepEqual(presentRoleDescription('BC - Batch Input Management', ['BC']), { description: 'Batch Input Management', area: 'BC' })
  assert.equal(presentRoleDescription('UNKNOWN - Retain original', ['BC']).description, 'UNKNOWN - Retain original')
  assert.equal(presentRoleDescription('BC prose - Preserve', ['BC']).description, 'BC prose - Preserve')
  assert.equal(transactionMatches('sost', ['SO*']), true); assert.equal(transactionMatches('SM35', ['SO*']), false); assert.equal(transactionMatches('SOST', ['SO']), false)
  assert.deepEqual(matchingTransactions([{ tcode: 'SOST' }, { tcode: 'SO20' }, { tcode: 'SM35' }], ['SO*']).map(row => row.tcode), ['SOST', 'SO20'])
})
