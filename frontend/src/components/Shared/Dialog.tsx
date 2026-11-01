import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { openListOwnsEscape } from '@/lib/openListOwnsEscape'
import { X } from 'lucide-react'
import { Button, IconButton } from './Button'

/** Modal owner: portalled above overflow boundaries with focus isolation. */
export function Dialog({
  title,
  children,
  onClose,
  footer,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  footer?: ReactNode
}) {
  const id = useId(),
    dialog = useRef<HTMLDivElement>(null),
    close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const root = document.getElementById('root')
    const wasInert = root?.inert
    if (root) root.inert = true
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (openListOwnsEscape(event)) return
        event.preventDefault()
        event.stopPropagation()
        close.current()
        return
      }
      if (event.key !== 'Tab') return
      const controls = [
        ...(dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]',
        ) || []),
      ].filter((el) => el.getClientRects().length > 0)
      if (!controls.length) {
        event.preventDefault()
        dialog.current?.focus()
        return
      }
      const first = controls[0],
        last = controls[controls.length - 1]
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === dialog.current ||
          !dialog.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        last.focus()
      }
      if (
        !event.shiftKey &&
        (document.activeElement === last ||
          document.activeElement === dialog.current ||
          !dialog.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('keydown', key, true)
      if (root) root.inert = wasInert || false
      document.body.style.overflow = oldOverflow
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  useEffect(()=>{dialog.current?.focus()},[title])
  return createPortal(
    <div className="ui-dialog-backdrop">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        ref={dialog}
        className="ui-dialog"
      >
        <header>
          <h2 id={id}>{title}</h2>
          <IconButton label="Close dialog" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </header>
        <div className="ui-dialog-content">{children}</div>
        <footer>
          {footer ?? <Button onClick={onClose}><X size={16} aria-hidden="true"/>Close</Button>}
        </footer>
      </div>
    </div>,
    document.body,
  )
}
