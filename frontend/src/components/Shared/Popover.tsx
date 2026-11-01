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
import { Button, type ButtonProps } from './Button'
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
  triggerVariant='outline',
  triggerClassName='',
  className='',
  reveal='click',
  isolateClicks=false,
}: {
  label: string
  trigger: ReactNode
  preferredWidth?:number
  triggerSize?: 'default' | 'compact' | 'icon'
  /** Visual weight of the trigger button; `ghost` for triggers that carry their own look (for example a pill). */
  triggerVariant?: ButtonProps['variant']
  triggerClassName?: string
  /** Extra class for the panel, for menu-like popovers that must never scroll. */
  className?: string
  /** `hover` also opens on mouse hover and keyboard focus (a transient description); a click or Enter pins it open. */
  reveal?: 'click' | 'hover'
  /** React bubbles portal events to the owner's ancestors: keep clicks inside the panel from reaching them. */
  isolateClicks?: boolean
  onOpenChange?: (open: boolean) => void
  children: ReactNode | ((close: () => void) => ReactNode)
}) {
  const inheritedOwners=usePopoverOwners()
  const [open, setOpen] = useState(false),
    [position, setPosition] = useState<{top:number;left:number;width:number;maxHeight:number}|null>(null),
    id = useId(),
    anchor = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null),
    pinned = useRef(false),
    timer = useRef<number>()
  const owned=(target:EventTarget|null)=>target instanceof Element&&!!target.closest(`[data-popover-owner~="${id}"]`)
  const openNow = () => { if (!open) { setOpen(true); onOpenChange?.(true) } }
  const later = (action: () => void, delay: number) => { window.clearTimeout(timer.current); timer.current = window.setTimeout(action, delay) }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const close = (restore = true) => {
    window.clearTimeout(timer.current)
    pinned.current = false
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
        variant={triggerVariant}
        className={triggerClassName}
        size={triggerSize}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? id : undefined}
        onClick={() => {
          if (reveal === 'hover' && open && !pinned.current) { pinned.current = true; return } // a transient reveal becomes a pinned one
          if (open) return close()
          pinned.current = true
          openNow()
        }}
        onPointerEnter={reveal === 'hover' ? (event) => { if (event.pointerType === 'mouse') later(openNow, 250) } : undefined}
        onPointerLeave={reveal === 'hover' ? () => { window.clearTimeout(timer.current); if (open && !pinned.current) later(() => close(false), 200) } : undefined}
        onFocus={reveal === 'hover' ? (event) => { if (event.currentTarget.matches(':focus-visible')) openNow() } : undefined}
        onBlur={reveal === 'hover' ? (event) => { if (!pinned.current && !panel.current?.contains(event.relatedTarget as Node)) close(false) } : undefined}
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
            className={`ui-popover ${className}`.trim()}
            style={{ position: 'fixed', width:Math.min(preferredWidth,innerWidth-16), visibility:position?'visible':'hidden', ...position }}
            onPointerEnter={reveal === 'hover' ? () => window.clearTimeout(timer.current) : undefined}
            onPointerLeave={reveal === 'hover' ? () => { if (!pinned.current) later(() => close(false), 200) } : undefined}
            onClick={isolateClicks ? (event) => event.stopPropagation() : undefined}
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
