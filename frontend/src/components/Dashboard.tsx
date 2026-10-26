import {useModules} from '@/hooks/useModules'
import {SourceHealthSummary,useSourceEvidence} from '@/components/Settings/SourceStatus'
import { PageHeader, SectionHeader } from '@/components/Shared/Presentation'
import { LayoutDashboard, ShieldAlert, HeartPulse, BarChart3, SlidersHorizontal } from 'lucide-react'
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
} from 'lucide-react'
import { apiRequest } from '@/api/client'
import { useViewHistory } from '@/hooks/useViewHistory'
import { useApplicationData } from '@/state/ApplicationData'
import { StatusPill } from '@/components/Shared/StatusPill'
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
  const open = (metric: Metric, area='') =>
    metric.destination === 'review'
      ? change({
          page: 'users',
          accessMode: 'review',
          accountReviewFilters:{search:'',license:'',state:'',sort:'username',descending:false},
          kpiNavigation:{...view.kpiNavigation,users:(view.kpiNavigation?.users||0)+1},
          user: '',
          reviewFinding:
            metric.id==='outdated'?'stale':metric.id==='reviewed'?'reviewed':metric.id==='pending'?'pending':metric.id==='ad_disabled_open'?'ad_disabled_open':metric.id === 'unresolved'
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
              ? 'Loading…'
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
  const modules=useModules()
  const groups = [
    ['SAP Overview', ['users', 'roles', 'releases', 'mappings']],
    ['Access & Risk', ['account_review','ad_disabled_open','expired','future','assignments','assigned_users']],
    ['Directory & Data Health', ['email_matches','unresolved']],
    ['Review Progress',['reviewed','pending','outdated']],
  ] as const
  return (
    <section aria-label="Dashboard" className="space-y-5">
      <PageHeader title="Dashboard" icon={<LayoutDashboard size={22} aria-hidden="true"/>}>{loading&&<span role="status" className="evidence-badge evidence-info">Updating data…</span>}</PageHeader>
      <p className="ui-description">Current validated SAP data and available capabilities.</p>
      {query.isLoading && <p role="status">Loading overview…</p>}
      {query.isError && (
        <p role="alert">
          Overview could not be refreshed. Previously loaded data remains
          available; review Health &amp; Diagnostics.
        </p>
      )}
      {query.data && (
        <div className="dashboard-workspace">
          {groups.map(([name, ids]) => (
            <section key={name} aria-label={name} className={`dashboard-section ${name==='SAP Overview'?'':'dashboard-middle-section'}`}>
              <SectionHeader title={name} icon={name==='SAP Overview'?<Database size={18}/>:name==='Access & Risk'?<ShieldAlert size={18}/>:name==='Review Progress'?<ClipboardCheck size={18}/>:<HeartPulse size={18}/>}/>
              <div className={`dashboard-metrics ${name === 'SAP Overview' ? 'dashboard-primary-metrics' : 'dashboard-secondary-metrics'}`}>
                {query.data.metrics
                  .filter((m) => (ids as readonly string[]).includes(m.id))
                  .sort(
                    (a, b) =>
                      (ids as readonly string[]).indexOf(a.id) -
                      (ids as readonly string[]).indexOf(b.id),
                  )
                  .map(tile)}
              </div>
              {name==='Review Progress'&&query.data.review_population!=null&&query.data.metrics.find(m=>m.id==='reviewed')?.value!=null&&<div className="coverage-summary"><strong>{query.data.review_population ? (((query.data.metrics.find(m=>m.id==='reviewed')?.value||0)/query.data.review_population)*100).toFixed(1):'0.0'}% reviewed</strong><progress aria-label="Account review completion" max={query.data.review_population||1} value={query.data.metrics.find(m=>m.id==='reviewed')?.value||0}/><small>All {query.data.review_population} imported SAP accounts; outdated reviews remain pending.</small></div>}
              {name === 'Access & Risk' && (
                <p className="text-xs text-[var(--muted)]">
                  Counts describe source evidence, not effective SAP authorization.
                </p>
              )}
            </section>
          ))}

          <div className="dashboard-bottom-row"><section aria-label="Role Distribution" className="dashboard-section dashboard-distribution"><SectionHeader title="Role Distribution" icon={<BarChart3 size={18}/>}/><p className="ui-description">Distinct catalogue roles by canonical SAP area. Single-role relationships and release assignments are separate evidence.</p>{query.data.role_distribution==null?<p>Role catalogue unavailable.</p>:Object.entries(query.data.role_distribution).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([area,count])=><button key={area} className="dashboard-distribution-link" title={modules.data?.find(module=>module.function_key===area)?.module_name||area} aria-label={`Investigate ${area} catalogue roles`} onClick={()=>{const metric=query.data.metrics.find(m=>m.id==='roles');if(metric)open(metric,area)}}><span>{area}</span><progress aria-label={`${area} catalogue roles`} max={Math.max(1,...Object.values(query.data.role_distribution||{}))} value={count}/><strong>{count}</strong><ArrowUpRight size={14}/></button>)}</section>
          <section aria-label="Configuration" className="dashboard-section">
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
          </section><section aria-label="Assignment Distribution" className="dashboard-section dashboard-distribution"><SectionHeader title="Assignment Distribution" icon={<UsersRound size={18}/>}/><p className="ui-description">Distinct currently valid assigned roles. Historical and unknown intervals are excluded. High counts are not security findings.</p>{query.data.assignment_distribution?['0','1–5','6–20','21+'].map(bin=><button key={bin} className="dashboard-distribution-stat" aria-label={`Investigate users with ${bin} currently valid roles`} onClick={()=>change({page:'users',accessMode:'directory',user:'',userContext:{},assignmentBand:bin,settings:false,detailRole:null})}><span>{bin} roles</span><progress aria-label={`${bin} roles user count`} max={Math.max(1,...Object.values(query.data.assignment_distribution||{}))} value={query.data.assignment_distribution?.[bin]||0}/><strong>{query.data.assignment_distribution?.[bin]||0}</strong></button>):<p>User–Role Mapping unavailable.</p>}
          </section></div>
        </div>
      )}
    </section>
  )
}
