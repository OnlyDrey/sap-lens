import { observeAnchorLayout } from '@/lib/observeAnchorLayout'
import { textMatches } from '@/lib/searchMatching'
import { usePopoverOwners } from './Popover'
import { Button } from './Button'
import { FilterChip } from './FilterChip'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronUp, FilterX, ListChecks, Search, X } from 'lucide-react'

/** Searchable multi-select. The list stays open while options are toggled and closes on outside click, Escape, Tab or Close. Values combine with OR; the caller owns the AND between filters.
 * Selections are independent of the search text: narrowing the list never drops a selected value. Select all applies to the options currently shown. */
export function MultiSelectFilter({ label, values, options, onChange, onSearch, loading, hasMore, optionLabel = (value: string) => value, placeholder = 'All · type to search', maxSelected = 100, scope }: {
  label: string; values: string[]; options: string[]; onChange: (values: string[]) => void; onSearch?: (query: string) => void
  loading?: boolean; hasMore?: boolean; optionLabel?: (value: string) => string; placeholder?: string; maxSelected?: number
  /** Describes what the option list is limited to (for example the active filters); shown beside Select all. */
  scope?: string
}) {
  const owners = usePopoverOwners()
  const uid = useId(), listId = `${uid}-list`
  const anchor = useRef<HTMLDivElement>(null), popup = useRef<HTMLDivElement>(null), input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false), [query, setQuery] = useState(''), [index, setIndex] = useState(0), [positioned, setPositioned] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 320 })
  const shown = [...new Set(options.filter(Boolean))].filter(option => !query || onSearch || textMatches(option, query) || textMatches(optionLabel(option), query))
  const unselected = shown.filter(option => !values.includes(option))
  const close = () => { setOpen(false); setQuery(''); onSearch?.('') }
  const toggle = (option: string) => onChange(values.includes(option) ? values.filter(item => item !== option) : values.length < maxSelected ? [...values, option] : values)
  const selectShown = () => onChange([...values, ...unselected].slice(0, maxSelected))
  useLayoutEffect(() => {
    if (!open) { setPositioned(false); return }
    const place = () => {
      const box = anchor.current?.getBoundingClientRect(); if (!box) return
      const below = window.innerHeight - box.bottom - 12, above = box.top - 12
      const natural = Math.min(360, (popup.current?.scrollHeight || 340) + 2), down = below >= natural || below >= above
      const height = Math.min(natural, Math.max(0, down ? below : above), Math.max(0, innerHeight - 16))
      setPositioned(true)
      setPosition({ left: Math.max(8, Math.min(box.left, window.innerWidth - Math.min(Math.max(box.width, 300), innerWidth - 16) - 8)), width: Math.min(Math.max(box.width, 300), window.innerWidth - 16),
        top: Math.max(8, Math.min(down ? box.bottom + 4 : box.top - height - 4, innerHeight - height - 8)), maxHeight: height })
    }
    place(); return anchor.current ? observeAnchorLayout(anchor.current, popup.current, place) : undefined
  }, [open, shown.length])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!anchor.current?.contains(event.target as Node) && !popup.current?.contains(event.target as Node)) close() }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => { setIndex(previous => Math.max(0, Math.min(previous, shown.length - 1))) }, [shown.length])
  useEffect(() => { if (open) document.getElementById(`${uid}-option-${index}`)?.scrollIntoView({ block: 'nearest' }) }, [index, uid, open])
  useEffect(() => {
    const dismiss = () => setOpen(false)
    window.addEventListener('popstate', dismiss)
    return () => window.removeEventListener('popstate', dismiss)
  }, [])
  const openList = () => { if (!open) { setOpen(true); onSearch?.('') } }
  const noun = query ? `matching “${query}”` : 'listed'
  return (
    <div className="grid min-w-0 gap-2">
      <div className="combobox-anchor" ref={anchor}>
        <Search size={15} aria-hidden="true" className="combobox-search" />
        <input ref={input} role="combobox" aria-label={label} aria-expanded={open} aria-controls={open ? listId : undefined} aria-autocomplete="list"
          aria-activedescendant={open && shown[index] !== undefined ? `${uid}-option-${index}` : undefined}
          autoComplete="off" spellCheck={false} maxLength={100} placeholder={values.length ? `${values.length} selected · search to add or remove` : placeholder} value={query}
          onClick={openList} onFocus={openList}
          onChange={event => { openList(); setIndex(0); setQuery(event.target.value); onSearch?.(event.target.value) }}
          onBlur={event => { if (!anchor.current?.contains(event.relatedTarget as Node) && !popup.current?.contains(event.relatedTarget as Node)) close() }}
          onKeyDown={event => {
            if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); close() }
            else if (event.key === 'Tab') close()
            else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); openList(); setIndex(previous => Math.max(0, Math.min(shown.length - 1, previous + (event.key === 'ArrowDown' ? 1 : -1)))) }
            else if (event.key === 'Enter' && open) { event.preventDefault(); if (shown[index] !== undefined) toggle(shown[index]) }
            else if (event.key === 'Backspace' && !query && values.length) onChange(values.slice(0, -1))
          }} />
        <button type="button" aria-label={`${open ? 'Close' : 'Open'} ${label} options`} tabIndex={-1} onMouseDown={event => event.preventDefault()}
          onClick={() => { if (open) close(); else { input.current?.focus(); openList() } }}>{open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>
        {open && createPortal(
          <div ref={popup} data-popover-owner={owners} className="combobox-popup multi-popup" style={{ position: 'fixed', ...position, visibility: positioned ? 'visible' : 'hidden' }} onMouseDown={event => event.preventDefault()}>
            <div className="multi-popup-head">
              <p className="multi-popup-scope" role="status">{shown.length} {shown.length === 1 ? 'value' : 'values'} {noun}{scope ? ` · ${scope}` : ''} · {values.length} selected</p>
              <div className="multi-popup-actions">
                <Button size="compact" title={`Select all ${unselected.length || 0} ${noun} values`} disabled={!unselected.length || values.length >= maxSelected} aria-label={`Select all ${unselected.length} ${noun} ${label} values`} onClick={selectShown}><ListChecks size={14} aria-hidden="true" />Select all</Button>
                <Button size="compact" aria-label="Clear selection" title="Clear the selected values" disabled={!values.length} onClick={() => onChange([])}><FilterX size={14} aria-hidden="true" />Clear</Button>
                <Button size="compact" aria-label={`Close ${label} options`} title="Close the list" onClick={() => { close(); input.current?.focus() }}><X size={14} aria-hidden="true" />Close</Button>
              </div>
            </div>
            <div id={listId} role="listbox" aria-multiselectable="true" aria-label={`${label} options`}>
              {shown.map((option, i) => {
                const selected = values.includes(option)
                return <div key={option} id={`${uid}-option-${i}`} role="option" aria-selected={selected} className={`combobox-option multi-option ${i === index ? 'highlighted' : ''}`}
                  onMouseMove={() => setIndex(i)} onClick={() => toggle(option)}>
                  <span className="multi-check" data-checked={selected || undefined} aria-hidden="true">{selected && <Check size={12} strokeWidth={3} />}</span>
                  <span>{optionLabel(option)}</span>
                </div>
              })}
              {loading && <p role="status" className="p-3 text-sm text-[var(--muted)]">Searching available values…</p>}
              {hasMore && <p className="p-3 text-sm text-[var(--muted)]">Showing the first {options.length} values. Type to narrow the options; Select all applies only to the values shown.</p>}
              {!shown.length && !loading && <p className="p-3 text-sm text-[var(--muted)]">No matching values.</p>}
            </div>
          </div>, document.body)}
      </div>
      {values.length > 0 && <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Selected ${label}`}>
        {values.map(value => <FilterChip key={value} removeLabel={`Remove ${label} ${value}`} onRemove={() => onChange(values.filter(item => item !== value))}>{optionLabel(value)}</FilterChip>)}
        {values.length > 1 && <Button size="compact" variant="ghost" aria-label={`Clear all ${label} selections`} onClick={() => onChange([])}>Clear all</Button>}
      </div>}
    </div>
  )
}
