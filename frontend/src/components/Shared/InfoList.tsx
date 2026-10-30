import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'

/** Where each summary belongs: Kpi for a prominent figure to scan or drill into, InfoList for secondary metrics and operational facts, charts for distributions backed by data, tables for comparable records, badges for compact status, codeblocks for exact identifiers. */
export function InfoList({ label, children, className = '' }: { label?: string; children: ReactNode; className?: string }) {
  return <ul className={`info-list ${className}`.trim()} aria-label={label}>{children}</ul>
}

/** One secondary metric: label, value and optional icon or note. With `onClick` the whole row is a button (aria-pressed when `active` is given). */
export function InfoRow({ label, value, icon, note, tone = 'neutral', onClick, active, navigates, ariaLabel, title, data, progress }: {
  /** Proportion under the row, only where numerator and denominator are real data. */
  progress?: { value: number; max: number; label: string }
  label: string; value: ReactNode; icon?: ReactNode; note?: ReactNode; tone?: 'neutral' | 'warning' | 'error' | 'success'
  onClick?: () => void; active?: boolean; navigates?: boolean; ariaLabel?: string; title?: string; data?: Record<string, string | undefined>
}) {
  const dataAttrs = Object.fromEntries(Object.entries(data ?? {}).map(([key, item]) => [`data-${key}`, item]))
  const body = (
    <>
      {icon && <span className="info-row-icon" aria-hidden="true">{icon}</span>}
      <span className="info-row-label">{label}{note && <small>{note}</small>}</span>
      <strong className="info-row-value">{value}</strong>
      {onClick && navigates && <ArrowUpRight size={14} aria-hidden="true" className="info-row-arrow" />}
      {progress && <progress className="info-row-progress" aria-label={progress.label} max={Math.max(progress.max, 1)} value={Math.min(progress.value, Math.max(progress.max, 1))} />}
    </>
  )
  const attrs = { className: 'info-row', 'data-tone': tone, 'data-active': active || undefined, 'data-progress': progress ? '' : undefined, title, ...dataAttrs }
  return (
    <li>
      {onClick
        ? <button type="button" {...attrs} aria-pressed={active} aria-label={ariaLabel ?? label} onClick={onClick}>{body}</button>
        : <div {...attrs}>{body}</div>}
    </li>
  )
}
