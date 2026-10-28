import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'

/** Dashboard-style metric: icon, label, value and an optional drilldown. Same markup and CSS as the Dashboard tiles. */
export function MetricTile({ icon, label, value, onOpen, tone, note }: { icon: ReactNode; label: string; value: number | string | null | undefined; onOpen?: () => void; tone?: 'warning' | 'error'; note?: string }) {
  const content = (
    <>
      {icon}
      <span className="dashboard-metric-label">{label}</span>
      <strong>{value === null || value === undefined ? '—' : typeof value === 'number' ? value.toLocaleString() : value}</strong>
      {onOpen && <ArrowUpRight size={14} aria-hidden="true" />}
      {note && <small>{note}</small>}
    </>
  )
  const attrs = { className: 'dashboard-metric', 'data-tone': tone && Number(value) > 0 ? tone : 'neutral' }
  return onOpen
    ? <button type="button" aria-label={label} {...attrs} onClick={onOpen}>{content}</button>
    : <div role="group" aria-label={label} {...attrs}>{content}</div>
}
