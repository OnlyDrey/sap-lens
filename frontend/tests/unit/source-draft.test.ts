import test from 'node:test'
import assert from 'node:assert/strict'
import {rebaseSourceDraft} from '../../src/lib/sourceDraft.ts'
import type {Configuration} from '../../src/api/configuration.ts'

// The server returns settings with sorted keys; Settings treats any JSON-text difference between draft and saved as an unsaved change.
const saved = (paths: Record<string, string>, revision: number) => ({
  revision, data_lifecycle: { sources: {} }, data_csv_path: '', employee_csv_path: '', employee_snapshot_id: null,
  active_import: 'default', import_profiles: [{ id: 'default' }],
  source_modes: { employees: 'static', roles: 'dynamic', sod: 'static', users: 'dynamic' }, ...paths,
}) as unknown as Configuration

test('an activation leaves a clean draft clean, whatever key order the server uses', () => {
  const before = saved({}, 1), after = saved({ employee_csv_path: '/synthetic/employees.csv', employee_snapshot_id: 'abc' }, 2)
  const draft = rebaseSourceDraft(structuredClone(before), after, 'employees')
  assert.equal(JSON.stringify(draft), JSON.stringify(after))
})

test('unsaved edits survive an activation, including another source mode', () => {
  const before = saved({}, 1), after = saved({ data_csv_path: '/synthetic/roles.csv' }, 2)
  const draft = structuredClone(before) as unknown as Record<string, unknown>
  ;(draft.source_modes as Record<string, string>).users = 'static'
  draft.theme = 'dark'
  const next = rebaseSourceDraft(draft as unknown as Configuration, after, 'roles') as unknown as Record<string, unknown>
  assert.equal(next.theme, 'dark')
  assert.deepEqual(next.source_modes, { employees: 'static', roles: 'dynamic', sod: 'static', users: 'static' })
  assert.equal(next.data_csv_path, '/synthetic/roles.csv')
  assert.equal(next.revision, 2)
})
