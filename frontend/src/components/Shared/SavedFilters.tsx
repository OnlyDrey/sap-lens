import { Button } from './Button'
import { Popover } from './Popover'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, FolderOpen, Trash2, Pencil, X } from 'lucide-react'
import { apiRequest } from '@/api/client'
import { Combobox } from './Combobox'
import { formatDate } from '@/lib/dateFormat'
import { inputClass } from '@/components/Access/Shared'

type State = Record<string, string | boolean | number | string[]>
export interface Entry {
  id: string
  name: string
  view: string
  filter_schema: number
  filters: State
  modified: string
}
export interface FilterStorage {
  key: string
  list: () => Promise<{ items: Entry[] }>
  save: (body: Record<string, unknown>) => Promise<Entry>
  remove: (body: { id: string; expected: string }) => Promise<unknown>
}
/** Explicit operations only: unsupported definitions remain stored until deliberately updated. */
export function SavedFilters({
  view,
  state,
  apply,
  clear,
  storage,
  showClear = true,
}: {
  view: string
  state: State
  apply: (s: State) => void
  clear: () => void
  storage?: FilterStorage
  showClear?: boolean
}) {
  const qc = useQueryClient(),
    [active, setActive] = useState(''),
    [menuOpen, setMenuOpen] = useState(false),
    [applied, setApplied] = useState(''),
    [appliedState, setAppliedState] = useState(''),
    [name, setName] = useState(''),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false)
  const result = useQuery({
    queryKey: ['saved-filters', storage?.key || 'local'],
    queryFn: () =>
      storage
        ? storage.list()
        : apiRequest<{ items: Entry[] }>('/api/saved-filters'),
  })
  const items = result.data?.items.filter((i) => i.view === view) || [],
    selected = items.find((i) => i.id === active),
    appliedEntry = items.find((i) => i.id === applied)
  const modified = appliedEntry && appliedState !== JSON.stringify(state)
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setMessage('')
    try {
      await action()
      await qc.invalidateQueries({
        queryKey: ['saved-filters', storage?.key || 'local'],
      })
      setMessage('Saved filters updated.')
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const save = (update: boolean, rename = false) =>
    void run(async () => {
      const body = {
        name,
        view,
        filters: rename ? {} : state,
        id: update ? active : '',
        expected: update ? selected?.modified : '',
        rename,
      }
      const entry = await (storage
        ? storage.save(body)
        : apiRequest<Entry>('/api/saved-filters', 'POST', body))
      setActive(entry.id)
      if (!rename) {
        setApplied(entry.id)
        setAppliedState(JSON.stringify(state))
      }
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
          : view === 'comparison'
            ? ['identifier', 'difference', 'a', 'b']
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
    setAppliedState(JSON.stringify({ ...state, ...safe }))
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
      <Popover
        onOpenChange={setMenuOpen}
        label={`${view} saved filters`}
        trigger={
          <>
            <FolderOpen size={16} aria-hidden="true" />
            Saved filters
            {appliedEntry && (
              <span>
                {' '}
                · {appliedEntry.name}
                {modified ? ' (Modified)' : ''}
              </span>
            )}
          </>
        }
      >
        <div className="saved-filter-panel">
          <Combobox openOnFocus={false} label="Saved filter" value={active} options={items.map(item=>item.id)} disabled={busy} allowCustom={false} placeholder={items.length?'Choose saved filter':'No saved filters'} clearLabel="Choose saved filter" optionLabel={value=>items.find(item=>item.id===value)?.name||value} onChange={value=>{setActive(value);setName(items.find(item=>item.id===value)?.name||'')}}/>
          <Button disabled={!selected || busy} onClick={load}>
            Load
          </Button>
          <input
            className={inputClass}
            aria-label="Saved filter name"
            placeholder="Filter name"
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <div className="saved-filter-actions">
          <Button
            disabled={!name.trim() || busy || !!result.error}
            onClick={() => save(false)}
          >
            <Save size={15} aria-hidden="true" />
            Save as new
          </Button>
          {(
            <Button
              variant="ghost"
              onClick={() => {
                clear()
                setActive('')
                setApplied('')
                setName('')
                setMessage('')
              }}
            >
              <X size={15} aria-hidden="true" />
              Clear filters
            </Button>
          )}
          </div>
          {selected && (
            <>
              <Button
                disabled={busy || !name.trim()}
                onClick={() => save(true)}
              >
                Update saved filter
              </Button>
              <Button
                disabled={busy || !name.trim()}
                onClick={() => save(true, true)}
              >
                <Pencil size={15} aria-hidden="true" />
                Rename
              </Button>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(`Delete saved filter “${selected.name}”?`))
                    void run(async () => {
                      await (storage
                        ? storage.remove({
                            id: active,
                            expected: selected.modified,
                          })
                        : apiRequest('/api/saved-filters/delete', 'POST', {
                            id: active,
                            expected: selected.modified,
                          }))
                      setActive('')
                      setApplied('')
                      setName('')
                    })
                }}
              >
                <Trash2 size={15} aria-hidden="true" />
                Delete
              </Button>
            </>
          )}
          {(message || result.error) && (
            <p role="status">{message || result.error?.message}</p>
          )}
          {selected?.filter_schema !== undefined &&
            selected.filter_schema !== 1 && (
              <p className="text-sm text-[var(--warning)]">
                Incompatible saved filter schema; original retained.
              </p>
            )}
        </div>
      </Popover>
      {showClear && !menuOpen && (
        <Button
          variant="ghost"
          onClick={() => {
            clear()
            setActive('')
            setApplied('')
            setName('')
            setMessage('')
          }}
        >
          <X size={15} aria-hidden="true" />
          Clear filters
        </Button>
      )}
      {appliedEntry && (
        <span className="sr-only" role="status">
          {appliedEntry.name}
          {modified ? ' · Modified' : ''}
        </span>
      )}
      {!menuOpen && (message || result.error) && (
        <p role="status" className="text-sm basis-full">
          {message || result.error?.message}
        </p>
      )}
    </div>
  )
}
