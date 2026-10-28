import { useEffect, useState, type ReactNode } from 'react'
import { useQuery, type QueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleDashed, CircleDot, History, Lock, RefreshCw, ShieldCheck, ShieldX, UserMinus } from 'lucide-react'
import { sod, emptyFilters, type ContextInfo, type Filters, type Lifecycle } from '@/api/sod'
import { useHistoryValue, useViewHistory, type SodFilterState } from '@/hooks/useViewHistory'
import { Card, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { FormField, Input, SearchInput } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { Button } from '@/components/Shared/Button'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { formatDate } from '@/lib/dateFormat'

export type Tone = 'neutral' | 'success' | 'warning' | 'error' | 'info'
export interface LifecycleView { icon: ReactNode; tone: Tone; text: string }
const size = 14

/** One mapping for every decision lifecycle so shape, wording and tone stay consistent across views. */
export function lifecycleView(value: string): LifecycleView {
  switch (value) {
    case 'Approved': case 'Keep': case 'Accepted': return { icon: <CheckCircle2 size={size} />, tone: 'success', text: value }
    case 'Conditional': return { icon: <CircleDot size={size} />, tone: 'info', text: value }
    case 'Removal required': return { icon: <UserMinus size={size} />, tone: 'error', text: 'Remove' }
    case 'Rejected': return { icon: <ShieldX size={size} />, tone: 'error', text: value }
    case 'Outdated': return { icon: <RefreshCw size={size} />, tone: 'warning', text: value }
    case 'Resolved': return { icon: <ShieldCheck size={size} />, tone: 'success', text: value }
    case 'Historical': return { icon: <History size={size} />, tone: 'neutral', text: value }
    default: return { icon: <CircleDashed size={size} />, tone: 'warning', text: 'Pending' }
  }
}

export function LifecycleBadge({ value }: { value: Lifecycle | string }) {
  const view = lifecycleView(value)
  return <StatusBadge tone={view.tone}>{view.icon}{view.text}</StatusBadge>
}

export const KIND_LABEL: Record<string, string> = { activity: 'Activity', assignment: 'Role assignment', acceptance: 'Risk acceptance' }

export function useSodContext(): [string, (value: string) => void] {
  const [value, set] = useHistoryValue('sodContext')
  return [value || 'current', set]
}

export function useSodFilters(name: string): [Filters, (value: Filters) => void] {
  const [stored, set] = useHistoryValue('sodFilters')
  return [{ ...emptyFilters, ...stored?.[name] }, (value) => set((previous) => ({ ...previous, [name]: value as SodFilterState }))]
}

export const refreshKeys = ['sod-matrix', 'sod-subject', 'sod-queue', 'sod-explorer', 'sod-overview', 'sod-remediation', 'sod-periods', 'sod-period']
export const invalidateSod = (qc: QueryClient) => Promise.all(refreshKeys.map((key) => qc.invalidateQueries({ queryKey: [key] })))

export function ContextBar({ info }: { info?: ContextInfo }) {
  const [context, setContext] = useSodContext()
  const periods = useQuery({ queryKey: ['sod-periods'], queryFn: () => sod<{ items: { id: string; name: string; state: string }[] }>('/api/sod/periods') })
  // A period that was archived or deleted elsewhere falls back to current evidence instead of an error.
  useEffect(() => {
    if (periods.data && context !== 'current' && !periods.data.items.some((period) => period.id === context)) setContext('current')
  }, [periods.data, context, setContext])
  return (
    <Toolbar aria-label="Review context">
      <FormField label="Review context">
        <Select value={context} onChange={(event) => setContext(event.target.value)}>
          <option value="current">Current evidence</option>
          {periods.data?.items.map((period) => <option key={period.id} value={period.id}>{period.name} · {period.state}</option>)}
        </Select>
      </FormField>
      {info && (
        <p className="ui-description" role="status">
          Evaluation date {formatDate(info.as_of)}
          {info.period ? ` · ${info.period.state}` : ' · live imported evidence'}
          {info.frozen && <StatusBadge tone="info"><Lock size={size} aria-hidden="true" />Frozen snapshot, read only</StatusBadge>}
          {!info.frozen && !info.reviewable && <StatusBadge tone="neutral">Read only</StatusBadge>}
          {info.legacy && <StatusBadge tone="warning">Legacy period: only legacy risk decisions exist</StatusBadge>}
        </p>
      )}
    </Toolbar>
  )
}

const DECISION_OPTIONS: Record<string, string[]> = {
  activity_decision: ['Pending', 'Approved', 'Conditional', 'Removal required', 'Outdated'],
  assignment_decision: ['Pending', 'Keep', 'Removal required', 'Outdated'],
  acceptance: ['Pending', 'Accepted', 'Rejected', 'Outdated'],
}

/** Shared filter set for matrices, explorer and queue; Saved Filters reuse the existing storage and component. */
export function FilterBar({ view, filters, setFilters, decisions = true, children }: { view: string; filters: Filters; setFilters: (value: Filters) => void; decisions?: boolean; children?: ReactNode }) {
  const text = (name: string) => (typeof filters[name] === 'string' ? (filters[name] as string) : '')
  const update = (name: string, value: string | boolean) => setFilters({ ...filters, [name]: value })
  const clear = () => setFilters({ ...emptyFilters })
  const field = (name: string, label: string, max = 256) => (
    <FormField key={name} label={label}><Input value={text(name)} maxLength={max} onChange={(event) => update(name, event.target.value)} /></FormField>
  )
  const active = Object.entries(filters).filter(([name, value]) => !['sort', 'descending', 'validity', 'as_of'].includes(name) && value !== '' && value !== false).length + (text('validity') !== 'active' ? 1 : 0)
  const [open, setOpen] = useState(() => typeof window === 'undefined' || window.matchMedia('(min-width: 800px)').matches)
  return (
    <details className="min-w-0" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer font-semibold">Filters{active ? ` · ${active} active` : ''}</summary>
      <div className="mt-3 grid min-w-0 gap-3" role="search" aria-label="SoD filters">
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <FormField label="Search SoD data"><SearchInput aria-label="Search SoD data" value={text('search')} onChange={(event) => update('search', event.target.value)} onClear={() => update('search', '')} /></FormField>
          {field('group', 'SAP user group')}
          {field('risk', 'Risk ID', 512)}
          {field('activity', 'Activity', 512)}
        </div>
        <details>
          <summary className="cursor-pointer">More filters</summary>
          <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {field('username', 'SAP username', 512)}
            {field('role', 'Assigned role', 512)}
            {field('role_suffix', 'Role suffix', 128)}
            {field('tcode', 'Transaction code')}
            {field('category', 'Business area', 120)}
            {field('criticality', 'Source criticality', 64)}
            <FormField label="Assignment validity">
              <Select value={text('validity')} onChange={(event) => update('validity', event.target.value)}>
                <option value="active">Active assignments</option>
                <option value="expired">Expired assignments</option>
                <option value="future">Future assignments</option>
                <option value="unknown">Unknown validity</option>
                <option value="all">All assignment evidence</option>
              </Select>
            </FormField>
            {decisions && Object.entries({ activity_decision: 'Activity review', assignment_decision: 'Role assignment review', acceptance: 'Risk acceptance' }).map(([name, label]) => (
              <FormField key={name} label={label}>
                <Select value={text(name)} onChange={(event) => update(name, event.target.value)}>
                  <option value="">Any</option>
                  {DECISION_OPTIONS[name].map((option) => <option key={option} value={option}>{option === 'Removal required' ? 'Remove' : option}</option>)}
                </Select>
              </FormField>
            ))}
          </div>
        </details>
        <Toolbar>
          {children}
          <SavedFilters view={view} state={filters as Record<string, string | boolean | number | string[]>} apply={(value) => setFilters({ ...emptyFilters, ...value })} clear={clear} showClear={false} />
          <Button variant="ghost" onClick={clear}>Clear all filters</Button>
        </Toolbar>
      </div>
    </details>
  )
}

export function AlertNote({ children }: { children: ReactNode }) {
  return <p className="ui-description flex items-start gap-2"><AlertTriangle size={size} className="mt-0.5 shrink-0" aria-hidden="true" />{children}</p>
}


/** Unavailable evidence is never presented as "no conflict". */
export function CoverageNotice({ info }: { info?: ContextInfo }) {
  const { change } = useViewHistory()
  if (!info || info.coverage.status === 'available') return null
  const disabled = info.coverage.reason === 'mapping_disabled'
  return (
    <Card aria-label="Evidence coverage">
      <StatusBadge tone="warning">Analysis unavailable or incomplete</StatusBadge>
      <p>{disabled ? 'User–Role Mapping is disabled. Re-enable it in Features to analyze retained assignment evidence.' : 'A supported SoD matrix, validated role catalogue and User–Role Mapping data are required.'}</p>
      <p className="ui-description">Unavailable evidence is not proof that no access or conflict exists.</p>
      <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: disabled ? 'features' : 'sod' })}>Review configuration</Button></Toolbar>
    </Card>
  )
}
