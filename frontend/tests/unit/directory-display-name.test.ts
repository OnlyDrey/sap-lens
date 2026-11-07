import test from 'node:test'
import assert from 'node:assert/strict'
import { directoryDisplayName } from '../../src/lib/directoryDisplayName.ts'

// Moved from loading-consolidation.spec.ts. Same cases.
test('directory-only name formatting preserves compounds and ambiguous structures', () => {
  for (const [input, output] of [
    ['van der Berg, Anna Maria', 'Anna Maria van der Berg'],
    ['O’Neill, Mary Anne', 'Mary Anne O’Neill'],
    ['Jean-Luc Martin', 'Jean-Luc Martin'],
    ['SMITH John', 'John SMITH'],
    ['VAN DER BERG Anna Maria', 'Anna Maria VAN DER BERG'],
    ['SMITH JOHN', 'SMITH JOHN'],
    ['McDonald John', 'McDonald John'],
    ['Smith, John, Jr.', 'Smith, John, Jr.'],
    ['Team 2, Demo', 'Team 2, Demo'],
    ['Demo (Group), Analyst', 'Demo (Group), Analyst'],
    ['J, Smith', 'J, Smith'],
    ['', ''],
  ]) assert.equal(directoryDisplayName(input), output, input)
})
