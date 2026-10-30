import type { ReactNode } from 'react'
import { Kpi } from './Kpi'

/** Dashboard-style metric: icon, label, value and an optional drilldown, as an expanded KPI. */
export function MetricTile({ icon, label, value, onOpen, tone, note }: { icon: ReactNode; label: string; value: number | string | null | undefined; onOpen?: () => void; tone?: 'warning' | 'error'; note?: string }) {
  const shown = value === null || value === undefined ? '—' : typeof value === 'number' ? value.toLocaleString() : value
  return <Kpi layout="expanded" icon={icon} label={label} value={shown} onClick={onOpen} navigates tone={tone && Number(value) > 0 ? tone : 'neutral'} note={note} ariaLabel={label} />
}
