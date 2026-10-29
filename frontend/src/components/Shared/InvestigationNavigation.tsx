import { Button, IconButton } from './Button'
import { StatusBadge } from './Presentation'
import { AccountStatus } from './AccountStatus'
import type { ButtonHTMLAttributes } from 'react'
import { useEffect, useRef } from 'react'
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Undo2, CircleHelp, CircleCheck, CircleX, Clock } from 'lucide-react'

/** Global position and neighbours come from the same server-side list ordering. */
export function DetailNavigation({ parent, current, onBack, previousUser, index = -1, total = 0, onPrevious, onNext, showBreadcrumb=true, loading = false, error = null, missing = false }: {
  previousUser?: { name: string; onBack: () => void };
  showBreadcrumb?:boolean; loading?: boolean; error?: Error | null; missing?: boolean;
  parent: string; current: string; onBack: () => void; index?: number; total?: number;
  onPrevious?: () => void; onNext?: () => void;
}) {
  const focus = useRef<HTMLSpanElement>(null)
  useEffect(() => { focus.current?.focus({ preventScroll: true }) }, [current])
  const noun = parent === 'User Access' ? 'user' : parent === 'Release Roles' ? 'release role' : 'record'
  return <div className="detail-navigation">
    {showBreadcrumb&&<nav aria-label="Breadcrumb" className="detail-breadcrumb">
      <Button variant="ghost" size="compact" className="detail-back-action" onClick={onBack}><ArrowLeft size={16} aria-hidden="true"/>Back to {parent === 'User Access' ? 'users' : parent}</Button>
      <ChevronRight size={14} aria-hidden="true" className="shrink-0"/>
      <span ref={focus} tabIndex={-1} aria-current="page" className="truncate font-semibold" title={current}>{current}</span>
    </nav>}
    {previousUser && <Button variant="ghost" size="compact" className="detail-back-action detail-return" aria-label={`Back to previous user: ${previousUser.name}`} onClick={previousUser.onBack}><Undo2 size={14} aria-hidden="true"/>Return to {previousUser.name}</Button>}
    {index >= 0 && total > 0 && <nav aria-label="Detail records" className="detail-record-controls">
      <IconButton variant="ghost" label="Previous" tooltip={`Previous ${noun} in filtered results`} disabled={!onPrevious || index === 0} onClick={onPrevious}><ChevronLeft size={16} aria-hidden="true"/></IconButton>
      <span className="whitespace-nowrap">{index + 1} of {total}<span className="sr-only"> in filtered results</span></span>
      <IconButton variant="ghost" label="Next" tooltip={`Next ${noun} in filtered results`} disabled={!onNext || index >= total - 1} onClick={onNext}><ChevronRight size={16} aria-hidden="true"/></IconButton>
    </nav>}
    {loading && <p role="status" className="detail-navigation-note">Locating record in filtered results…</p>}
    {error && <p role="alert" className="detail-navigation-note text-[var(--error)]">Record navigation unavailable. {error.message}</p>}
    {missing && <p role="status" className="detail-navigation-note">This record is missing or no longer matches these filters. Return to the list to review the current results.</p>}
  </div>
}

export function EvidenceBadge({ value }: { value: string }) {
  const tone = value === 'active' ? 'success' : value === 'expired' ? 'error' : value === 'future' ? 'info' : value === 'Locked' ? 'warning' : 'neutral'
  const Icon = value === 'active' ? CircleCheck : value === 'expired' ? CircleX : value === 'future' ? Clock : value === 'unknown' ? CircleHelp : null
  return <StatusBadge tone={tone}>{Icon && <Icon size={13} aria-hidden="true"/>}{value === 'active' ? 'Currently valid' : value === 'unmapped' ? 'Unmapped' : value === 'exact' ? 'Exact' : value === 'wildcard' ? 'Wildcard' : value === 'ambiguous' ? 'Ambiguous' : value}</StatusBadge>
}

export function LockStatus({value}:{value?:string|null}) {return <AccountStatus value={value||'Unknown'} kind="lock"/>}

export function AccountEvidence({ status, lock }: { status: string; lock: string }) {
  return <div className="account-evidence"><div aria-label="Account validity"><AccountStatus value={status}/></div><div aria-label="Account lock"><LockStatus value={lock}/></div></div>
}

export function DetailButton({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <Button {...props} className={`detail-button ${className}`}>{children}<ArrowRight size={14} aria-hidden="true"/></Button>
}

/** Assignment validity only; account and lock evidence keep their own labels. */
export function AssignmentStatus({ value }: { value: string }) {
  const tone = value === 'active' ? 'success' : value === 'expired' ? 'error' : value === 'future' ? 'info' : 'neutral'
  const Icon = value === 'active' ? CircleCheck : value === 'expired' ? CircleX : value === 'future' ? Clock : CircleHelp
  const text = value === 'active' ? 'Active assignment' : value === 'expired' ? 'Expired assignment' : value === 'future' ? 'Future assignment' : 'Unknown validity'
  return <StatusBadge tone={tone}><Icon size={13} aria-hidden="true"/>{text}</StatusBadge>
}
