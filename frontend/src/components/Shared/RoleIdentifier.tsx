import { useEffect, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes } from 'react'
import { Check, Copy, ArrowUpRight } from 'lucide-react'

/** SAP identifiers are rendered as one unbroken string: no characters are inserted, copy writes the exact value. */
export const identifierFragments = (value: string) => value

/** Smallest font size a codeblock is scaled down to when its container is narrower than the name; below it the container adapts instead. */
const MIN_FIT_SIZE = 9

/**
 * A role name is always one complete line: never wrapped, scrolled, clipped or ellipsized. When the surrounding layout is narrower than
 * the name, the font is scaled down (not below MIN_FIT_SIZE) so it fits; when even that is not enough the codeblock keeps its full width
 * (`data-fit="overflow"`) and the container, not the codeblock, has to make room.
 */
function fit(root: HTMLElement) {
  root.style.removeProperty('--role-code-size')
  root.removeAttribute('data-fit')
  const excess = root.scrollWidth - root.clientWidth
  if (excess <= 0.5) return
  const code = root.querySelector('code')
  if (!code) return
  const base = parseFloat(getComputedStyle(code).fontSize), width = code.getBoundingClientRect().width
  if (!base || width <= excess) return
  const size = Math.max(MIN_FIT_SIZE, Math.floor(base * ((width - excess) / width) * 10) / 10)
  if (size < base) root.style.setProperty('--role-code-size', `${size}px`)
  root.dataset.fit = root.scrollWidth - root.clientWidth > 0.5 ? 'overflow' : 'scaled'
}

const fitted = new Map<Element, Set<HTMLElement>>()
let observer: ResizeObserver | undefined
function watch(root: HTMLElement) {
  const parent = root.parentElement
  if (!parent || typeof ResizeObserver === 'undefined') return () => undefined
  observer ??= new ResizeObserver((entries) => { for (const entry of entries) fitted.get(entry.target)?.forEach(fit) })
  const group = fitted.get(parent) ?? new Set<HTMLElement>()
  if (!group.size) { fitted.set(parent, group); observer.observe(parent) }
  group.add(root)
  return () => { group.delete(root); if (!group.size) { fitted.delete(parent); observer?.unobserve(parent) } }
}

interface RoleIdentifierProps {
  moduleId?: string | null
  value: string
  label?: string
  onOpen?: () => void
  /** With a href the open control is a real link: modified clicks open a new tab, a plain click calls onOpen. */
  href?: string
  openLabel?: string
  openButtonProps?: ButtonHTMLAttributes<HTMLButtonElement> & { 'data-user'?: string }
}

export function RoleIdentifier({ moduleId: _moduleId, value, label = 'role identifier', onOpen, href, openLabel, openButtonProps }: RoleIdentifierProps) {
  const [message, setMessage] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout>>(), root = useRef<HTMLSpanElement>(null)
  useEffect(() => () => clearTimeout(timer.current), [])
  useLayoutEffect(() => {
    const node = root.current
    if (!node) return
    fit(node)
    return watch(node)
  }, [value])
  return (
    <span
      ref={root}
      className="role-identifier"
      data-np
      data-copied={message === 'Copied'}
      onClick={(e) => e.stopPropagation()}
    >
      {onOpen && href ? <a href={href} className="role-identifier-link" aria-label={openLabel || `Open ${value}`} data-user={openButtonProps?.['data-user']} onClick={(event) => { if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen() }}><code title={value} tabIndex={-1}>{identifierFragments(value)}</code><ArrowUpRight size={14} aria-hidden="true" className="shrink-0"/></a>
        : onOpen ? <button {...openButtonProps} type="button" className="role-identifier-link" aria-label={openLabel || `Open ${value}`} onClick={onOpen}><code title={value} tabIndex={-1}>{identifierFragments(value)}</code><ArrowUpRight size={14} aria-hidden="true" className="shrink-0"/></button> : <code title={value} tabIndex={-1}>{identifierFragments(value)}</code>}
      <button
        type="button"
        aria-label={`Copy ${label} ${value}`}
        onClick={async () => {
          clearTimeout(timer.current)
          try {
            await navigator.clipboard.writeText(value)
            setMessage('Copied')
          } catch {
            setMessage('Copy failed. Select the identifier to copy manually.')
          }
          timer.current = setTimeout(() => setMessage(''), 2000)
        }}
      >
        {message === 'Copied' ? (
          <Check size={14} aria-hidden="true" />
        ) : (
          <Copy size={14} aria-hidden="true" />
        )}
      </button>
      <span className="role-copy-feedback" role="status">
        {message}
      </span>
    </span>
  )
}
