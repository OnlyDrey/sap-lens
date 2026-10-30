import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'

export interface BarDatum { key: string; label: ReactNode; value: number; /** Native tooltip and accessible detail. */ title?: string; ariaLabel?: string; onOpen?: () => void }

/** Horizontal bar chart from real counts: label, proportional bar and value on one row. Rows are buttons only when they can open a filtered view. Bars scale to the largest value shown. */
export function BarChart({ label, data, empty = 'No data' }: { label: string; data: BarDatum[]; empty?: string }) {
  const max = Math.max(1, ...data.map(item => item.value))
  if (!data.length) return <p className="ui-description">{empty}</p>
  return (
    <ul className="chart-bars" aria-label={label}>
      {data.map(item => {
        const body = (
          <>
            <span className="chart-label">{item.label}</span>
            <span className="chart-track" aria-hidden="true"><span className="chart-fill" style={{ width: `${(item.value / max) * 100}%` }} /></span>
            <strong className="chart-value">{item.value.toLocaleString()}</strong>
            {item.onOpen && <ArrowUpRight size={14} aria-hidden="true" className="chart-arrow" />}
          </>
        )
        return (
          <li key={item.key}>
            {item.onOpen
              ? <button type="button" className="chart-row" title={item.title} aria-label={item.ariaLabel ?? `${item.key}: ${item.value}`} onClick={item.onOpen}>{body}</button>
              : <div className="chart-row" title={item.title} role="img" aria-label={item.ariaLabel ?? `${item.key}: ${item.value}`}>{body}</div>}
          </li>
        )
      })}
    </ul>
  )
}

export interface Segment { key: string; label: string; value: number; tone: 'success' | 'neutral' | 'warning' | 'error'; title?: string; onOpen?: () => void }

/** One stacked bar of mutually exclusive parts of a known total, with a legend whose entries open the matching list. Parts with no records take no width. */
export function StackedBar({ label, segments, total, caption }: { label: string; segments: Segment[]; total: number; caption?: ReactNode }) {
  const sum = Math.max(1, total)
  return (
    <div className="chart-stack">
      <div className="chart-stack-bar" role="img" aria-label={`${label}: ${segments.map(item => `${item.label} ${item.value}`).join(', ')} of ${total}`}>
        {segments.filter(item => item.value > 0).map(item => <span key={item.key} data-tone={item.tone} title={item.title ?? `${item.label}: ${item.value.toLocaleString()} of ${total.toLocaleString()}`} style={{ width: `${(item.value / sum) * 100}%` }} />)}
      </div>
      <ul className="chart-legend" aria-label={`${label} legend`}>
        {segments.map(item => {
          const body = <><span className="chart-swatch" data-tone={item.tone} aria-hidden="true" /><span className="chart-label">{item.label}</span><strong className="chart-value">{item.value.toLocaleString()}</strong>{item.onOpen && <ArrowUpRight size={14} aria-hidden="true" className="chart-arrow" />}</>
          return <li key={item.key}>{item.onOpen ? <button type="button" className="chart-row" aria-label={`${item.label}: ${item.value.toLocaleString()}`} title={item.title} onClick={item.onOpen}>{body}</button> : <div className="chart-row">{body}</div>}</li>
        })}
      </ul>
      {caption && <p className="ui-description">{caption}</p>}
    </div>
  )
}
