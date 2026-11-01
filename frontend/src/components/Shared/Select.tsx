import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type SelectHTMLAttributes } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'
import { observeAnchorLayout } from '@/lib/observeAnchorLayout'
import { usePopoverOwners } from './Popover'

type Choice = { value: string; label: string; disabled: boolean; group: string | null }

/** The options of the native element, read when the list opens, so `<option>` and `<optgroup>` children stay the single source of truth. */
const readChoices = (select: HTMLSelectElement): Choice[] =>
  Array.from(select.options).map(option => ({
    value: option.value, label: option.label || option.textContent || option.value, disabled: option.disabled || !!option.closest('optgroup:disabled'),
    group: option.parentElement instanceof HTMLOptGroupElement ? option.parentElement.label : null,
  }))

/** Set the value the way the browser does and let React see an ordinary `change` event, so callers keep `event.target.value`. */
const commit = (select: HTMLSelectElement, value: string) => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, value)
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

/**
 * Standard, non-searchable select. It keeps a real `<select>` (name, value, validation, labels, disabled state, forms) and replaces only its
 * browser-drawn popup with the list used by the searchable Combobox and the multi-select filter: same surface, spacing, highlight, accent
 * and check mark for the selected option. The list is a portal, so scrolling containers, dialogs and sidebars never clip it.
 *
 * Keyboard (closed): Enter, Space, Arrow Up/Down or Alt+Arrow Down open it. Keyboard (open): Arrow Up/Down, Home, End, Page Up/Down move,
 * Enter or Space choose, typing jumps to a matching label, Escape and Tab close it (Escape does not reach a surrounding dialog).
 * Multiple or sized selects keep the browser control. Use `Combobox` when the user needs to search or enter a value.
 */
export function Select({ className = 'ui-control', onMouseDown, onKeyDown, onBlur, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  const owners = usePopoverOwners()
  const uid = useId(), listId = `${uid}-list`
  const select = useRef<HTMLSelectElement>(null), popup = useRef<HTMLDivElement>(null), typed = useRef({ text: '', at: 0 })
  const [open, setOpen] = useState(false), [choices, setChoices] = useState<Choice[]>([]), [index, setIndex] = useState(0), [positioned, setPositioned] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 280 })
  const enhanced = !props.multiple && !(props.size && props.size > 1)
  const optionId = (position: number) => `${uid}-option-${position}`
  const enabled = (from: number, step: 1 | -1) => { for (let at = from; at >= 0 && at < choices.length; at += step) if (!choices[at].disabled) return at; return -1 }

  const show = () => {
    const element = select.current
    if (!element || element.disabled) return
    const list = readChoices(element)
    setChoices(list)
    const selected = list.findIndex(choice => choice.value === element.value && !choice.disabled)
    setIndex(selected >= 0 ? selected : Math.max(0, list.findIndex(choice => !choice.disabled)))
    setOpen(true)
  }
  const close = () => setOpen(false)
  const choose = (position: number) => {
    const choice = choices[position]
    if (!choice || choice.disabled || !select.current) return
    close(); select.current.focus()
    if (choice.value !== select.current.value) commit(select.current, choice.value)
  }

  useLayoutEffect(() => {
    if (!open) { setPositioned(false); return }
    const anchor = select.current?.parentElement
    const place = () => {
      const box = anchor?.getBoundingClientRect(); if (!box) return
      const below = innerHeight - box.bottom - 12, above = box.top - 12
      const natural = Math.min(280, (popup.current?.scrollHeight || 278) + 2), down = below >= natural || below >= above
      const height = Math.min(natural, Math.max(0, down ? below : above), Math.max(0, innerHeight - 16))
      const width = Math.min(box.width, innerWidth - 16)
      setPositioned(true)
      setPosition({ left: Math.max(8, Math.min(box.left, innerWidth - width - 8)), width, top: Math.max(8, Math.min(down ? box.bottom + 4 : box.top - height - 4, innerHeight - height - 8)), maxHeight: height })
    }
    place()
    return anchor ? observeAnchorLayout(anchor, popup.current, place) : undefined
  }, [open, choices.length])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!select.current?.parentElement?.contains(event.target as Node) && !popup.current?.contains(event.target as Node)) close() }
    const dismiss = () => close()
    document.addEventListener('pointerdown', outside)
    window.addEventListener('popstate', dismiss)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('popstate', dismiss) }
  }, [open])
  useEffect(() => { if (open) document.getElementById(optionId(index))?.scrollIntoView({ block: 'nearest' }) }, [open, index])
  useEffect(() => { if (props.disabled) close() }, [props.disabled])

  const keys = (event: KeyboardEvent<HTMLSelectElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented || !enhanced) return
    const { key } = event
    if (!open) {
      if (key === 'Enter' || key === ' ' || key === 'ArrowDown' || key === 'ArrowUp') { event.preventDefault(); show() }
      return
    }
    if (key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return }
    if (key === 'Tab') { close(); return }
    if (key === 'Enter' || key === ' ') { event.preventDefault(); choose(index); return }
    const move = (to: number) => { if (to >= 0) setIndex(to) }
    if (key === 'ArrowDown') { event.preventDefault(); move(enabled(index + 1, 1)) }
    else if (key === 'ArrowUp') { event.preventDefault(); move(enabled(index - 1, -1)) }
    else if (key === 'Home') { event.preventDefault(); move(enabled(0, 1)) }
    else if (key === 'End') { event.preventDefault(); move(enabled(choices.length - 1, -1)) }
    else if (key === 'PageDown') { event.preventDefault(); move(enabled(Math.min(choices.length - 1, index + 8), -1)) }
    else if (key === 'PageUp') { event.preventDefault(); move(enabled(Math.max(0, index - 8), 1)) }
    else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const now = Date.now(), text = (now - typed.current.at < 700 ? typed.current.text : '') + key.toLowerCase()
      typed.current = { text, at: now }
      const from = text.length === 1 ? index + 1 : index  // repeating one letter cycles through its matches
      const found = [...choices.keys()].map(offset => (from + offset) % choices.length).find(at => !choices[at].disabled && choices[at].label.toLowerCase().startsWith(text))
      if (found !== undefined) { event.preventDefault(); setIndex(found) }
    }
  }

  let lastGroup: string | null = null
  return (
    <span className="settings-select shared-select" data-open={open || undefined}>
      <select {...props} ref={select} className={className}
        aria-haspopup={enhanced ? 'listbox' : undefined} aria-expanded={enhanced ? open : undefined} aria-controls={enhanced && open ? listId : undefined}
        aria-activedescendant={enhanced && open && choices[index] ? optionId(index) : undefined}
        onMouseDown={event => { onMouseDown?.(event); if (enhanced && !event.defaultPrevented && event.button === 0 && !event.currentTarget.disabled) { event.preventDefault(); event.currentTarget.focus(); open ? close() : show() } }}
        onKeyDown={keys}
        onBlur={event => { onBlur?.(event); if (!popup.current?.contains(event.relatedTarget as Node)) close() }}>
        {children}
      </select>
      <ChevronDown size={16} aria-hidden="true" />
      {open && createPortal(
        <div ref={popup} data-popover-owner={owners} className="combobox-popup select-popup" style={{ position: 'fixed', ...position, visibility: positioned ? 'visible' : 'hidden' }} onMouseDown={event => event.preventDefault()}>
          <div id={listId} role="listbox" aria-label={props['aria-label'] ?? undefined}>
            {choices.map((choice, position) => {
              const heading = choice.group !== null && choice.group !== lastGroup ? choice.group : null
              lastGroup = choice.group
              const selected = choice.value === select.current?.value
              return (
                <div key={`${position}-${choice.value}`} role="presentation">
                  {heading && <p className="select-group" role="presentation">{heading}</p>}
                  <div id={optionId(position)} role="option" data-value={choice.value} aria-selected={selected} aria-disabled={choice.disabled || undefined}
                    className={`combobox-option ${position === index ? 'highlighted' : ''}`} onMouseMove={() => { if (!choice.disabled) setIndex(position) }} onClick={() => choose(position)}>
                    <span>{choice.label}</span>{selected && <Check size={16} aria-hidden="true" />}
                  </div>
                </div>
              )
            })}
            {!choices.length && <p className="select-empty" role="status">No options available.</p>}
          </div>
        </div>, document.body)}
    </span>
  )
}
