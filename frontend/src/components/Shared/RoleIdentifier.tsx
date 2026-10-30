import { useEffect, useRef, useState, type ButtonHTMLAttributes } from 'react'
import { Check, Copy, ArrowUpRight } from 'lucide-react'

/** SAP identifiers are rendered as one unbroken string: no soft-wrap opportunities are inserted, so a role name never splits mid-identifier and selection and copy keep the exact value. */
export const identifierFragments = (value: string) => value

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
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <span
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
