import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { calmZero } from '@/lib/labels'

export interface KpiProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  /** Secondary information under the value (a unit, a share, a reason). */
  note?: ReactNode
  /** Progress only where the numerator and denominator are real data. */
  progress?: { value: number; max: number; label: string }
  /** `compact` is one line (label, value); `expanded` stacks icon and label above a larger value. */
  layout?: 'compact' | 'expanded'
  tone?: 'neutral' | 'warning' | 'error' | 'success'
  /** Makes the KPI a real button. Without it the KPI is informational. */
  onClick?: () => void
  /** For a filter KPI: pressed state. Leave undefined for navigation KPIs (no aria-pressed). */
  active?: boolean
  /** Shows the open arrow; use for KPIs that navigate to another view. */
  navigates?: boolean
  disabled?: boolean
  title?: string
  /** Overrides the accessible name; by default the name is the visible label and value. */
  ariaLabel?: string
  className?: string
  data?: Record<string, string | undefined>
}

/** Shared KPI: informational group or genuine button, in the same compact or expanded layout, themed by semantic tokens. */
export function Kpi({ label, value, icon, note, progress, layout = 'compact', tone = 'neutral', onClick, active, navigates, disabled, title, ariaLabel, className = '', data }: KpiProps) {
  const dataAttrs = Object.fromEntries(Object.entries(data ?? {}).map(([key, item]) => [`data-${key}`, item]))
  const body = (
    <>
      {icon && <span className="ui-kpi-icon" aria-hidden="true">{icon}</span>}
      <span className="ui-kpi-label">{label}</span>
      <strong className="ui-kpi-value">{value}</strong>
      {onClick && navigates && <ArrowUpRight size={14} aria-hidden="true" className="ui-kpi-arrow" />}
      {note && <small className="ui-kpi-note">{note}</small>}
      {progress && <progress className="ui-kpi-progress" aria-label={progress.label} max={Math.max(progress.max, 1)} value={Math.min(progress.value, Math.max(progress.max, 1))} />}
    </>
  )
  const attrs = { className: `ui-kpi ${className}`.trim(), 'data-layout': layout, 'data-tone': calmZero(tone, value), 'data-icon': icon ? 'true' : 'false', 'data-active': active || undefined, title, ...dataAttrs }
  return onClick
    ? <button type="button" {...attrs} aria-pressed={active} aria-label={ariaLabel} disabled={disabled} onClick={onClick}>{body}</button>
    : <div {...attrs} data-static="true" role="group" aria-label={ariaLabel ?? label}>{body}</div>
}
