import { useEffect, useId, useRef, type ReactNode } from 'react'
import { openListOwnsEscape } from '@/lib/openListOwnsEscape'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { IconButton } from './Button'

/** Docked detail panel. Non-modal so the list or matrix behind it keeps its scroll position and filters. */
export function SidePanel({ title, subtitle, children, onClose, footer, headerActions, className = '' }: { title: string; subtitle?: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; headerActions?: ReactNode; className?: string }) {
  const id = useId(),
    panel = useRef<HTMLElement>(null),
    close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('.ui-dialog') && !openListOwnsEscape(event)) {
        event.preventDefault()
        close.current()
      }
    }
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('keydown', key)
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return createPortal(
    <aside role="dialog" aria-modal="false" aria-labelledby={id} tabIndex={-1} ref={panel} className={`ui-side-panel ${className}`}>
      <header>
        <div className="min-w-0">
          <h2 id={id}>{title}</h2>
          {subtitle && <div className="ui-description">{subtitle}</div>}
        </div>
        <div className="ui-side-panel-actions">
          {headerActions}
          <IconButton label="Close panel" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>
      </header>
      <div className="ui-side-panel-body">{children}</div>
      {footer && <footer>{footer}</footer>}
    </aside>,
    document.body,
  )
}
