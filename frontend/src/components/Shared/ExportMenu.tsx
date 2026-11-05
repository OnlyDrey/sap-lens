import { ChevronDown, Download, FileSpreadsheet, FileText } from 'lucide-react'
import type { KeyboardEvent, ReactNode } from 'react'
import { ExportCSVButton } from './ExportCSVButton'
import { Popover } from './Popover'

export interface ExportOption { id: string; label: string; description: string; icon?: ReactNode }

/** Export button with several formats. Built on the shared Popover (outside click, Escape and focus return); closes after a choice, arrow keys move between options. */
export function ExportMenu({ label = 'Export CSV', options, onSelect, busy = false, disabled = false, title }: { label?: string; options: ExportOption[]; onSelect: (id: string) => void; busy?: boolean; disabled?: boolean; title?: string }) {
  if (disabled) return <ExportCSVButton label={label} disabled title={title} />
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
    const at = items.indexOf(document.activeElement as HTMLButtonElement)
    items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
  }
  return (
    <Popover label={`${label} formats`} preferredWidth={340} triggerVariant="outline" className="export-menu" trigger={<><Download size={16} aria-hidden="true" />{label}<ChevronDown size={14} aria-hidden="true" /></>}>
      {(close) => (
        <div role="group" aria-label={`${label} formats`} className="export-menu-list" onKeyDown={move}>
          {options.map((option) => (
            <button key={option.id} type="button" className="export-menu-item" disabled={busy} title={title} onClick={() => { close(); onSelect(option.id) }}>
              {option.icon ?? <FileText size={16} aria-hidden="true" />}
              <span><strong>{option.label}</strong><span>{option.description}</span></span>
            </button>
          ))}
        </div>
      )}
    </Popover>
  )
}
export const ROLE_ASSIGNMENTS_ICON = <FileSpreadsheet size={16} aria-hidden="true" />
