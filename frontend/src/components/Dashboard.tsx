import {Fragment,useState,type ReactNode} from 'react'
import {Button} from '@/components/Shared/Button'
import {useModules} from '@/hooks/useModules'
import {ModuleBadge} from '@/components/Modules/ModuleBadge'
import {SourceHealthSummary,useSourceEvidence} from '@/components/Settings/SourceStatus'
import { PageHeader, SectionHeader } from '@/components/Shared/Presentation'
import { AlertTriangle, Loader2, CircleDashed, LayoutDashboard, ShieldAlert, ShieldCheck, HeartPulse, BarChart3, SlidersHorizontal, UsersRound as ConflictUsers } from 'lucide-react'
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
import { StatusPill } from '@/components/Shared/StatusPill'
import { Kpi } from '@/components/Shared/Kpi'
import { InfoList, InfoRow } from '@/components/Shared/InfoList'
import { BarChart, StackedBar } from '@/components/Shared/Charts'
import { fetchConfiguration } from '@/api/configuration'
/** Cards below SAP Overview, in reading order. Reordering this list reorders the rendered elements. */
export const DASHBOARD_CARDS = ['access-risk', 'sod', 'directory-health', 'review-progress', 'role-distribution', 'assignment-distribution'] as const
type DashboardCard = (typeof DASHBOARD_CARDS)[number]
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
      <Button size="compact" onClick={onConfigure}>Configure data sources</Button>
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
  const sodSummary=useQuery({queryKey:['sod-overview'],enabled:sodEnabled,queryFn:()=>apiRequest<{governance:{available:boolean;reason?:string|null;users_with_conflicts?:number;user_risk_findings?:number;activities?:Record<string,number>;acceptance?:Record<string,number>;remediation?:{open_actions:number;overdue:number}}}>('/api/sod/overview')})
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
            metric.id==='outdated'?'stale':metric.id==='position_changes'?'position_change':metric.id==='reviewed'?'reviewed':metric.id==='pending'?'pending':metric.id==='ad_disabled_open'?'ad_disabled_open':metric.id === 'unresolved'
              ? 'directory_match'
              : metric.id === 'email_matches'
                ? 'matched'
                : 'any'],
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
  /** Prominent figure for the KPI row. */
  const tile = (metric: Metric) => {
    const Icon = iconFor(metric), { unavailable, value } = present(metric)
    return <Kpi key={metric.id} layout="expanded" icon={<Icon size={18} aria-hidden="true" />} label={metric.label} value={value} ariaLabel={metric.label} title={metric.context}
      tone={metric.id === 'account_review' && !!metric.value ? 'warning' : 'neutral'} data={{ metric: metric.id }} note={unavailable ? metric.unavailable_reason : undefined} onClick={() => open(metric)} navigates />
  }
  /** Secondary operational fact for an information list. */
  const row = (metric: Metric, coverageTotal = 0) => {
    const Icon = iconFor(metric), { unavailable, value } = present(metric, coverageTotal)
    return <InfoRow key={metric.id} icon={<Icon size={16} aria-hidden="true" />} label={metric.label} ariaLabel={metric.label} title={metric.context} value={value} data={{ metric: metric.id }}
      tone={['unresolved', 'outdated'].includes(metric.id) && !!metric.value ? 'warning' : 'neutral'}
      note={unavailable ? metric.unavailable_reason : coverageTotal && metric.value !== null ? `${((metric.value / coverageTotal) * 100).toFixed(1)}% matched` : undefined}
      progress={coverageTotal && metric.value !== null ? { value: metric.value, max: coverageTotal, label: 'SAP identity match coverage' } : undefined} onClick={() => open(metric)} navigates />
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
  /** Key figures: the few numbers that drive decisions. Each opens the relevant view with its filter applied. */
  const renderKeyFigures = (d: DashboardData) => {
    const g = sodEnabled ? sodSummary.data?.governance : undefined
    const users = metricOf(d, 'users'), review = metricOf(d, 'account_review'), reviewed = metricOf(d, 'reviewed'), pending = metricOf(d, 'pending')
    const population = d.review_population, done = reviewed?.value
    const percent = population && done != null ? (done / population) * 100 : null
    return (
      <section key="key-figures" aria-label="Key figures" className="dashboard-section dashboard-key-figures">
        <h2 className="sr-only">Key figures</h2>
        <div className="dashboard-key-grid">
          {users && tile(users)}
          {review && tile(review)}
          {sodEnabled && sodSummary.data && <Kpi layout="expanded" icon={<ConflictUsers size={18} aria-hidden="true"/>} label="Users with potential conflicts" ariaLabel="Users with potential conflicts" value={g?.available ? (g.users_with_conflicts ?? 0).toLocaleString() : 'Unavailable'} tone={g?.available && g.users_with_conflicts ? 'warning' : 'neutral'} note={g?.available ? 'Segregation of Duties' : 'SoD analysis unavailable'} onClick={() => openSod('risk-matrix')} navigates data={{ metric: 'sod_conflicts' }}/>}
          {pending && <Kpi layout="expanded" icon={<ClipboardCheck size={18} aria-hidden="true"/>} label="Review completion" ariaLabel="Review completion" title="Share of imported SAP accounts with a current completed review. Opens the accounts still pending." data={{ metric: 'review_completion' }}
            value={percent === null ? 'Unavailable' : `${percent.toFixed(1)}%`} note={percent === null ? 'Review population unavailable' : `${(done ?? 0).toLocaleString()} of ${population!.toLocaleString()} accounts`}
            progress={percent === null ? undefined : { value: done ?? 0, max: population!, label: 'Account review completion' }} onClick={() => open(pending)} navigates />}
        </div>
      </section>
    )
  }
  const infoCard = (name: string, icon: ReactNode, children: ReactNode, note?: string) => (
    <section key={name} aria-label={name} className="dashboard-section dashboard-middle-section">
      <SectionHeader title={name} icon={icon}/>
      <InfoList label={name}>{children}</InfoList>
      {note && <p className="text-xs text-[var(--muted)]">{note}</p>}
    </section>
  )
  const renderAccessRisk = (d: DashboardData) => infoCard('Access & Risk', <ShieldAlert size={18}/>, list(d, ['position_changes', 'ad_disabled_open', 'expired', 'assignments', 'assigned_users', 'mappings', 'roles', 'releases']).map(m => row(m)), 'Counts describe source evidence, not effective SAP authorization.')
  const renderDirectory = (d: DashboardData) => infoCard('Directory & Data Health', <HeartPulse size={18}/>, <>{list(d, ['email_matches']).map(m => row(m, d.coverage_total || 0))}{list(d, ['unresolved']).map(m => row(m))}</>)
  const renderSod = (d: DashboardData) => {
    if (!(sodEnabled && sodSummary.data)) return null
    const g = sodSummary.data.governance, pending = (g.activities?.Pending || 0) + (g.activities?.Outdated || 0) + (g.acceptance?.Pending || 0) + (g.acceptance?.Outdated || 0)
    void d
    return <section key="sod" aria-label="Segregation of Duties" className="dashboard-section dashboard-middle-section">
      <SectionHeader title="Segregation of Duties" icon={<ShieldAlert size={18}/>}/>
      {g.available
        ? <InfoList label="Segregation of Duties">
            <InfoRow icon={<ShieldAlert size={16} aria-hidden="true"/>} label="User-risk findings" value={(g.user_risk_findings ?? 0).toLocaleString()} onClick={()=>openSod('risk-matrix')} navigates/>
            <InfoRow icon={<CircleDashed size={16} aria-hidden="true"/>} label="SoD reviews pending" value={pending.toLocaleString()} tone={pending ? 'warning' : 'neutral'} onClick={()=>openSod('reviews')} navigates/>
            <InfoRow icon={<ShieldCheck size={16} aria-hidden="true"/>} label="Open remediation actions" value={(g.remediation?.open_actions ?? 0).toLocaleString()} onClick={()=>openSod('reviews')} navigates/>
            <InfoRow icon={<AlertTriangle size={16} aria-hidden="true"/>} label="Overdue remediation actions" value={(g.remediation?.overdue ?? 0).toLocaleString()} tone={g.remediation?.overdue ? 'error' : 'neutral'} onClick={()=>openSod('reviews')} navigates/>
          </InfoList>
        : <p className="text-sm text-[var(--muted)]">SoD analysis is not available ({g.reason==='mapping_disabled'?'User–Role Mapping is disabled':'a supported SoD matrix and validated role catalogue are required'}). <Button variant="ghost" onClick={()=>change({settings:true,settingsTarget:g.reason==='mapping_disabled'?'features':'sod'})}>Review configuration</Button></p>}
      <p className="text-xs text-[var(--muted)]">Potential transaction-derived conflicts, not effective SAP authorization.</p>
    </section>
  }
  /** Review progress as one stacked bar: completed, pending and outdated are mutually exclusive parts of the imported SAP accounts. */
  const renderReviewProgress = (d: DashboardData) => {
    const reviewed = metricOf(d, 'reviewed'), pending = metricOf(d, 'pending'), outdated = metricOf(d, 'outdated')
    const ready = d.review_population != null && reviewed?.value != null && pending?.value != null && outdated?.value != null
    return <section key="review-progress" aria-label="Review Progress" className="dashboard-section dashboard-chart min-w-0 rounded-card bg-surface p-4">
      <SectionHeader title="Review Progress" icon={<ClipboardCheck size={18}/>}/>
      {ready
        ? <StackedBar label="Account review progress" total={d.review_population!} segments={[
            { key: 'completed', label: 'Completed reviews', value: reviewed!.value!, tone: 'success', onOpen: () => open(reviewed!) },
            { key: 'pending', label: 'Not yet reviewed', value: pending!.value! - outdated!.value!, tone: 'neutral', title: 'Accounts without a current decision (excluding outdated reviews)', onOpen: () => open(pending!) },
            { key: 'outdated', label: 'Outdated reviews', value: outdated!.value!, tone: 'warning', title: 'The decision was recorded against evidence that has since changed', onOpen: () => open(outdated!) },
          ]} caption={`All ${d.review_population!.toLocaleString()} imported SAP accounts. Outdated reviews are pending until reviewed again.`} />
        : <p className="ui-description">Review progress needs the User Access data and account-review annotations.</p>}
    </section>
  }
  const renderRoleDistribution = (d: DashboardData) => (
    <section key="role-distribution" aria-label="Role Distribution" className="dashboard-section dashboard-chart min-w-0 rounded-card bg-surface p-4">
      <SectionHeader title="Role Distribution" icon={<BarChart3 size={18}/>}/>
      <p className="ui-description">Distinct catalogue roles by canonical SAP area. Single-role relationships and release assignments are separate evidence.</p>
      {d.role_distribution == null ? <p>Role catalogue unavailable.</p> : <>
        <BarChart label="Catalogue roles by SAP area" data={Object.entries(d.role_distribution).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, allAreas ? undefined : 5).map(([area, count]) => ({
          key: area, label: <ModuleBadge moduleId={area} variant="compact" showUnclassified/>, value: count, title: `${modules.data?.find(module => module.function_key === area)?.module_name || area}: ${count} catalogue roles`,
          ariaLabel: `Investigate ${area} catalogue roles`, onOpen: () => { const metric = metricOf(d, 'roles'); if (metric) open(metric, area) } }))} />
        {Object.keys(d.role_distribution).length > 5 && <Button size="compact" aria-expanded={allAreas} onClick={() => setAllAreas(value => !value)}>{allAreas ? 'Show less' : 'Show all'}</Button>}
      </>}
    </section>
  )
  const renderAssignmentDistribution = (d: DashboardData) => (
    <section key="assignment-distribution" aria-label="Assignment Distribution" className="dashboard-section dashboard-chart min-w-0 rounded-card bg-surface p-4">
      <SectionHeader title="Assignment Distribution" icon={<UsersRound size={18}/>}/>
      <p className="ui-description">Users by the number of distinct currently valid assigned roles. Historical and unknown intervals are excluded. High counts are not security findings.</p>
      {d.assignment_distribution
        ? <BarChart label="Users by currently valid role count" data={['1–5', '6–20', '21+'].map(bin => ({ key: bin, label: `${bin} roles`, value: d.assignment_distribution?.[bin] || 0, title: `${d.assignment_distribution?.[bin] || 0} users with ${bin} currently valid roles`,
            ariaLabel: `Investigate users with ${bin} currently valid roles`, onOpen: () => change({ page: 'users', accessMode: 'directory', user: '', userContext: {}, assignmentBand: bin, settings: false, detailRole: null }) }))} />
        : <p>User–Role Mapping unavailable.</p>}
    </section>
  )
  // Reading and keyboard order follow DASHBOARD_CARDS; the grid only wraps columns.
  const cards: Record<DashboardCard, (d: DashboardData) => ReactNode> = {
    'access-risk': renderAccessRisk,
    sod: renderSod,
    'directory-health': renderDirectory,
    'review-progress': renderReviewProgress,
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
          {renderKeyFigures(query.data)}
          <div className="dashboard-cards">
            {DASHBOARD_CARDS.map(id => <Fragment key={id}>{cards[id](query.data!)}</Fragment>)}
          </div>
          <section aria-label="Configuration" className="dashboard-section col-span-full">
            <SectionHeader title="Data Sources & Configuration" icon={<SlidersHorizontal size={18}/>}/>
            <p className="text-xs text-[var(--muted)]">
              Last successful refresh:{' '}
              {formatTimestamp(query.data.last_successful_refresh)} · Enabled
              SAP areas:{' '}
              {query.data.metrics.find((m) => m.id === 'areas')?.value ??
                'Unavailable'}
            </p>
            {query.data.source_warning && (
              <p role="status" className="text-sm text-[var(--warning)]">
                {query.data.source_warning}
              </p>
            )}
            <div className="dashboard-sources">
              {query.data.sources
                ?.map((source) => (
                  <button
                    key={source.id}
                    className="dashboard-source"
                    aria-label={source.id==='employees'?'Employee Directory records':`Configure ${source.name}`}
                    onClick={() =>
                      change({ settings: true, settingsTarget: source.id })
                    }
                  >
                    <Database size={18} aria-hidden="true" />
                    <span>
                      <strong>{source.name}</strong>

                    </span>
                    {sourceEvidence.data?.sources.find(item=>item.id===source.id)&&<SourceHealthSummary compact includeSnapshot={false} source={sourceEvidence.data.sources.find(item=>item.id===source.id)!}/>}
                    <StatusPill enabled={source.enabled} />
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </button>
                ))}

            </div>
          </section>
        </div>
      )}
    </section>
  )
}
