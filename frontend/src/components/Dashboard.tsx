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
import { MetricTile } from '@/components/Shared/MetricTile'
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
          accountReviewFilters:{search:'',license:'',state:'',sort:'username',descending:false},
          kpiNavigation:{...view.kpiNavigation,users:(view.kpiNavigation?.users||0)+1},
          user: '',
          reviewFinding:
            metric.id==='outdated'?'stale':metric.id==='position_changes'?'position_change':metric.id==='reviewed'?'reviewed':metric.id==='pending'?'pending':metric.id==='ad_disabled_open'?'ad_disabled_open':metric.id === 'unresolved'
              ? 'directory_match'
              : metric.id === 'email_matches'
                ? 'matched'
                : 'any',
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
  const tile = (metric: Metric) => {
    const Icon =
      metric.id === 'account_review'
        ? ClipboardCheck
        : metric.id === 'position_changes'
          ? UserCog
        : metric.id === 'areas'
          ? Network
          : metric.id === 'releases'
            ? FileCheck2
            : metric.id === 'expired' || metric.id === 'future'
              ? CalendarDays
              : metric.id.includes('match') || metric.id === 'unresolved'
                ? MailCheck
                : metric.destination === 'users'
                  ? UsersRound
                  : Database
    return (
      <button
        key={metric.id}
        className="dashboard-metric" data-metric={metric.id} data-tone={metric.id==='account_review'&&!!metric.value?'warning':'neutral'}
        aria-label={metric.label}
        title={metric.context}
        onClick={() => open(metric)}
      >
        <Icon size={18} aria-hidden="true" />
        <span className="dashboard-metric-label">{metric.label}</span>
        <strong>
          {metric.value === null
            ? loading &&
              !metric.unavailable_reason?.toLowerCase().includes('disabled')
              ? <><span className="dashboard-skeleton" aria-hidden="true"/><span className="sr-only">Loading</span></>
              : 'Unavailable'
            : metric.id==='email_matches'&&query.data?.coverage_total?`${metric.value.toLocaleString()} / ${query.data.coverage_total.toLocaleString()}`:metric.value.toLocaleString()}
        </strong>
        <ArrowUpRight size={14} aria-hidden="true" />
        {metric.value === null && <small>{metric.unavailable_reason}</small>}
        <span className="sr-only">{metric.context}</span>


        {metric.id==='email_matches'&&metric.value!==null&&!!query.data?.coverage_total&&<><small>{((metric.value/query.data.coverage_total)*100).toFixed(1)}% matched</small><progress aria-label="SAP identity match coverage" max={query.data.coverage_total} value={metric.value}/></>}

      </button>
    )
  }
  const [allAreas,setAllAreas]=useState(false)
  const modules=useModules()
  const groups = [
    ['SAP Overview', ['users', 'roles', 'releases', 'mappings']],
    ['Access & Risk', ['account_review','position_changes','ad_disabled_open','expired','future','assignments','assigned_users']],
    ['Directory & Data Health', ['email_matches','unresolved']],
    ['Review Progress',['reviewed','pending','outdated']],
  ] as const
  const lifecycle = dashboardLifecycle({
    fetching: query.isLoading,
    failed: query.isError || !!query.data?.source_warning,
    loading,
    hasValidatedData: !!query.data?.metrics.some(metric => metric.value !== null),
    hasEnabledSource: !query.data?.sources || query.data.sources.some(source => source.configured && source.enabled),
  })
  const renderGroup = (d: DashboardData, name: string, ids: readonly string[]) => (
            <section key={name} aria-label={name} className={`dashboard-section ${name==='SAP Overview'?'':'dashboard-middle-section'}`}>
              <SectionHeader title={name} icon={name==='SAP Overview'?<Database size={18}/>:name==='Access & Risk'?<ShieldAlert size={18}/>:name==='Review Progress'?<ClipboardCheck size={18}/>:<HeartPulse size={18}/>}/>
              <div className={`dashboard-metrics ${name === 'SAP Overview' ? 'dashboard-primary-metrics' : 'dashboard-secondary-metrics'}`}>
                {d.metrics
                  .filter((m) => (ids as readonly string[]).includes(m.id))
                  .sort(
                    (a, b) =>
                      (ids as readonly string[]).indexOf(a.id) -
                      (ids as readonly string[]).indexOf(b.id),
                  )
                  .map(tile)}
              </div>
              {name==='Review Progress'&&d.review_population!=null&&d.metrics.find(m=>m.id==='reviewed')?.value!=null&&<div className="coverage-summary"><strong>{d.review_population ? (((d.metrics.find(m=>m.id==='reviewed')?.value||0)/d.review_population)*100).toFixed(1):'0.0'}% reviewed</strong><progress aria-label="Account review completion" max={d.review_population||1} value={d.metrics.find(m=>m.id==='reviewed')?.value||0}/><small>All {d.review_population} imported SAP accounts; outdated reviews remain pending.</small></div>}
              {name === 'Access & Risk' && (
                <p className="text-xs text-[var(--muted)]">
                  Counts describe source evidence, not effective SAP authorization.
                </p>
              )}
            </section>

  )
  const renderSod = () => {
    if (!(sodEnabled && sodSummary.data)) return null
            const g=sodSummary.data.governance,pending=(g.activities?.Pending||0)+(g.activities?.Outdated||0)+(g.acceptance?.Pending||0)+(g.acceptance?.Outdated||0)
            return <section aria-label="Segregation of Duties" className="dashboard-section min-w-0 rounded-card bg-surface p-4">
              <SectionHeader title="Segregation of Duties" icon={<ShieldAlert size={18}/>}/>
              {g.available
                ? <div className="dashboard-metrics dashboard-secondary-metrics">
                    <MetricTile icon={<ConflictUsers size={18} aria-hidden="true"/>} label="Users with potential conflicts" value={g.users_with_conflicts} onOpen={()=>openSod('risk-matrix')}/>
                    <MetricTile icon={<ShieldAlert size={18} aria-hidden="true"/>} label="User-risk findings" value={g.user_risk_findings} onOpen={()=>openSod('risk-matrix')}/>
                    <MetricTile icon={<CircleDashed size={18} aria-hidden="true"/>} label="SoD reviews pending" value={pending} onOpen={()=>openSod('reviews')}/>
                    <MetricTile icon={<ShieldCheck size={18} aria-hidden="true"/>} label="Open remediation actions" value={g.remediation?.open_actions} onOpen={()=>openSod('reviews')}/>
                    <MetricTile icon={<AlertTriangle size={18} aria-hidden="true"/>} label="Overdue remediation actions" value={g.remediation?.overdue} tone="error" onOpen={()=>openSod('reviews')}/>
                  </div>
                : <p className="text-sm text-[var(--muted)]">SoD analysis is not available ({g.reason==='mapping_disabled'?'User–Role Mapping is disabled':'a supported SoD matrix and validated role catalogue are required'}). <Button variant="ghost" onClick={()=>openSod('overview')}>Open SoD</Button></p>}
              <p className="text-xs text-[var(--muted)]">Potential transaction-derived conflicts, not effective SAP authorization.</p>
            </section>
  }
  const renderRoleDistribution = (d: DashboardData) => (
    <section aria-label="Role Distribution" className="dashboard-section dashboard-distribution min-w-0 rounded-card bg-surface p-4"><SectionHeader title="Role Distribution" icon={<BarChart3 size={18}/>}/><p className="ui-description">Distinct catalogue roles by canonical SAP area. Single-role relationships and release assignments are separate evidence.</p><div className="grid gap-0">{d.role_distribution==null?<p>Role catalogue unavailable.</p>:Object.entries(d.role_distribution).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,allAreas?undefined:5).map(([area,count])=><button key={area} className="dashboard-distribution-link" title={modules.data?.find(module=>module.function_key===area)?.module_name||area} aria-label={`Investigate ${area} catalogue roles`} onClick={()=>{const metric=d.metrics.find(m=>m.id==='roles');if(metric)open(metric,area)}}><ModuleBadge moduleId={area} variant="compact" showUnclassified/><progress aria-label={`${area} catalogue roles`} max={Math.max(1,...Object.values(d.role_distribution||{}))} value={count}/><strong>{count}</strong><ArrowUpRight size={14}/></button>)}</div>{d.role_distribution&&Object.keys(d.role_distribution).length>5&&<Button size="compact" aria-expanded={allAreas} onClick={()=>setAllAreas(value=>!value)}>{allAreas?'Show less':'Show all'}</Button>}</section>
  )
  const renderAssignmentDistribution = (d: DashboardData) => (
    <section aria-label="Assignment Distribution" className="dashboard-section dashboard-distribution min-w-0 rounded-card bg-surface p-4"><SectionHeader title="Assignment Distribution" icon={<UsersRound size={18}/>}/><p className="ui-description">Distinct currently valid assigned roles. Historical and unknown intervals are excluded. High counts are not security findings.</p><div className="grid gap-0">{d.assignment_distribution?['1–5','6–20','21+'].map(bin=><button key={bin} className="dashboard-distribution-stat" aria-label={`Investigate users with ${bin} currently valid roles`} onClick={()=>change({page:'users',accessMode:'directory',user:'',userContext:{},assignmentBand:bin,settings:false,detailRole:null})}><span>{bin} roles</span><progress aria-label={`${bin} roles user count`} max={Math.max(1,...Object.values(d.assignment_distribution||{}))} value={d.assignment_distribution?.[bin]||0}/><strong>{d.assignment_distribution?.[bin]||0}</strong></button>):<p>User–Role Mapping unavailable.</p>}</div>
          </section>
  )
  // Reading and keyboard order follow DASHBOARD_CARDS; the grid only wraps columns.
  const cards: Record<DashboardCard, (d: DashboardData) => ReactNode> = {
    'access-risk': d => renderGroup(d, groups[1][0], groups[1][1]),
    sod: () => renderSod(),
    'directory-health': d => renderGroup(d, groups[2][0], groups[2][1]),
    'review-progress': d => renderGroup(d, groups[3][0], groups[3][1]),
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
          {renderGroup(query.data, 'SAP Overview', groups[0][1])}
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
