import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  BookUser,
  Database,
  UsersRound,
  Network,
  FileCheck2,
  CalendarDays,
  MailCheck,
  Settings2,
} from 'lucide-react'
import { apiRequest } from '@/api/client'
import { useViewHistory } from '@/hooks/useViewHistory'
import { useApplicationData } from '@/state/ApplicationData'
import { StatusPill } from '@/components/Shared/StatusPill'
interface Metric {
  id: string
  label: string
  value: number | null
  destination: 'roles' | 'users' | 'releases' | 'employees'
  context: string
  unavailable_reason: string | null
}
interface Source {
  id: 'roles' | 'users' | 'employees'
  name: string
  enabled: boolean
  configured: boolean
  available: boolean
}
export function Dashboard() {
  const { view, change } = useViewHistory(),
    { loading } = useApplicationData()
  const query = useQuery({
    queryKey: ['dashboard'],
    queryFn: () =>
      apiRequest<{
        metrics: Metric[]
        sources?: Source[]
        coverage_total?: number
        notice: string
      }>('/api/dashboard'),
  })
  const open = (metric: Metric) =>
    metric.destination === 'employees'
      ? change({ settings: true, settingsTarget: 'employees' })
      : change({
          page: metric.destination,
          kpiNavigation: {
            ...view.kpiNavigation,
            [metric.destination]:
              (view.kpiNavigation?.[metric.destination] || 0) + 1,
          },
          ...(metric.destination === 'users'
            ? { user: '', userContext: {} }
            : {}),
          ...(metric.destination === 'releases' ? { release: null } : {}),
          ...(metric.destination === 'roles' ? { comparison: false } : {}),
          detailRole: null,
          settings: false,
        })
  const tile = (metric: Metric) => {
    const Icon =
      metric.id === 'areas'
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
        className="dashboard-metric"
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
            : metric.value.toLocaleString()}
        </strong>
        <ArrowUpRight size={14} aria-hidden="true" />
        {metric.value === null && <small>{metric.unavailable_reason}</small>}
        <span className="sr-only">{metric.context}</span>
        {metric.id === 'email_matches' &&
          metric.value !== null &&
          !!query.data?.coverage_total && (
            <small>
              of {query.data.coverage_total.toLocaleString()} SAP identities
            </small>
          )}
      </button>
    )
  }
  const groups = [
    ['Overview', ['roles', 'areas', 'mappings']],
    ['User Access', ['users', 'assignments', 'assigned_users', 'releases']],
    ['Data Quality', ['email_matches', 'unresolved', 'expired', 'future']],
  ] as const
  return (
    <section aria-label="Dashboard" className="space-y-5">
      <header className="dashboard-heading">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="text-sm text-[var(--muted)]">
            Current validated SAP data and available capabilities.
          </p>
        </div>
        {loading && (
          <span role="status" className="evidence-badge evidence-info">
            Updating data…
          </span>
        )}
      </header>
      {query.isLoading && <p role="status">Loading overview…</p>}
      {query.isError && (
        <p role="alert">
          Overview could not be refreshed. Previously loaded data remains
          available; review Application &amp; Diagnostics.
        </p>
      )}
      {query.data && (
        <>
          {groups.map(([name, ids]) => (
            <section key={name} aria-label={name} className="dashboard-section">
              <h2>{name}</h2>
              <div className="dashboard-metrics">
                {query.data.metrics
                  .filter((m) => (ids as readonly string[]).includes(m.id))
                  .map(tile)}
              </div>
              {name === 'Data Quality' && (
                <p className="text-xs text-[var(--muted)]">
                  Expired/future totals open User Access; select assignment
                  status in a profile. Release Roles opens its currently-valid
                  view. Counts describe source evidence, not effective SAP
                  authorization.
                </p>
              )}
            </section>
          ))}
          <section aria-label="Configuration" className="dashboard-section">
            <h2>
              <Settings2 size={17} aria-hidden="true" />
              Configuration
            </h2>
            <div className="dashboard-sources">
              {query.data.sources
                ?.filter((source) => source.id !== 'employees')
                .map((source) => (
                  <button
                    key={source.id}
                    className="dashboard-source"
                    aria-label={`Configure ${source.name}`}
                    onClick={() =>
                      change({ settings: true, settingsTarget: source.id })
                    }
                  >
                    <Database size={18} aria-hidden="true" />
                    <span>
                      <strong>{source.name}</strong>
                      <small>
                        {source.configured
                          ? 'Source configured'
                          : 'Setup required'}{' '}
                        ·{' '}
                        {source.available
                          ? 'Data available'
                          : loading
                            ? 'Loading…'
                            : 'No data available'}
                      </small>
                    </span>
                    <StatusPill enabled={source.enabled} />
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </button>
                ))}
              {query.data.metrics
                .filter((m) => m.id === 'employees')
                .map((metric) => (
                  <button
                    key={metric.id}
                    className="dashboard-source"
                    aria-label={metric.label}
                    onClick={() => open(metric)}
                  >
                    <BookUser size={18} aria-hidden="true" />
                    <span>
                      <strong>{metric.label}</strong>
                      <small>
                        {metric.value === null
                          ? metric.unavailable_reason
                          : `${metric.value.toLocaleString()} imported records`}
                      </small>
                    </span>
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </button>
                ))}
            </div>
          </section>
        </>
      )}
    </section>
  )
}
