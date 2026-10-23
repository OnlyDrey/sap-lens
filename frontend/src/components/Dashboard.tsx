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
} from 'lucide-react'
import { apiRequest } from '@/api/client'
import { useViewHistory } from '@/hooks/useViewHistory'
interface Metric {
  id: string
  label: string
  value: number | null
  destination: 'roles' | 'users' | 'releases' | 'employees'
  context: string
  unavailable_reason: string | null
}
export function Dashboard() {
  const { view, change } = useViewHistory()
  const query = useQuery({
    queryKey: ['dashboard'],
    queryFn: () =>
      apiRequest<{ metrics: Metric[]; notice: string }>('/api/dashboard'),
  })
  return (
    <section aria-label="Dashboard" className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <p className="text-sm text-[var(--muted)]">
        Validated local data and available capabilities. Metrics summarize
        imported snapshots, not effective SAP authorization.
      </p>
      {query.isLoading && <p role="status">Loading overview…</p>}
      {query.isError && (
        <p role="alert">
          Overview unavailable. Open Application &amp; Diagnostics to check the
          local service.
        </p>
      )}
      {query.data && (
        <>
          <div className="dashboard-grid">
            {query.data.metrics.map((metric) => {
              const Icon =
                metric.id === 'employees'
                  ? BookUser
                  : metric.id.includes('match') || metric.id === 'unresolved'
                    ? MailCheck
                    : metric.id === 'releases'
                      ? FileCheck2
                      : metric.id === 'expired' || metric.id === 'future'
                        ? CalendarDays
                        : metric.destination === 'users'
                          ? UsersRound
                          : metric.id === 'areas'
                            ? Network
                            : Database
              return (
                <button
                  key={metric.id}
                  className="dashboard-kpi information-card"
                  aria-label={metric.label}
                  onClick={() =>
                    metric.destination === 'employees'
                      ? change({ settings: true, settingsTarget: 'employees' })
                      : change({
                          page: metric.destination,
                          kpiNavigation:{...view.kpiNavigation,[metric.destination]:(view.kpiNavigation?.[metric.destination] || 0)+1},
                          user: '',
                          userContext: {},
                          release: null,
                          detailRole: null,
                          settings: false,
                        })
                  }
                >
                  <span className="flex items-center justify-between gap-2">
                    <Icon size={20} aria-hidden="true" />
                    <ArrowUpRight size={15} aria-hidden="true" />
                  </span>
                  <span className="text-sm font-semibold">{metric.label}</span>
                  <strong className="text-2xl">
                    {metric.value === null
                      ? 'Unavailable'
                      : metric.value.toLocaleString()}
                  </strong>
                  <span className="text-xs text-[var(--muted)]">
                    {metric.unavailable_reason || metric.context}
                  </span>
                </button>
              )
            })}
          </div>
          <p className="text-xs text-[var(--muted)]">{query.data.notice}</p>
        </>
      )}
    </section>
  )
}
