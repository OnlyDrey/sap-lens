import test from 'node:test'
import assert from 'node:assert/strict'
import { jaccard, containment } from '../../src/lib/comparisonMetrics.ts'

// Moved from refinement-27.spec.ts. Same values.
test('comparison metric distinguishes symmetric similarity from directional containment', () => {
  assert.equal(jaccard(2, 2, 2), 100); assert.equal(jaccard(1, 1, 2), 50); assert.equal(jaccard(1, 2, 2), 33); assert.equal(jaccard(0, 2, 3), 0); assert.equal(jaccard(0, 0, 0), 0)
  assert.equal(containment(1, 1), 100); assert.equal(containment(1, 2), 50)
})
