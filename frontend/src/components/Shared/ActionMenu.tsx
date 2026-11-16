import { MoreHorizontal } from 'lucide-react'
import type { KeyboardEvent, ReactNode } from 'react'
import { Button } from './Button'
import { Popover } from './Popover'

export interface ActionMenuItem { id: string; label: string; icon?: ReactNode; description?: string; tone?: 'default' | 'destructive'; disabled?: boolean }

/** Compact row actions behind one "more" button. Built on the shared Popover (outside click, Escape and focus return); closes after a choice,
 *  arrow keys move between items. The trigger is named for its row ("Actions for alice"), so several menus on a page stay distinguishable. */
export function ActionMenu({ label, items, onSelect, disabled = false }: { label: string; items: ActionMenuItem[]; onSelect: (id: string) => void; disabled?: boolean }) {
  if (disabled) return <Button variant="ghost" size="icon" aria-label={label} disabled><MoreHorizontal size={16} aria-hidden="true" /></Button>
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const options = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
    const at = options.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (at + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
    options[next]?.focus()
  }
  return (
    <Popover label={label} triggerLabel={label} triggerSize="icon" triggerVariant="ghost" preferredWidth={260} className="action-menu" trigger={<MoreHorizontal size={16} aria-hidden="true" />}>
      {(close) => (
        <div role="group" aria-label={label} className="action-menu-list" onKeyDown={move}>
          {items.map((item) => (
            <button key={item.id} type="button" className="action-menu-item" data-tone={item.tone ?? 'default'} disabled={item.disabled} onClick={() => { close(); onSelect(item.id) }}>
              {item.icon}
              <span><strong>{item.label}</strong>{item.description && <span>{item.description}</span>}</span>
            </button>
          ))}
        </div>
      )}
    </Popover>
  )
}
