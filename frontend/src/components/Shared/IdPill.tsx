import type { CSSProperties } from 'react'

/** Compact identifier pill for risks and activities. The label is always text; the optional color only tints the pill. */
export function IdPill({ kind, value, color, title, className = '' }: { kind: 'risk' | 'activity'; value: string; color?: string; title?: string; className?: string }) {
  const style = color && /^#[0-9a-fA-F]{6}$/.test(color) ? ({ '--pill': color } as CSSProperties) : undefined
  return <span className={`id-pill id-pill-${kind} ${className}`} style={style} data-colored={!!style} title={title || `${kind === 'risk' ? 'Risk' : 'Activity'} ${value}`}>{value}</span>
}
