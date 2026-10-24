import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronUp, Search } from 'lucide-react'

/** Bounded local or server-backed options; portal avoids scroll-container clipping. */
export function Combobox({ value, options, onChange, label, placeholder = 'All', disabled = false, allowCustom = true, clearLabel = 'All', id, onSearch, hasMore = false, loading = false, maxLength = 512, serverFiltered = false, optionLabel = (value:string)=>value }: {
  value: string; options: string[]; onChange: (value: string) => void; label: string;
  placeholder?: string; disabled?: boolean; allowCustom?: boolean; clearLabel?: string; id?: string; onSearch?: (query: string) => void; hasMore?: boolean; loading?: boolean; maxLength?: number; serverFiltered?: boolean; optionLabel?:(value:string)=>string;
}) {
  const uid = useId(), listId = `${uid}-list`
  const anchor = useRef<HTMLDivElement>(null), popup = useRef<HTMLDivElement>(null), input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false), [query, setQuery] = useState<string | null>(null), [index, setIndex] = useState(0)
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 240 })
  const choices = ['', ...new Set(options.filter(Boolean))].filter(option => !query || serverFiltered || (option ? optionLabel(option) : clearLabel).toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const close = () => { setOpen(false); setQuery(null) }
  const choose = (option: string) => { onChange(option); close(); input.current?.focus() }
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const box = anchor.current?.getBoundingClientRect(); if (!box) return
      const below = window.innerHeight - box.bottom - 12, above = box.top - 12
      const height = Math.min(280, Math.max(80, below >= 180 || below >= above ? below : above))
      setPosition({ left: Math.max(8, Math.min(box.left, window.innerWidth - box.width - 8)), width: Math.min(box.width, window.innerWidth - 16),
        top: below >= 180 || below >= above ? box.bottom + 4 : Math.max(8, box.top - height - 4), maxHeight: height })
    }
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!anchor.current?.contains(event.target as Node) && !popup.current?.contains(event.target as Node)) close() }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => { if (open && query === null) setIndex(Math.max(0, choices.indexOf(value))) }, [open, value, JSON.stringify(options), query])
  useEffect(() => { document.getElementById(`${uid}-option-${index}`)?.scrollIntoView({ block: 'nearest' }) }, [index, uid, open])
  useEffect(() => { if (disabled) close() }, [disabled])
  useEffect(() => {
    const dismiss = () => close()
    window.addEventListener('popstate', dismiss)
    return () => window.removeEventListener('popstate', dismiss)
  }, [])
  return <div className="combobox-anchor" ref={anchor}>
    <Search size={15} aria-hidden="true" className="combobox-search"/>
    <input id={id} ref={input} role="combobox" aria-label={label} aria-expanded={open} aria-controls={open ? listId : undefined}
      aria-autocomplete="list" aria-activedescendant={open && choices[index] !== undefined ? `${uid}-option-${index}` : undefined}
      autoComplete="off" spellCheck={false} disabled={disabled} placeholder={placeholder} value={query ?? value} maxLength={maxLength}
      onClick={() => { if (!disabled) { setOpen(true); if (!open) onSearch?.(''); setIndex(Math.max(0, choices.indexOf(value))) } }}
      onFocus={() => { if (!disabled) { setOpen(true); if (!open) onSearch?.(''); setIndex(Math.max(0, choices.indexOf(value))) } }}
      onChange={event => { setOpen(true); setIndex(0); setQuery(event.target.value); onSearch?.(event.target.value); if (allowCustom) onChange(event.target.value) }}
      onBlur={event => { if (!anchor.current?.contains(event.relatedTarget as Node)) close() }}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); close() }
        if (event.key === 'Tab') close()
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); setIndex(previous => Math.max(0, Math.min(choices.length - 1, previous + (event.key === 'ArrowDown' ? 1 : -1)))) }
        if (event.key === 'Enter' && open) { event.preventDefault(); if (choices[index] !== undefined) choose(choices[index]) }
      }}/>
    <button type="button" disabled={disabled} aria-label={`${open ? 'Close' : 'Open'} ${label} options`} tabIndex={-1}
      onMouseDown={event => event.preventDefault()} onClick={() => { if (open) close(); else { input.current?.focus(); setOpen(true) } }}>
      {open ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}</button>
    {open && createPortal(<div ref={popup} className="combobox-popup" style={{ position: 'fixed', ...position }} onMouseDown={event => event.preventDefault()}>
      <div id={listId} role="listbox" aria-label={`${label} options`}>
        {choices.map((option, i) => <div key={option} id={`${uid}-option-${i}`} role="option" aria-selected={option === value}
          className={`combobox-option ${i === index ? 'highlighted' : ''}`} onMouseMove={() => setIndex(i)} onClick={() => choose(option)}>
          <span>{option ? optionLabel(option) : clearLabel}</span>{option === value && <Check size={16} aria-hidden="true"/>}
        </div>)}
        {loading && <p role="status" className="p-3 text-sm text-[var(--muted)]">Searching available values…</p>}
        {hasMore && <p className="p-3 text-sm text-[var(--muted)]">Showing the first {options.length} values. Type to narrow the options.</p>}
        {!choices.length && !loading && <p className="p-3 text-sm text-[var(--muted)]">No matching options{allowCustom ? '; the typed filter is retained.' : '.'}</p>}
      </div>
    </div>, document.body)}
  </div>
}
