import { formatTimestamp } from '@/lib/dateFormat'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  ClipboardCheck,
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
        last_successful_refresh?: string | null
        source_warning?: string | null
        notice: string
      }>('/api/dashboard'),
  })
  const open = (metric: Metric) =>
    metric.destination === 'review'
      ? change({
          page: 'users',
          accessMode: 'review',
          user: '',
          reviewFinding:
            metric.id === 'unresolved'
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
            ...(metric.destination === 'roles' ? { comparison: false } : {}),
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
    ['Overview', ['users', 'roles', 'releases', 'mappings']],
    ['User Access', ['assignments', 'assigned_users', 'account_review']],
    ['Access Lifecycle', ['expired', 'future']],
    ['Data Quality', ['email_matches', 'unresolved']],
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
          available; review Health &amp; Diagnostics.
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
                  .sort(
                    (a, b) =>
                      (ids as readonly string[]).indexOf(a.id) -
                      (ids as readonly string[]).indexOf(b.id),
                  )
                  .map(tile)}
              </div>
              {name === 'Data Quality' && !!query.data.coverage_total && (
                <section
                  className="coverage-summary"
                  aria-label="Directory match percentage"
                >
                  <strong>
                    {(
                      ((query.data.metrics.find((m) => m.id === 'email_matches')
                        ?.value || 0) /
                        query.data.coverage_total) *
                      100
                    ).toFixed(1)}
                    % matched
                  </strong>
                  <progress
                    aria-label="SAP identity match coverage"
                    max={query.data.coverage_total}
                    value={
                      query.data.metrics.find((m) => m.id === 'email_matches')
                        ?.value || 0
                    }
                  />
                  <span>
                    {query.data.metrics.find((m) => m.id === 'email_matches')
                      ?.value || 0}{' '}
                    of {query.data.coverage_total} SAP identities
                  </span>
                </section>
              )}
              {name === 'Access Lifecycle' && (
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
