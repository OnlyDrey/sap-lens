import { useEffect, type ReactNode } from 'react'
import { useQuery, type QueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleDashed, CircleDot, History, Lock, RefreshCw, ShieldCheck, ShieldX, UserMinus } from 'lucide-react'
import { sod, emptyFilters, type ContextInfo, type Filters, type Lifecycle } from '@/api/sod'
import { useHistoryValue, useViewHistory, type SodFilterState } from '@/hooks/useViewHistory'
import { Card, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { FormField, Input, SearchInput } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { Button } from '@/components/Shared/Button'
import { FilterLayout, FilterSection, PageToolbar, SortControl } from '@/components/Shared/FilterLayout'
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

export interface SodSubject { user: string; risk?: string; activity?: string }
/** Investigation target lives in view history: Back closes it, and it returns after visiting a role or user page. */
export function useSodSubject(): [SodSubject | null, (value: SodSubject | null) => void] {
  const { view, change } = useViewHistory()
  return [view.sodSubject || null, (value) => change({ sodSubject: value }, value === null)]
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

export type FilterField = 'group' | 'risk' | 'activity' | 'username' | 'role' | 'role_suffix' | 'tcode' | 'category' | 'criticality' | 'validity' | 'activity_decision' | 'assignment_decision' | 'acceptance'
const FIELD_LABELS: Record<string, [string, number]> = {
  group: ['SAP user group', 256], risk: ['Risk ID', 512], activity: ['Activity', 512], username: ['SAP username', 512], role: ['Assigned role', 512], role_suffix: ['Role suffix', 128],
  tcode: ['Transaction code', 256], category: ['Business area', 120], criticality: ['Source criticality', 64],
}
const FIELD_SECTIONS: { title: string; fields: FilterField[] }[] = [
  { title: 'Subject', fields: ['group', 'username'] },
  { title: 'Risk and activity', fields: ['risk', 'activity', 'tcode', 'category', 'criticality'] },
  { title: 'Roles and assignments', fields: ['role', 'role_suffix', 'validity'] },
  { title: 'Review status', fields: ['activity_decision', 'assignment_decision', 'acceptance'] },
]
const DECISION_LABELS: Record<string, string> = { activity_decision: 'Activity review', assignment_decision: 'Role assignment review', acceptance: 'Risk acceptance' }

/** Filters relevant to the page. Hidden fields are cleared when a Saved Filter is applied so they cannot silently narrow results. */
export function SodFilters({ view, filters, setFilters, fields, sorts, actions, children }: {
  view: string; filters: Filters; setFilters: (value: Filters) => void; fields: FilterField[]; sorts?: { value: string; label: string }[]; actions?: ReactNode; children: ReactNode
}) {
  const text = (name: string) => (typeof filters[name] === 'string' ? (filters[name] as string) : '')
  const update = (name: string, value: string | boolean) => setFilters({ ...filters, [name]: value })
  const clear = () => setFilters({ ...emptyFilters })
  const shown = new Set<string>(fields)
  const apply = (value: Record<string, unknown>) => {
    const next = { ...emptyFilters, ...value } as Filters
    for (const name of Object.keys(FIELD_LABELS).concat(Object.keys(DECISION_LABELS), ['validity'])) if (!shown.has(name)) next[name] = emptyFilters[name]
    setFilters(next)
  }
  const active = [...shown].filter((name) => (name === 'validity' ? text(name) !== 'active' : text(name) !== '')).length + (text('search') ? 1 : 0)
  const field = (name: FilterField) => {
    if (name === 'validity') return (
      <FormField key={name} label="Assignment validity">
        <Select value={text('validity')} onChange={(event) => update('validity', event.target.value)}>
          <option value="active">Active assignments</option>
          <option value="expired">Expired assignments</option>
          <option value="future">Future assignments</option>
          <option value="unknown">Unknown validity</option>
          <option value="all">All assignment evidence</option>
        </Select>
      </FormField>
    )
    if (DECISION_LABELS[name]) return (
      <FormField key={name} label={DECISION_LABELS[name]}>
        <Select value={text(name)} onChange={(event) => update(name, event.target.value)}>
          <option value="">Any</option>
          {DECISION_OPTIONS[name].map((option) => <option key={option} value={option}>{option === 'Removal required' ? 'Remove' : option}</option>)}
        </Select>
      </FormField>
    )
    const [label, max] = FIELD_LABELS[name]
    return <FormField key={name} label={label}><Input value={text(name)} maxLength={max} onChange={(event) => update(name, event.target.value)} /></FormField>
  }
  const sidebar = (
    <div className="grid min-w-0 gap-3" role="search" aria-label="SoD filters">
      <FilterSection title="Saved Filters">
        <SavedFilters view={view} state={filters as Record<string, string | boolean | number | string[]>} apply={apply} clear={clear} showClear={false} />
      </FilterSection>
      {FIELD_SECTIONS.map((section) => {
        const visible = section.fields.filter((name) => shown.has(name))
        return visible.length ? <FilterSection key={section.title} title={section.title}>{visible.map(field)}</FilterSection> : null
      })}
      <Button variant="ghost" onClick={clear} disabled={!active && text('sort') === 'subject' && filters.descending !== true}>Reset filters</Button>
    </div>
  )
  const toolbar = (
    <PageToolbar>
      <SearchInput aria-label="Search SoD data" placeholder="Search" value={text('search')} onChange={(event) => update('search', event.target.value)} onClear={() => update('search', '')} />
      {sorts && <SortControl value={text('sort') || sorts[0].value} options={sorts} descending={filters.descending === true} onChange={(value) => update('sort', value)} onDescending={(value) => update('descending', value)} />}
      {actions}
      <Button variant="ghost" onClick={clear}>Reset</Button>
    </PageToolbar>
  )
  return <FilterLayout activeCount={active} sidebar={sidebar} toolbar={toolbar}>{children}</FilterLayout>
}

export function AlertNote({ children }: { children: ReactNode }) {
  return <p className="ui-description flex items-start gap-2"><AlertTriangle size={size} className="mt-0.5 shrink-0" aria-hidden="true" />{children}</p>
}


/** Unavailable evidence is never presented as "no conflict". */
export function CoverageNotice({ info }: { info?: ContextInfo }) {
  const { change } = useViewHistory()
  if (!info || info.coverage.status === 'available') return null
  const disabled = info.coverage.reason === 'mapping_disabled',
    off = info.coverage.reason === 'sod_disabled'
  return (
    <Card aria-label="Evidence coverage">
      <StatusBadge tone="warning">Analysis unavailable or incomplete</StatusBadge>
      <p>{off ? 'SoD is turned off in Features. Retained evidence and decisions return when it is enabled.' : disabled ? 'User–Role Mapping is disabled. Re-enable it in Features to analyze retained assignment evidence.' : 'A supported SoD matrix, validated role catalogue and User–Role Mapping data are required.'}</p>
      <p className="ui-description">Unavailable evidence is not proof that no access or conflict exists.</p>
      <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: disabled || off ? 'features' : 'sod' })}>Review configuration</Button></Toolbar>
    </Card>
  )
}
