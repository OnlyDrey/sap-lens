import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, FolderOpen, Trash2, Pencil, X } from 'lucide-react'
import { apiRequest } from '@/api/client'
import { Select } from './Select'
import { formatDate } from '@/lib/dateFormat'
import { inputClass } from '@/components/Access/Shared'

type State = Record<string, string | boolean | number | string[]>
interface Entry {
  id: string
  name: string
  view: string
  filter_schema: number
  filters: State
  modified: string
}
/** Explicit operations only: unsupported definitions remain stored until deliberately updated. */
export function SavedFilters({
  view,
  state,
  apply,
  clear,
}: {
  view: string
  state: State
  apply: (s: State) => void
  clear: () => void
}) {
  const qc = useQueryClient(),
    [active, setActive] = useState(''),
    [applied, setApplied] = useState(''),
    [name, setName] = useState(''),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false)
  const result = useQuery({
    queryKey: ['saved-filters'],
    queryFn: () => apiRequest<{ items: Entry[] }>('/api/saved-filters'),
  })
  const items = result.data?.items.filter((i) => i.view === view) || [],
    selected = items.find((i) => i.id === active),
    appliedEntry = items.find((i) => i.id === applied)
  const modified =
    appliedEntry &&
    JSON.stringify(appliedEntry.filters) !== JSON.stringify(state)
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setMessage('')
    try {
      await action()
      await qc.invalidateQueries({ queryKey: ['saved-filters'] })
      setMessage('Saved filters updated.')
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const save = (update: boolean, rename = false) =>
    void run(async () => {
      const entry = await apiRequest<Entry>('/api/saved-filters', 'POST', {
        name,
        view,
        filters: rename ? {} : state,
        id: update ? active : '',
        expected: update ? selected?.modified : '',
        rename,
      })
      setActive(entry.id)
      if (!rename) setApplied(entry.id)
    })
  const load = () => {
    if (!selected) return
    if (selected.filter_schema !== 1) {
      setMessage(
        'This saved filter uses an unsupported schema. Its original definition is retained.',
      )
      return
    }
    const safe: State = {},
      warnings: string[] = []
    Object.entries(selected.filters).forEach(([key, value]) => {
      const current = state[key]
      if (
        current === undefined ||
        Array.isArray(current) !== Array.isArray(value) ||
        typeof current !== typeof value
      )
        warnings.push(key)
      else safe[key] = value
    })
    const choices: Record<string, string[]> = {
      transactionMode: ['and', 'or'],
      finding: [
        '',
        'any',
        'matched',
        'stale',
        'ad_disabled_open',
        'ad_disabled_locked',
        'directory_match',
        'expired',
        'technical',
      ],
      validity: ['active', 'expired', 'future', 'unknown', 'all'],
      difference: ['', 'shared', 'a', 'b'],
      kind:
        view === 'comparison' ? ['roles', 'transactions'] : ['', 'PR', 'PO'],
      status: ['active', 'expired', 'future', 'unknown', 'all'],
      license: ['', 'classified', 'exclude'],
      state: [
        '',
        'Needs review',
        'Investigating',
        'Approved for deactivation',
        'No action required',
      ],
      sortBy: [
        'name-asc',
        'name-desc',
        'tcodes-desc',
        'tcodes-asc',
        'singles-desc',
      ],
      sort:
        view === 'users'
          ? [
              'username',
              'group',
              'first_name',
              'last_name',
              'email',
              'account_status',
              'relevant_roles',
            ]
          : view === 'review'
            ? [
                'username',
                'name',
                'sap_validity',
                'lock_status',
                'ad_status',
                'review_state',
              ]
            : [
                'role_name',
                'assigned_users',
                'document_type',
                'release_group',
                'release_strategy',
              ],
    }
    Object.keys(safe).forEach((k) => {
      if (
        (choices[k] && !choices[k].includes(String(safe[k]))) ||
        (k.startsWith('valid_') &&
          typeof safe[k] === 'string' &&
          safe[k] !== '' &&
          !formatDate(String(safe[k]), ''))
      ) {
        delete safe[k]
        warnings.push(k)
      }
    })
    setApplied(selected.id)
    apply(safe)
    setName(selected.name)
    setMessage(
      warnings.length
        ? 'Some unsupported fields or values were not applied. The original definition is preserved until Update.'
        : 'Saved filter applied to the current data.',
    )
  }
  return (
    <div className="saved-filter-toolbar" aria-label={`${view} saved filters`}>
      <span className="inline-flex items-center gap-2 text-sm">
        <FolderOpen size={16} aria-hidden="true" />
        Saved filters
      </span>
      <Select
        className={inputClass}
        aria-label="Saved filter"
        value={active}
        disabled={busy}
        onChange={(e) => {
          setActive(e.target.value)
          setName(items.find((i) => i.id === e.target.value)?.name || '')
        }}
      >
        <option value="">Choose saved filter</option>
        {items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
      </Select>
      <button
        className="settings-secondary-button"
        disabled={!selected || busy}
        onClick={load}
      >
        Load
      </button>
      <input
        className={inputClass}
        aria-label="Saved filter name"
        placeholder="Filter name"
        maxLength={80}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button
        className="settings-secondary-button"
        disabled={!name.trim() || busy || !!result.error}
        onClick={() => save(false)}
      >
        <Save size={15} aria-hidden="true" />
        Save as new
      </button>
      {selected && (
        <>
          <button
            className="settings-secondary-button"
            disabled={busy || !name.trim()}
            onClick={() => save(true)}
          >
            Update saved filter
          </button>
          <button
            className="settings-secondary-button"
            disabled={busy || !name.trim()}
            onClick={() => save(true, true)}
          >
            <Pencil size={15} aria-hidden="true" />
            Rename
          </button>
          <button
            className="settings-secondary-button"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Delete saved filter “${selected.name}”?`))
                void run(async () => {
                  await apiRequest('/api/saved-filters/delete', 'POST', {
                    id: active,
                    expected: selected.modified,
                  })
                  setActive('')
                  setApplied('')
                  setName('')
                })
            }}
          >
            <Trash2 size={15} aria-hidden="true" />
            Delete
          </button>
        </>
      )}
      <button
        className="settings-secondary-button clear-filter-button"
        onClick={() => {
          clear()
          setActive('')
          setApplied('')
          setName('')
          setMessage('')
        }}
      >
        <X size={15} aria-hidden="true" />
        Clear applied filter
      </button>
      {appliedEntry && (
        <span className="text-sm" role="status">
          {appliedEntry.name}
          {modified ? ' · Modified' : ''}
        </span>
      )}
      {(message || result.error) && (
        <p role="status" className="text-sm basis-full">
          {message || result.error?.message}
        </p>
      )}
    </div>
  )
}
