import { useEffect, useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'

export function RoleIdentifier({ value, label = 'role identifier', onOpen, openLabel }: { value: string; label?: string; onOpen?: () => void; openLabel?: string }) {
  const [message, setMessage] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <span
      className="role-identifier"
      data-np
      onClick={(e) => e.stopPropagation()}
    >
      {onOpen ? <button className="role-identifier-link" aria-label={openLabel || `Open ${value}`} onClick={onOpen}><code>{value}</code></button> : <code>{value}</code>}
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
          timer.current = setTimeout(() => setMessage(''), 2200)
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
