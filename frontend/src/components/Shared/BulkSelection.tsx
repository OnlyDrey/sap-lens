import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

/** Selection by stable identifier (never row position). Items are kept as an explicit snapshot, so changing filters or pages
 * never adds or removes members; only the caller's add/remove/clear operations do. */
export function useBulkSelection<T>(keyOf: (item: T) => string) {
  const [items, setItems] = useState<Map<string, T>>(new Map())
  const toggle = useCallback((item: T) => setItems((previous) => {
    const next = new Map(previous), key = keyOf(item)
    if (next.has(key)) next.delete(key); else next.set(key, item)
    return next
  }), [keyOf])
  const add = useCallback((list: readonly T[]) => setItems((previous) => { const next = new Map(previous); for (const item of list) next.set(keyOf(item), item); return next }), [keyOf])
  const remove = useCallback((keys: readonly string[]) => setItems((previous) => { const next = new Map(previous); for (const key of keys) next.delete(key); return next }), [])
  const clear = useCallback(() => setItems(new Map()), [])
  return { items, size: items.size, has: (key: string) => items.has(key), toggle, add, remove, clear }
}

/** Row checkbox with an explicit accessible name (for example "Select assignment ROLE for USER"). */
export function RowCheckbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return <input type="checkbox" className="bulk-checkbox" aria-label={label} checked={checked} onChange={onChange} />
}

/** Header checkbox for the rows currently visible; indeterminate when only some of them are selected. */
export function PageCheckbox({ label, selected, total, onChange }: { label: string; selected: number; total: number; onChange: (select: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = selected > 0 && selected < total }, [selected, total])
  return <input ref={ref} type="checkbox" className="bulk-checkbox" aria-label={label} disabled={!total} checked={total > 0 && selected === total} onChange={(event) => onChange(event.target.checked)} />
}

/** Contextual toolbar shown while something is selected: count and scope first, then selection and review actions. */
export function BulkToolbar({ label, summary, scope, children }: { label: string; summary: ReactNode; scope?: ReactNode; children: ReactNode }) {
  return (
    <div role="toolbar" aria-label={label} className="bulk-toolbar">
      <div className="bulk-toolbar-info"><p role="status" className="bulk-summary">{summary}</p>{scope && <p className="bulk-scope">{scope}</p>}</div>
      <div className="bulk-toolbar-actions">{children}</div>
    </div>
  )
}
