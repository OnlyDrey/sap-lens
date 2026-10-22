import { useEffect, useRef } from 'react'
import { ArrowLeft, ArrowRight, ChevronRight } from 'lucide-react'

/** Position is deliberately limited to the current filtered, sorted result page. */
export function DetailNavigation({ parent, current, onBack, index = -1, total = 0, onPrevious, onNext }: {
  parent: string; current: string; onBack: () => void; index?: number; total?: number;
  onPrevious?: () => void; onNext?: () => void;
}) {
  const focus = useRef<HTMLSpanElement>(null)
  useEffect(() => { focus.current?.focus({ preventScroll: true }) }, [current])
  return <div className="detail-navigation">
    <nav aria-label="Breadcrumb" className="flex items-center gap-2 min-w-0 text-sm">
      <button className="settings-secondary-button" onClick={onBack}><ArrowLeft size={16} aria-hidden="true"/>Back to {parent === 'User Access' ? 'users' : parent}</button>
      <ChevronRight size={16} aria-hidden="true" className="shrink-0"/>
      <span ref={focus} tabIndex={-1} aria-current="page" className="truncate" title={current}>{current}</span>
    </nav>
    {index >= 0 && total > 0 && <nav aria-label="Detail records" className="flex gap-2 items-center text-sm">
      <button className="settings-secondary-button" disabled={!onPrevious || index === 0} onClick={onPrevious}><ArrowLeft size={16} aria-hidden="true"/>Previous</button>
      <span className="whitespace-nowrap">{index + 1} of {total} on this page</span>
      <button className="settings-secondary-button" disabled={!onNext || index >= total - 1} onClick={onNext}>Next<ArrowRight size={16} aria-hidden="true"/></button>
    </nav>}
  </div>
}

export function EvidenceBadge({ value }: { value: string }) {
  const tone = value === 'active' ? 'success' : value === 'expired' ? 'error' : value === 'future' ? 'info' : 'neutral'
  return <span className={`evidence-badge evidence-${tone}`}>{value === 'active' ? 'Currently valid' : value === 'unmapped' ? 'Unmapped' : value}</span>
}
