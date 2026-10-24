import {
  useId,
  useLayoutEffect,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { Button } from './Button'
/** Nonmodal, anchored portal. Escape restores focus; outside click keeps its destination. */
export function Popover({
  label,
  trigger,
  children,
  onOpenChange,
}: {
  label: string
  trigger: ReactNode
  onOpenChange?: (open: boolean) => void
  children: ReactNode | ((close: () => void) => ReactNode)
}) {
  const [open, setOpen] = useState(false),
    [position, setPosition] = useState({
      top: 0,
      left: 8,
      width: 360,
      maxHeight: 400,
    }),
    id = useId(),
    anchor = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null)
  const close = (restore = true) => {
    setOpen(false)
    onOpenChange?.(false)
    if (restore) anchor.current?.focus()
  }
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const box = anchor.current?.getBoundingClientRect()
      if (!box) return
      const width = Math.min(380, innerWidth - 16),
        below = innerHeight - box.bottom - 12,
        above = box.top - 12,
        height = Math.min(
          panel.current?.scrollHeight || 400,
          Math.max(below, above),
          innerHeight - 24,
        )
      setPosition({
        left: Math.max(8, Math.min(box.left, innerWidth - width - 8)),
        top:
          below >= height || below >= above
            ? box.bottom + 6
            : Math.max(8, box.top - height - 6),
        width,
        maxHeight: height,
      })
    }
    place()
    const frame = requestAnimationFrame(() =>
      panel.current
        ?.querySelector<HTMLElement>('input,select,button,[tabindex="0"]')
        ?.focus(),
    )
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])
  useEffect(() => {
    if (!open) return
    const outside = (e: PointerEvent) => {
        if (
          !panel.current?.contains(e.target as Node) &&
          !anchor.current?.contains(e.target as Node)
        )
          close(false)
      },
      pop = () => close(false)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('popstate', pop)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('popstate', pop)
    }
  }, [open])
  return (
    <>
      <Button
        ref={anchor}
        variant="outline"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? id : undefined}
        onClick={() => (open ? close() : (setOpen(true), onOpenChange?.(true)))}
      >
        {trigger}
      </Button>
      {open &&
        createPortal(
          <div
            id={id}
            ref={panel}
            role="dialog"
            aria-modal="false"
            aria-label={label}
            className="ui-popover"
            style={{ position: 'fixed', ...position }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                close()
              }
            }}
            onBlur={(e) => {
              if (
                e.relatedTarget &&
                !e.currentTarget.contains(e.relatedTarget as Node) &&
                !anchor.current?.contains(e.relatedTarget as Node)
              )
                close(false)
            }}
          >
            {typeof children === 'function'
              ? children(() => close())
              : children}
          </div>,
          document.body,
        )}
    </>
  )
}
