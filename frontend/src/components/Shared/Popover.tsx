import { observeAnchorLayout } from '@/lib/observeAnchorLayout'
import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { Button } from './Button'
const PopoverOwners = createContext<string|undefined>(undefined)
export const usePopoverOwners=()=>useContext(PopoverOwners)

/** Nonmodal, anchored portal. Escape restores focus; outside click keeps its destination. */
export function Popover({
  label,
  trigger,
  children,
  onOpenChange,
  preferredWidth=380,
  triggerSize='default',
}: {
  label: string
  trigger: ReactNode
  preferredWidth?:number
  triggerSize?: 'default' | 'compact' | 'icon'
  onOpenChange?: (open: boolean) => void
  children: ReactNode | ((close: () => void) => ReactNode)
}) {
  const inheritedOwners=usePopoverOwners()
  const [open, setOpen] = useState(false),
    [position, setPosition] = useState<{top:number;left:number;width:number;maxHeight:number}|null>(null),
    id = useId(),
    anchor = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null)
  const owned=(target:EventTarget|null)=>target instanceof Element&&!!target.closest(`[data-popover-owner~="${id}"]`)
  const close = (restore = true) => {
    setOpen(false)
    setPosition(null)
    onOpenChange?.(false)
    if (restore) anchor.current?.focus()
  }
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const box = anchor.current?.getBoundingClientRect()
      if (!box) return
      const width = Math.min(preferredWidth, innerWidth - 16),
        below = innerHeight - box.bottom - 12,
        above = box.top - 12,
        height = Math.min(
          (panel.current?.scrollHeight || 400) + 2,
          Math.max(below, above),
          innerHeight - 24,
        )
      setPosition({
        left: Math.max(8, Math.min(box.left, innerWidth - width - 8)),
        top: Math.max(8,Math.min(
          below >= height || below >= above ? box.bottom+6 : box.top-height-6,
          innerHeight-height-8)),
        width,
        maxHeight: height,
      })
    }
    place()
    const stopObserving=anchor.current?observeAnchorLayout(anchor.current,panel.current,place):()=>{}
    const mutations=new MutationObserver(place)
    if(panel.current)mutations.observe(panel.current,{childList:true,subtree:true,characterData:true})
    const frame = requestAnimationFrame(() =>
      Array.from(panel.current?.querySelectorAll<HTMLElement>('input:not(:disabled),select:not(:disabled),button:not(:disabled),[tabindex="0"]')||[]).find(element=>element.getClientRects().length)?.focus({preventScroll:true}),
    )
    panel.current?.addEventListener('toggle',place,true)
    return () => {
      stopObserving()
      mutations.disconnect()
      cancelAnimationFrame(frame)
      panel.current?.removeEventListener('toggle',place,true)
    }
  }, [open,preferredWidth])
  useEffect(() => {
    if (!open) return
    const outside = (e: PointerEvent) => {
        if (
          !panel.current?.contains(e.target as Node) &&
          !anchor.current?.contains(e.target as Node) && !owned(e.target)
        )
          close(false)
      },
      pop = () => close(false),
      escape = (event: KeyboardEvent) => {
        if (event.key === 'Escape' && !event.defaultPrevented) {
          event.preventDefault()
          event.stopPropagation()
          close()
        }
      }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('popstate', pop)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('popstate', pop)
    }
  }, [open])
  return (
    <>
      <Button
        ref={anchor}
        variant="outline"
        size={triggerSize}
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
            data-popover-owner={inheritedOwners}
            ref={panel}
            role="dialog"
            aria-modal="false"
            aria-label={label}
            className="ui-popover"
            style={{ position: 'fixed', width:Math.min(preferredWidth,innerWidth-16), visibility:position?'visible':'hidden', ...position }}
            onBlur={(e) => {
              if (
                e.relatedTarget &&
                !e.currentTarget.contains(e.relatedTarget as Node) &&
                !anchor.current?.contains(e.relatedTarget as Node) && !owned(e.relatedTarget)
              )
                close(false)
            }}
          >
            <PopoverOwners.Provider value={[inheritedOwners,id].filter(Boolean).join(' ')}>{typeof children === 'function'
              ? children(() => close())
              : children}</PopoverOwners.Provider>
          </div>,
          document.body,
        )}
    </>
  )
}
