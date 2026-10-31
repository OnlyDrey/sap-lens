import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { ArrowDownAZ, ArrowUpAZ, FilterX, PanelLeftClose, PanelLeftOpen, SlidersHorizontal, X } from 'lucide-react'
import { Button, IconButton } from './Button'
import { Select } from './Select'

const WIDE = '(min-width: 1024px)'
const storageKey = 'sap-lens-filter-sidebar'

function useWide() {
  const query = () => typeof window !== 'undefined' && window.matchMedia(WIDE).matches
  const [wide, setWide] = useState(query)
  useEffect(() => {
    const media = window.matchMedia(WIDE)
    const update = () => setWide(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return wide
}

/** Collapsible left filter sidebar on wide screens, an overlay drawer on narrow ones. Filter state belongs to the caller, so hiding never resets it. */
export function FilterLayout({ activeCount, toolbar, sidebar, children, label = 'Filters', onClear, clearDisabled = false, clearLabel = 'Clear filters' }: { activeCount: number; toolbar?: ReactNode; sidebar: ReactNode; children: ReactNode; label?: string; onClear?: () => void; clearDisabled?: boolean; /** Accessible name of the Clear action where it clears something narrower than every filter of the view. */ clearLabel?: string }) {
  const wide = useWide(),
    id = useId(),
    [open, setOpen] = useState(() => { try { return localStorage.getItem(storageKey) !== 'closed' } catch { return true } }),
    [drawer, setDrawer] = useState(false),
    drawerRef = useRef<HTMLElement>(null),
    trigger = useRef<HTMLButtonElement>(null)
  const persist = (value: boolean) => { setOpen(value); try { localStorage.setItem(storageKey, value ? 'open' : 'closed') } catch { /* optional convenience */ } }
  useEffect(() => {
    if (!drawer || wide) return
    drawerRef.current?.focus()
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.stopPropagation(); setDrawer(false); trigger.current?.focus() } }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [drawer, wide])
  const shown = wide ? open : drawer
  const toggle = () => (wide ? persist(!open) : setDrawer(!drawer))
  const close = () => { if (wide) persist(false); else { setDrawer(false); trigger.current?.focus() } }
  return (
    <div className="filter-layout" data-wide={wide} data-open={shown}>
      <div className="page-toolbar" role="toolbar" aria-label="Page actions">
        <Button ref={trigger} aria-expanded={shown} aria-controls={id} onClick={toggle}>
          {wide ? (open ? <PanelLeftClose size={16} aria-hidden="true" /> : <PanelLeftOpen size={16} aria-hidden="true" />) : <SlidersHorizontal size={16} aria-hidden="true" />}
          {shown && wide ? `Hide ${label.toLowerCase()}` : label}
          {activeCount > 0 && <span className="ui-tab-count" aria-label={`${activeCount} active`}>{activeCount}</span>}
        </Button>
        {toolbar}
      </div>
      <div className="filter-layout-body">
        {!wide && drawer && <div className="filter-backdrop" onClick={close} aria-hidden="true" />}
        <aside id={id} ref={drawerRef} tabIndex={-1} hidden={!shown} aria-label={label} className="filter-sidebar" role={wide ? 'complementary' : 'dialog'} aria-modal={wide ? undefined : 'false'}>
          <header>
            <h2>{label}</h2>
            <div className="filter-sidebar-actions">
              {onClear && <Button size="compact" className="filter-clear-all" aria-label={clearLabel} title={clearLabel === 'Clear filters' ? 'Clear all filters in this view' : clearLabel} disabled={clearDisabled} onClick={onClear}><FilterX size={14} aria-hidden="true" />Clear</Button>}
              <IconButton label={`Close ${label.toLowerCase()}`} onClick={close}><X size={16} /></IconButton>
            </div>
          </header>
          <div className="filter-sidebar-body">{sidebar}</div>
        </aside>
        <div className="filter-layout-main">{children}</div>
      </div>
    </div>
  )
}

export function FilterSection({ title, children }: { title: string; children: ReactNode }) {
  return <fieldset className="filter-section"><legend>{title}</legend>{children}</fieldset>
}

/** Consistent action row: view controls on the left, Saved Filters, sort and export grouped on the right. */
export function PageToolbar({ lead, children }: { lead?: ReactNode; children?: ReactNode }) {
  return <div className="page-toolbar-actions">{lead}<div className="page-toolbar-end">{children}</div></div>
}

export function SortControl({ label = 'Sort', value, options, descending, onChange, onDescending }: {
  label?: string; value: string; options: { value: string; label: string }[]; descending: boolean; onChange: (value: string) => void; onDescending: (value: boolean) => void
}) {
  return (
    <div className="sod-sort" role="group" aria-label={`${label} order`}>
      <Select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</Select>
      <IconButton label={descending ? 'Descending order, switch to ascending' : 'Ascending order, switch to descending'} aria-pressed={descending} onClick={() => onDescending(!descending)}>
        {descending ? <ArrowUpAZ size={16} /> : <ArrowDownAZ size={16} />}
      </IconButton>
    </div>
  )
}
