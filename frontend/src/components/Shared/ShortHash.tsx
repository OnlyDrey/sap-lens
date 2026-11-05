import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { IconButton } from './Button'

/** Shortened technical identifier (revision, hash) on one line with a copy action; the full value stays in the title, the copy and for assistive technology. */
export const shortenHash = (value: string, head = 8, tail = 6) => (value.length > head + tail + 1 ? `${value.slice(0, head)}…${value.slice(-tail)}` : value)

export function ShortHash({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState<'' | 'Copied' | 'Copy failed'>('')
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <span className="short-hash">
      <code title={value}>{shortenHash(value)}</code>
      <span className="sr-only">{`Full ${label}: ${value}`}</span>
      <IconButton label={`Copy ${label}`} tooltip={`Copy the full ${label}`} variant="ghost" size="compact" onClick={async () => {
        clearTimeout(timer.current)
        try { await navigator.clipboard.writeText(value); setCopied('Copied') } catch { setCopied('Copy failed') }
        timer.current = setTimeout(() => setCopied(''), 2000)
      }}>{copied === 'Copied' ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}</IconButton>
      <span aria-live="polite" className="sr-only">{copied}</span>
    </span>
  )
}
