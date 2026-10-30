import {Fragment,useState,type ReactNode} from 'react'
import {Button} from '@/components/Shared/Button'
import {useModules} from '@/hooks/useModules'
import {ModuleBadge} from '@/components/Modules/ModuleBadge'
import {useSourceEvidence} from '@/components/Settings/SourceStatus'
import { PageHeader, SectionHeader, StatusBadge } from '@/components/Shared/Presentation'
import { RefreshCw, AlertTriangle, Loader2, CircleDashed, LayoutDashboard, ShieldAlert, ShieldCheck, HeartPulse, BarChart3, SlidersHorizontal, UsersRound as ConflictUsers } from 'lucide-react'
import { formatTimestamp } from '@/lib/dateFormat'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  ClipboardCheck,
  Database,
  UsersRound,
  Network,
  FileCheck2,
  CalendarDays,
  MailCheck,
  UserCog,
} from 'lucide-react'
import { apiRequest } from '@/api/client'
import { useViewHistory } from '@/hooks/useViewHistory'
import { useApplicationData } from '@/state/ApplicationData'
import { InfoList, InfoRow } from '@/components/Shared/InfoList'
import { BarChart, StackedBar } from '@/components/Shared/Charts'
import { InfoTip } from '@/components/Shared/InfoTip'
import { Dialog } from '@/components/Shared/Dialog'
import { MATCH_HEALTH_LEGEND, matchHealthTone } from '@/lib/health'
import { ASSIGNMENT_BANDS } from '@/lib/assignmentBands'
import { sourceState } from '@/lib/sourceState'
import { fetchConfiguration } from '@/api/configuration'
/** Cards below SAP Overview, in reading order. Reordering this list reorders the rendered elements. */
export const DASHBOARD_CARDS = ['access-risk', 'review-progress', 'directory-health', 'sod', 'role-distribution', 'assignment-distribution'] as const
type DashboardCard = (typeof DASHBOARD_CARDS)[number]
const SOURCE_NAMES: Record<string, string> = { roles: 'Role Catalogue', users: 'User–Role Mapping', employees: 'Employee Directory', sod: 'SoD Matrix' }
/** Account Review filter applied when a Dashboard metric opens it. Each value is a real finding the review list can filter by. */
const REVIEW_FINDING: Record<string, string> = {
  outdated: 'stale', position_changes: 'position_change', reviewed: 'reviewed', pending: 'pending', ad_disabled_open: 'ad_disabled_open',
  unresolved: 'directory_match', directory_missing: 'directory_missing', directory_ambiguous: 'directory_ambiguous', email_matches: 'matched',
}
type Lifecycle = 'loading' | 'no-source' | 'initial-load' | 'ready' | 'refreshing' | 'refresh-failed' | 'unavailable'
/** Data lifecycle shown above the cards; previously validated data is never hidden by a refresh. */
function dashboardLifecycle({ fetching, failed, loading, hasValidatedData, hasEnabledSource }: { fetching: boolean; failed: boolean; loading: boolean; hasValidatedData: boolean; hasEnabledSource: boolean }): Lifecycle {
  if (fetching) return 'loading'
  if (!hasEnabledSource && !hasValidatedData) return 'no-source'
  if (loading && !hasValidatedData) return 'initial-load'
  if (failed && hasValidatedData) return 'refresh-failed'
  if (loading) return 'refreshing'
  return hasValidatedData ? 'ready' : 'unavailable'
}
function DataLifecycleStatus({ state, validatedAt, warning, onConfigure }: { state: Lifecycle; validatedAt?: string | null; warning?: string | null; onConfigure: () => void }) {
  const stamp = validatedAt ? formatTimestamp(validatedAt) : null
  if (state === 'no-source') return (
    <div className="dashboard-status" data-state={state} role="status">
      <Database size={18} aria-hidden="true" />
      <p><strong>No SAP source is configured yet.</strong> Connect a role catalogue and a user access export to see metrics; nothing is shown as zero until data exists.</p>
      <Button size="compact" onClick={onConfigure}><Database size={14} aria-hidden="true"/>Configure data sources</Button>
    </div>
  )
  const text: Record<Exclude<Lifecycle, 'no-source'>, string> = {
    loading: 'Loading overview…',
    'initial-load': 'Loading and validating SAP data…',
    refreshing: `Refreshing in the background. Showing data validated ${stamp ?? 'earlier'}.`,
    'refresh-failed': `The latest refresh did not complete. Showing previously validated data${stamp ? ` from ${stamp}` : ''}${warning ? `: ${warning}` : '.'}`,
    unavailable: 'Source data is unavailable. Review Health & Diagnostics.',
    ready: stamp ? `Data validated ${stamp}.` : '',
  }
  if (!text[state]) return null
  return (
    <p className="dashboard-status" data-state={state} role={state === 'refresh-failed' ? 'alert' : 'status'} aria-live="polite">
      {(state === 'refreshing' || state === 'initial-load' || state === 'loading') && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
      {state === 'refresh-failed' && <AlertTriangle size={14} aria-hidden="true" />}
      <span>{text[state]}</span>
    </p>
  )
}
interface Metric {
  id: string
  label: string
  value: number | null
  destination: 'roles' | 'users' | 'releases' | 'employees' | 'review'
  context: string
  unavailable_reason: string | null
}
interface Source {
  id: 'roles' | 'users' | 'employees'
  name: string
  enabled: boolean
  configured: boolean
  available: boolean
  last_import?:string|null
  last_checked?:string|null
}
export function Dashboard() {
  const { view, change } = useViewHistory(),
    { loading } = useApplicationData()
  const sourceEvidence=useSourceEvidence('roles')
  const configuration=useQuery({queryKey:['configuration'],queryFn:fetchConfiguration})
  const sodEnabled=configuration.data?.settings.features?.sod===true
  const sodSummary=useQuery({queryKey:['sod-overview'],enabled:sodEnabled,queryFn:()=>apiRequest<{governance:{available:boolean;reason?:string|null;missing?:string[];users_with_conflicts?:number;user_risk_findings?:number;activities?:Record<string,number>;acceptance?:Record<string,number>;remediation?:{open_actions:number;overdue:number}}}>('/api/sod/overview')})
  const openSod=(sodView:'overview'|'risk-matrix'|'activity-matrix'|'reviews')=>change({page:'sod',sodView,settings:false,detailRole:null})
  const query = useQuery({
    queryKey: ['dashboard'],
    queryFn: () =>
      apiRequest<{
        metrics: Metric[]
        sources?: Source[]
        role_distribution?:Record<string,number>|null
        assignment_distribution?:Record<string,number>|null
        review_population?:number|null
        coverage_total?: number
        last_successful_refresh?: string | null
        source_warning?: string | null
        notice: string
      }>('/api/dashboard'),
  })
  type DashboardData = NonNullable<typeof query.data>
  const open = (metric: Metric, area='') =>
    metric.destination === 'review'
      ? change({
          page: 'users',
          accessMode: 'review',
          accountReviewFilters:{search:'',licenses:[],states:[],sort:'username',descending:false},
          kpiNavigation:{...view.kpiNavigation,users:(view.kpiNavigation?.users||0)+1},
          user: '',
          reviewFindings: [
            REVIEW_FINDING[metric.id] ?? 'any'],
          settings: false,
          detailRole: null,
        })
      : metric.destination === 'employees'
        ? change({ settings: true, settingsTarget: 'employees' })
        : change({
            page: metric.destination,
            kpiNavigation: {
              ...view.kpiNavigation,
              [metric.destination]:
                (view.kpiNavigation?.[metric.destination] || 0) + 1,
            },
            ...(metric.destination === 'users'
              ? { user: '', userContext: {}, accessMode: 'directory' as const }
              : {}),
            ...(metric.destination === 'releases' ? { release: null } : {}),
            ...(metric.destination === 'roles' ? { comparison: false, catalogueArea:area } : {}),
            detailRole: null,
            settings: false,
          })
  const iconFor = (metric: Metric) => metric.id === 'account_review' ? ClipboardCheck
    : metric.id === 'position_changes' ? UserCog
    : metric.id === 'areas' ? Network
    : metric.id === 'releases' ? FileCheck2
    : metric.id === 'expired' || metric.id === 'future' ? CalendarDays
    : metric.id.includes('match') || metric.id === 'unresolved' ? MailCheck
    : metric.destination === 'users' ? UsersRound : Database
  /** Displayed value of one metric: a skeleton while loading, a stated reason when unavailable. */
  const present = (metric: Metric, coverage = 0) => {
    const unavailable = metric.value === null
    const value: ReactNode = unavailable
      ? (loading && !metric.unavailable_reason?.toLowerCase().includes('disabled') ? <><span className="dashboard-skeleton" aria-hidden="true"/><span className="sr-only">Loading</span></> : 'Unavailable')
      : coverage ? `${metric.value!.toLocaleString()} / ${coverage.toLocaleString()}` : metric.value!.toLocaleString()
    return { unavailable, value }
  }
  /** One metric as an information row. `primary` gives the figure more weight; `label` overrides the API wording. */
  const row = (metric: Metric, opts: { primary?: boolean; label?: string } = {}) => {
    const Icon = iconFor(metric), { unavailable, value } = present(metric)
    return <InfoRow key={metric.id} primary={opts.primary} icon={<Icon size={opts.primary ? 18 : 16} aria-hidden="true" />} label={opts.label ?? metric.label} ariaLabel={opts.label ?? metric.label} title={metric.context} value={value} data={{ metric: metric.id }}
      tone={['directory_missing', 'directory_ambiguous', 'position_changes', 'ad_disabled_open'].includes(metric.id) && !!metric.value ? 'warning' : 'neutral'}
      note={unavailable ? metric.unavailable_reason : undefined} onClick={() => open(metric)} navigates />
  }
  const [allAreas,setAllAreas]=useState(false)
  const modules=useModules()
  const lifecycle = dashboardLifecycle({
    fetching: query.isLoading,
    failed: query.isError || !!query.data?.source_warning,
    loading,
    hasValidatedData: !!query.data?.metrics.some(metric => metric.value !== null),
    hasEnabledSource: !query.data?.sources || query.data.sources.some(source => source.configured && source.enabled),
  })
  const metricOf = (d: DashboardData, id: string) => d.metrics.find(m => m.id === id)
  const list = (d: DashboardData, ids: readonly string[]) => ids.map(id => metricOf(d, id)).filter((m): m is Metric => !!m)
  /** Card with a heading, an optional info popover for secondary explanations and a short footnote. */
  const card = (name: string, icon: ReactNode, children: ReactNode, opts: { note?: string; tip?: ReactNode; className?: string } = {}) => (
    <section key={name} aria-label={name} className={`dashboard-section dashboard-card ${opts.className ?? ''}`.trim()}>
      <SectionHeader title={name} icon={icon}>{opts.tip && <InfoTip label={`About ${name}`}>{opts.tip}</InfoTip>}</SectionHeader>
      {children}
      {opts.note && <p className="text-xs text-[var(--muted)]">{opts.note}</p>}
    </section>
  )
  /** Access & Risk: SAP users as the primary figure, the remaining source facts as compact rows. */
  const renderAccessRisk = (d: DashboardData) => {
    const users = metricOf(d, 'users')
    return card('Access & Risk', <ShieldAlert size={18}/>, (
      <InfoList label="Access & Risk">
        {users && row(users, { primary: true })}
        {list(d, ['ad_disabled_open', 'assignments', 'mappings', 'roles', 'releases']).map(m => row(m, m.id === 'ad_disabled_open' ? { label: 'AD disabled / SAP active' } : {}))}
      </InfoList>
    ), { note: 'Counts describe source evidence, not effective SAP authorization.' })
  }
  /** Review Progress: the single Dashboard presentation of account review completion. */
  const renderReviewProgress = (d: DashboardData) => {
    const reviewed = metricOf(d, 'reviewed'), pending = metricOf(d, 'pending'), outdated = metricOf(d, 'outdated')
    const ready = d.review_population != null && reviewed?.value != null && pending?.value != null && outdated?.value != null
    const population = d.review_population ?? 0, done = reviewed?.value ?? 0
    return card('Review Progress', <ClipboardCheck size={18}/>, ready ? (
      <>
        <div className="progress-summary" data-metric="review_completion">
          <strong className="progress-summary-value">{population ? `${((done / population) * 100).toFixed(1)}%` : '0.0%'}</strong>
          <span className="progress-summary-caption">{done.toLocaleString()} of {population.toLocaleString()} accounts reviewed</span>
        </div>
        <StackedBar label="Account review progress" total={population} segments={[
          { key: 'completed', label: 'Completed reviews', value: done, tone: 'success', onOpen: () => open(reviewed!) },
          { key: 'pending', label: 'Not yet reviewed', value: pending!.value! - outdated!.value!, tone: 'neutral', title: 'Accounts without a current decision (excluding outdated reviews)', onOpen: () => open(pending!) },
          { key: 'outdated', label: 'Outdated reviews', value: outdated!.value!, tone: 'warning', title: 'The decision was recorded against evidence that has since changed', onOpen: () => open(outdated!) },
        ]} caption={`All ${population.toLocaleString()} imported SAP accounts. Outdated reviews are pending until reviewed again.`} />
      </>
    ) : <p className="ui-description">{reviewed?.unavailable_reason ?? 'Review progress needs the User Access data and account-review annotations.'}</p>)
  }
  /** Directory & Data Health: match quality (matched share of SAP identities) first, then the status rows. Position changes are a separate signal. */
  const renderDirectory = (d: DashboardData) => {
    const matched = metricOf(d, 'email_matches'), total = d.coverage_total || 0
    const percent = matched?.value != null && total ? (matched.value / total) * 100 : null
    return card('Directory & Data Health', <HeartPulse size={18}/>, (
      <>
        {percent !== null && matched?.value != null
          ? <div className="progress-summary" data-metric="directory_match_quality">
              <strong className="progress-summary-value">{percent.toFixed(1)}%</strong>
              <span className="progress-summary-caption">{matched.value.toLocaleString()} / {total.toLocaleString()} SAP identities matched</span>
              <progress className="progress-summary-bar" data-tone={matchHealthTone(percent)} max={total} value={matched.value} aria-label={`SAP identity match coverage: ${percent.toFixed(1)}% matched`} title="Directory matching quality only; it does not describe other data sources or SAP authorizations." />
            </div>
          : <p className="ui-description">{matched?.unavailable_reason ?? 'Directory matching is unavailable.'}</p>}
        <InfoList label="Directory & Data Health">
          {list(d, ['email_matches', 'directory_missing', 'directory_ambiguous', 'position_changes']).map(m => row(m, m.id === 'email_matches' ? { label: 'Matched identities' } : m.id === 'position_changes' ? { label: 'Position changes' } : {}))}
        </InfoList>
      </>
    ), { tip: <><p>The percentage is the share of SAP users matched to the Employee Directory. It describes directory matching quality only, not the health of other data sources or any SAP authorization.</p><p>{MATCH_HEALTH_LEGEND} The percentage is always shown as text.</p><p>Position changes are independent of matching and never change the percentage.</p></> })
  }
  /** Segregation of Duties: shown only when the feature is enabled; never zero-filled when the analysis is unavailable. */
  /** Segregation of Duties: loading, failed, unavailable (with its real cause) and ready are different states; none is inferred from another. */
  const renderSod = () => {
    if (!sodEnabled) return null
    const note = 'Potential transaction-derived conflicts, not effective SAP authorization.'
    const g = sodSummary.data?.governance
    if (sodSummary.isError && !g) return card('Segregation of Duties', <ShieldAlert size={18}/>, (
      <div className="dashboard-card-state" role="alert">
        <p className="text-sm">SoD analysis could not be loaded.</p>
        <Button size="compact" onClick={() => void sodSummary.refetch()}><RefreshCw size={14} aria-hidden="true"/>Try again</Button>
      </div>
    ), { note })
    // Persisted data is still being restored, or the analysis has not answered yet: a temporary state, never a missing-data verdict.
    if (!g || (!g.available && loading)) return card('Segregation of Duties', <ShieldAlert size={18}/>, (
      <p className="dashboard-card-state ui-description" role="status"><Loader2 size={14} className="animate-spin" aria-hidden="true"/>Preparing SoD analysis…</p>
    ), { note })
    const pending = (g.activities?.Pending || 0) + (g.activities?.Outdated || 0) + (g.acceptance?.Pending || 0) + (g.acceptance?.Outdated || 0)
    if (g.available) return card('Segregation of Duties', <ShieldAlert size={18}/>, (
      <InfoList label="Segregation of Duties">
        <InfoRow icon={<ConflictUsers size={16} aria-hidden="true"/>} label="Users with potential conflicts" value={(g.users_with_conflicts ?? 0).toLocaleString()} tone={g.users_with_conflicts ? 'warning' : 'neutral'} onClick={() => openSod('risk-matrix')} navigates data={{ metric: 'sod_conflicts' }}/>
        <InfoRow icon={<ShieldAlert size={16} aria-hidden="true"/>} label="User-risk findings" value={(g.user_risk_findings ?? 0).toLocaleString()} onClick={() => openSod('risk-matrix')} navigates/>
        <InfoRow icon={<CircleDashed size={16} aria-hidden="true"/>} label="SoD reviews pending" value={pending.toLocaleString()} tone={pending ? 'warning' : 'neutral'} onClick={() => openSod('reviews')} navigates/>
        <InfoRow icon={<ShieldCheck size={16} aria-hidden="true"/>} label="Open remediation actions" value={(g.remediation?.open_actions ?? 0).toLocaleString()} onClick={() => openSod('reviews')} navigates/>
        <InfoRow icon={<AlertTriangle size={16} aria-hidden="true"/>} label="Overdue remediation actions" value={(g.remediation?.overdue ?? 0).toLocaleString()} tone={g.remediation?.overdue ? 'error' : 'neutral'} onClick={() => openSod('reviews')} navigates/>
      </InfoList>
    ), { note })
    const names: Record<string, { label: string; target: 'roles' | 'users' | 'sod' }> = { roles: { label: 'Role Catalogue', target: 'roles' }, users: { label: 'User Access', target: 'users' }, sod: { label: 'SoD matrix', target: 'sod' } }
    const missing = (g.missing ?? []).filter(key => names[key]), first = names[missing[0] ?? 'sod']
    const cause = g.reason === 'mapping_disabled' ? 'User–Role Mapping is disabled.' : g.reason === 'sod_disabled' ? 'The SoD feature is disabled.'
      : missing.length ? `The ${missing.map(key => names[key].label).join(', ')} ${missing.length === 1 ? 'is' : 'are'} not loaded.` : 'A supported SoD matrix and a validated role catalogue are required.'
    return card('Segregation of Duties', <ShieldAlert size={18}/>, (
      <div className="dashboard-card-state">
        <p className="text-sm text-[var(--muted)]">SoD analysis is not available. {cause}</p>
        {g.reason !== 'sod_disabled' && <Button size="compact" onClick={() => change({ settings: true, settingsTarget: first.target })}><Database size={14} aria-hidden="true"/>Open {first.label === 'SoD matrix' ? 'SoD' : first.label} source</Button>}
      </div>
    ), { note })
  }
  const renderRoleDistribution = (d: DashboardData) => {
    const entries = d.role_distribution ? Object.entries(d.role_distribution).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])) : []
    const scale = Math.max(1, ...entries.map(([, count]) => count)), roleTotal = entries.reduce((sum, [, count]) => sum + count, 0)
    const datum = ([area, count]: [string, number]) => ({
      key: area, label: <ModuleBadge moduleId={area} variant="compact" showUnclassified/>, value: count, note: roleTotal ? `${Math.round((count / roleTotal) * 100)}%` : undefined,
      title: `${modules.data?.find(module => module.function_key === area)?.module_name || area}: ${count} catalogue roles${roleTotal ? ` (${((count / roleTotal) * 100).toFixed(1)}% of ${roleTotal})` : ''}`,
      ariaLabel: `Investigate ${area} catalogue roles`, onOpen: () => { setAllAreas(false); const metric = metricOf(d, 'roles'); if (metric) open(metric, area) } })
    return card('Role Distribution', <BarChart3 size={18}/>, d.role_distribution == null ? <p>Role catalogue unavailable.</p> : (
      <>
        <BarChart label="Catalogue roles by SAP area" max={scale} data={entries.slice(0, 5).map(datum)} />
        {entries.length > 5 && <Button size="compact" aria-haspopup="dialog" onClick={() => setAllAreas(true)}>Show all {entries.length} areas</Button>}
        {allAreas && <Dialog title="Role Distribution by SAP area" onClose={() => setAllAreas(false)}>
          <p className="ui-description">Distinct catalogue roles by canonical SAP area. Select an area to investigate its roles.</p>
          <BarChart label="Catalogue roles by SAP area (all areas)" max={scale} data={entries.map(datum)} />
        </Dialog>}
      </>
    ), { tip: <p>Distinct catalogue roles by canonical SAP area. Single-role relationships and release assignments are separate evidence.</p> })
  }
  /** Assignment Distribution: five non-overlapping ranges that together cover every applicable SAP user (zero roles included). */
  const renderAssignmentDistribution = (d: DashboardData) => {
    const counts = ASSIGNMENT_BANDS.map(band => d.assignment_distribution?.[band] || 0), total = counts.reduce((sum, count) => sum + count, 0)
    return card('Assignment Distribution', <UsersRound size={18}/>, d.assignment_distribution ? (
      <BarChart label="Users by currently valid role count" data={ASSIGNMENT_BANDS.map((band, index) => ({
        key: band, label: `${band} roles`, value: counts[index], note: total ? `${Math.round((counts[index] / total) * 100)}%` : undefined,
        title: `${counts[index]} users with ${band} currently valid roles${total ? ` (${((counts[index] / total) * 100).toFixed(1)}% of ${total} SAP users)` : ''}`,
        ariaLabel: `Investigate users with ${band} currently valid roles`, onOpen: () => change({ page: 'users', accessMode: 'directory', user: '', userContext: {}, assignmentBand: band, settings: false, detailRole: null }) }))} />
    ) : <p>User–Role Mapping unavailable.</p>, { tip: <><p>SAP users by the number of distinct currently valid assigned roles. Users without any valid role are in the first range; every user is counted once.</p><p>Historical and unknown intervals are excluded. High counts are not security findings.</p></> })
  }
  /** Data Sources & Configuration: one compact card per relevant source with its honest load state. */
  const renderSources = (d: DashboardData) => {
    const relevant = (sourceEvidence.data?.sources ?? []).filter(source => source.enabled !== false || source.configured)
    const records = (source: NonNullable<typeof sourceEvidence.data>['sources'][number]) => {
      if (source.records === undefined) return null
      const count = (value: number, unit: string) => `${value.toLocaleString()} ${unit}`
      return source.id === 'roles' ? count(source.records, source.records === 1 ? 'composite role' : 'composite roles')
        : source.id === 'users' ? `${count(source.records, source.records === 1 ? 'user' : 'users')} · ${count(source.assignments ?? 0, 'assignment records')}`
        : source.id === 'sod' ? count(source.records, 'matrix records') : count(source.records, 'directory records')
    }
    return (
      <section key="sources" aria-label="Data Sources & Configuration" className="dashboard-section dashboard-sources-section">
        <SectionHeader title="Data Sources & Configuration" icon={<SlidersHorizontal size={18}/>}/>
        <p className="text-xs text-[var(--muted)]">Last successful refresh: {formatTimestamp(d.last_successful_refresh)}</p>
        {d.source_warning && <p role="status" className="text-sm text-[var(--warning)]">{d.source_warning}</p>}
        {sourceEvidence.isError ? <p role="alert" className="text-sm">Source status could not be checked.</p> : !sourceEvidence.data ? <p role="status" className="ui-description">Checking source status…</p> : (
          <ul className="dashboard-sources" aria-label="Data sources">
            {relevant.map(source => {
              const state = sourceState(source), line = records(source)
              return (
                <li key={source.id}>
                  <button type="button" className="dashboard-source" data-state={state.key} data-source={source.id} aria-label={`${SOURCE_NAMES[source.id] ?? source.name}: ${state.label}. Open source settings`} onClick={() => change({ settings: true, settingsTarget: source.id as 'roles' | 'users' | 'employees' | 'sod' })}>
                    <span className="dashboard-source-head"><Database size={16} aria-hidden="true"/><strong>{SOURCE_NAMES[source.id] ?? source.name}</strong><ArrowUpRight size={14} aria-hidden="true" className="dashboard-source-arrow"/></span>
                    <span className="dashboard-source-badges">
                      <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
                      {source.mode && <StatusBadge tone={source.mode === 'static' ? 'neutral' : 'accent'}>{source.mode === 'static' ? 'Static' : 'Dynamic'}</StatusBadge>}
                    </span>
                    {state.key !== 'not_configured' && <span className="dashboard-source-meta">{line ?? 'No records'}</span>}
                    <span className="dashboard-source-meta">{source.last_successful_load ? `Last import ${formatTimestamp(source.last_successful_load)}` : 'No successful import'}</span>
                    {state.detail && <span className="dashboard-source-meta" data-tone={state.tone}>{state.detail}</span>}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    )
  }
  // Reading and keyboard order follow DASHBOARD_CARDS; the grid only wraps columns.
  const cards: Record<DashboardCard, (d: DashboardData) => ReactNode> = {
    'access-risk': renderAccessRisk,
    'review-progress': renderReviewProgress,
    'directory-health': renderDirectory,
    sod: renderSod,
    'role-distribution': renderRoleDistribution,
    'assignment-distribution': renderAssignmentDistribution,
  }
  return (
    <section aria-label="Dashboard" className="space-y-5">
      <PageHeader title="Dashboard" icon={<LayoutDashboard size={22} aria-hidden="true"/>}/>
      <p className="ui-description">Current validated SAP data and available capabilities.</p>
      <DataLifecycleStatus state={lifecycle} validatedAt={query.data?.last_successful_refresh} warning={query.data?.source_warning} onConfigure={()=>change({settings:true,settingsTarget:'roles'})}/>
      {query.data && (
        <div className="dashboard-workspace">
          <div className="dashboard-cards">
            {DASHBOARD_CARDS.map(id => <Fragment key={id}>{cards[id](query.data!)}</Fragment>)}
            {renderSources(query.data)}
          </div>
        </div>
      )}
    </section>
  )
}
