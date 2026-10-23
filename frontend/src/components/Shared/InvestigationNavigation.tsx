import type { ButtonHTMLAttributes } from 'react'
import { useEffect, useRef } from 'react'
import { ArrowLeft, ArrowRight, ChevronRight, LockKeyhole, LockOpen, CircleHelp, CircleCheck, CircleX, Clock } from 'lucide-react'

/** Global position and neighbours come from the same server-side list ordering. */
export function DetailNavigation({ parent, current, onBack, index = -1, total = 0, onPrevious, onNext, loading = false, error = null, missing = false }: {
  loading?: boolean; error?: Error | null; missing?: boolean;
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
    {loading && <p role="status" className="text-sm">Locating record in filtered results…</p>}
    {error && <p role="alert" className="text-sm text-[var(--error)]">Record navigation unavailable. {error.message}</p>}
    {missing && <p role="status" className="text-sm">This record is missing or no longer matches these filters. Return to the list to review the current results.</p>}
    {index >= 0 && total > 0 && <nav aria-label="Detail records" className="flex gap-2 items-center text-sm">
      <button className="settings-secondary-button" disabled={!onPrevious || index === 0} onClick={onPrevious}><ArrowLeft size={16} aria-hidden="true"/>Previous</button>
      <span className="whitespace-nowrap">{index + 1} of {total} in filtered results</span>
      <button className="settings-secondary-button" disabled={!onNext || index >= total - 1} onClick={onNext}>Next<ArrowRight size={16} aria-hidden="true"/></button>
    </nav>}
  </div>
}

export function EvidenceBadge({ value }: { value: string }) {
  const tone = value === 'active' ? 'success' : value === 'expired' ? 'error' : value === 'future' ? 'info' : value === 'Locked' ? 'warning' : 'neutral'
  const Icon = value === 'active' ? CircleCheck : value === 'expired' ? CircleX : value === 'future' ? Clock : value === 'unknown' ? CircleHelp : null
  return <span className={`evidence-badge evidence-${tone}`}>{Icon && <Icon size={13} aria-hidden="true"/>}{value === 'active' ? 'Currently valid' : value === 'unmapped' ? 'Unmapped' : value}</span>
}

export function LockStatus({ value }: { value?: string | null }) {
  const locked = value === 'Locked', unlocked = value === 'Unlocked'
  const Icon = locked ? LockKeyhole : unlocked ? LockOpen : CircleHelp
  return <span className={`lock-status${locked ? ' lock-status-locked' : ''}`}><Icon size={15} aria-hidden="true"/>{locked ? 'Locked' : unlocked ? 'Unlocked' : value || 'Unknown'}</span>
}

export function AccountEvidence({ status, lock }: { status: string; lock: string }) {
  return <div className="account-evidence"><div aria-label="Account validity">{status.split('/').map(value => <EvidenceBadge key={value} value={value}/>)}</div><div aria-label="Account lock"><LockStatus value={lock}/></div></div>
}

export function DetailButton({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`detail-button ${className}`}>{children}<ArrowRight size={14} aria-hidden="true"/></button>
}

/** Assignment validity only; account and lock evidence keep their own labels. */
export function AssignmentStatus({ value }: { value: string }) {
  const tone = value === 'active' ? 'success' : value === 'expired' ? 'error' : value === 'future' ? 'info' : 'neutral'
  const Icon = value === 'active' ? CircleCheck : value === 'expired' ? CircleX : value === 'future' ? Clock : CircleHelp
  const text = value === 'active' ? 'Active assignment' : value === 'expired' ? 'Expired assignment' : value === 'future' ? 'Future assignment' : 'Unknown validity'
  return <span className={`evidence-badge evidence-${tone}`}><Icon size={13} aria-hidden="true"/>{text}</span>
}
