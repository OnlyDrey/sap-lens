import type { CSSProperties } from 'react'
import { Activity, ShieldAlert } from 'lucide-react'

/** Neutral, non-severity hues (no red, amber or green): a stable default per identifier until a local color is configured. */
const DEFAULT_COLORS = ['#3b6fd4', '#1f8a8a', '#7a5fc9', '#b0509b', '#4b55b8', '#5c7285', '#9a6a3a', '#2a8bb0']
export const defaultPillColor = (kind: string, value: string) => {
  let hash = 0
  for (const char of `${kind}:${value}`) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return DEFAULT_COLORS[hash % DEFAULT_COLORS.length]
}

/** Compact identifier pill for risks and activities. The label is always text; the optional color only tints the pill. */
export function IdPill({ kind, value, color, title, className = '' }: { kind: 'risk' | 'activity'; value: string; color?: string; title?: string; className?: string }) {
  const configured = !!color && /^#[0-9a-fA-F]{6}$/.test(color)
  const style = { '--pill': configured ? color : defaultPillColor(kind, value) } as CSSProperties
  return <span className={`id-pill id-pill-${kind} ${className}`} style={style} data-colored={configured} data-default-color={!configured || undefined} title={title || `${kind === 'risk' ? 'Risk' : 'Activity'} ${value}`}>{kind === 'risk' ? <ShieldAlert size={11} aria-hidden="true" /> : <Activity size={11} aria-hidden="true" />}<span className="id-pill-text">{value}</span></span>
}
