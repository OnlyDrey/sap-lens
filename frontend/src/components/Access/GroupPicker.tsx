import { useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, X } from 'lucide-react'
import { createGroup, fetchGroups, groupsKey, type FunctionalGroup } from '@/api/functionalGroups'
import { FormField } from '@/components/Shared/Controls'
import { textMatches } from '@/lib/searchMatching'

const key = (name: string) => name.trim().replace(/\s+/g, ' ').toLocaleLowerCase()

/** Multi-select of existing Functional Groups with inline creation. The list stays open while several groups are chosen, a created group is selected at
 *  once, and everything already chosen (or selected elsewhere in the dialog, such as the users) is preserved. Archived groups cannot be chosen. */
export function GroupPicker({ selected, onChange, disabledIds = [], disabledHint = 'already a member', label = 'Functional Groups' }: {
  selected: string[]; onChange: (ids: string[]) => void; disabledIds?: string[]; disabledHint?: string; label?: string
}) {
  const client = useQueryClient()
  const groups = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const [query, setQuery] = useState(''), [open, setOpen] = useState(false), [index, setIndex] = useState(0)
  const id = useId(), input = useRef<HTMLInputElement>(null)
  const active = (groups.data?.items ?? []).filter(group => group.status === 'active')
  const byId = new Map((groups.data?.items ?? []).map(group => [group.id, group]))
  const matching = active.filter(group => !selected.includes(group.id) && (!query.trim() || textMatches(group.name, query)))
  const exact = active.some(group => key(group.name) === key(query))
  const canCreate = query.trim().length > 0 && !exact
  const rows: ({ kind: 'group'; group: FunctionalGroup } | { kind: 'create' })[] = [...matching.map(group => ({ kind: 'group' as const, group })), ...(canCreate ? [{ kind: 'create' as const }] : [])]
  const create = useMutation({
    mutationFn: (name: string) => createGroup(name, ''),
    onSuccess: async group => { await client.invalidateQueries({ queryKey: groupsKey }); onChange([...selected, group.id]); setQuery(''); setIndex(0); input.current?.focus() },
  })
  const choose = (position: number) => {
    const row = rows[position]
    if (!row) return
    if (row.kind === 'group' && disabledIds.includes(row.group.id)) return  // already a member: nothing to add
    if (row.kind === 'create') { create.mutate(query.trim()); return }
    onChange([...selected, row.group.id]); setQuery(''); setIndex(0); input.current?.focus()  // stays open: more groups can follow
  }
  return (
    <FormField label={label}>
      <div className="group-picker">
        {selected.length > 0 && (
          <ul className="group-picker-chips" aria-label="Selected Functional Groups">
            {selected.map(gid => (
              <li key={gid} className="group-picker-chip">
                <span>{byId.get(gid)?.name ?? gid}</span>
                <button type="button" aria-label={`Remove ${byId.get(gid)?.name ?? gid} from the selection`} onClick={() => onChange(selected.filter(value => value !== gid))}><X size={12} aria-hidden="true" /></button>
              </li>
            ))}
          </ul>
        )}
        <div className="combobox-anchor">
          <Search size={15} aria-hidden="true" className="combobox-search" />
          <input ref={input} role="combobox" aria-label="Search or create a Functional Group" aria-expanded={open} aria-controls={open ? `${id}-list` : undefined} aria-autocomplete="list"
            aria-activedescendant={open && rows[index] ? `${id}-row-${index}` : undefined} autoComplete="off" maxLength={80} placeholder="Search or create a group" value={query}
            onChange={event => { setQuery(event.target.value); setOpen(true); setIndex(0) }} onFocus={() => setOpen(true)} onClick={() => setOpen(true)}
            onKeyDown={event => {
              if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); setIndex(value => Math.min(rows.length - 1, value + 1)) }
              else if (event.key === 'ArrowUp') { event.preventDefault(); setIndex(value => Math.max(0, value - 1)) }
              else if (event.key === 'Enter' && open && rows[index]) { event.preventDefault(); choose(index) }
              else if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false) }  // closes the list first, the dialog on the next Escape
              else if (event.key === 'Backspace' && !query && selected.length) onChange(selected.slice(0, -1))
            }} />
        </div>
        {open && (
          <ul id={`${id}-list`} role="listbox" aria-label="Functional Group choices" aria-multiselectable="true" className="group-picker-list">
            {rows.map((row, position) => row.kind === 'group' ? (
              <li key={row.group.id} id={`${id}-row-${position}`} role="option" aria-selected={false} aria-disabled={disabledIds.includes(row.group.id) || undefined} data-active={position === index || undefined}
                onPointerDown={event => event.preventDefault()} onClick={() => choose(position)}>
                <span>{row.group.name}</span>{disabledIds.includes(row.group.id) && <small className="text-muted">{disabledHint}</small>}
              </li>
            ) : (
              <li key="create" id={`${id}-row-${position}`} role="option" aria-selected={false} data-active={position === index || undefined} onPointerDown={event => event.preventDefault()} onClick={() => choose(position)}>
                <Plus size={14} aria-hidden="true" /><span>Create group “{query.trim()}”</span>
              </li>
            ))}
            {rows.length === 0 && <li role="presentation" className="text-muted">{selected.length ? 'No more groups match.' : 'No groups match.'}</li>}
          </ul>
        )}
        {create.isError && <p role="alert">{create.error instanceof Error ? create.error.message : 'The group could not be created.'}</p>}
      </div>
    </FormField>
  )
}
