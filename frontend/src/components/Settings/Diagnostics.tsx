import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Download, FileText } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
interface Snapshot {
  version: string
  configuration_schema: number
  configuration_revision: number
  backend_status: string
  data_source: string
  application_directory: string
  cached_roles: number
  last_successful_load: string | null
  platform: string
}
export function Diagnostics({ native }: { native: boolean }) {
  const query = useQuery({
    queryKey: ['diagnostics'],
    queryFn: () => apiRequest<Snapshot>('/api/diagnostics'),
    refetchInterval: 5000
  })
  const [feedback, setFeedback] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const act = async (action: () => Promise<void>) => {
    setBusy(true)
    setFeedback(null)
    setFailed(false)
    try {
      await action()
    } catch {
      setFailed(true)
      setFeedback(
        'The action could not be completed. Check access to your application directory.'
      )
    } finally {
      setBusy(false)
    }
  }
  const exportReport = () =>
    act(async () => {
      if (window.pywebview?.api.export_diagnostics) {
        if (await window.pywebview.api.export_diagnostics(applicationToken()))
          setFeedback(
            'Diagnostics exported without source paths, organization details or file contents.'
          )
        return
      }
      const report = await apiRequest('/api/diagnostics/export')
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
          type: 'application/json'
        })
      )
      const link = document.createElement('a')
      link.href = url
      link.download = 'SAP-Lens-diagnostics.json'
      link.click()
      URL.revokeObjectURL(url)
      setFeedback(
        'Diagnostics exported without source paths, organization details or file contents.'
      )
    })
  return (
    <div className="space-y-5">
      <div className="flex gap-2 items-center text-sm">
        <Activity size={17} className="text-[var(--success)]" />
        <span>
          Local service:{' '}
          {query.isError
            ? 'unavailable'
            : query.data?.backend_status || 'checking…'}
        </span>
        <button
          onClick={() => void query.refetch()}
          className="ml-auto text-[var(--accent2)] underline text-xs"
        >
          Check again
        </button>
      </div>
      {query.data && (
        <dl className="grid sm:grid-cols-[170px_1fr] gap-x-6 gap-y-3 text-sm break-words">
          {Object.entries({
            'Application version': query.data.version,
            'Configuration schema': query.data.configuration_schema,
            'Configuration revision': query.data.configuration_revision,
            Platform: query.data.platform,
            'Cached roles': query.data.cached_roles,
            'Last successful load': query.data.last_successful_load
              ? new Date(query.data.last_successful_load).toLocaleString()
              : 'No successful load yet',
            'Active data source': query.data.data_source || 'No CSV configured',
            'Application data directory': query.data.application_directory
          }).map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-[var(--muted)]">{label}</dt>
              <dd className="min-w-0 break-all">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          disabled={!native || busy || !window.pywebview?.api.open_logs}
          onClick={() =>
            void act(async () => {
              await window.pywebview?.api.open_logs?.(applicationToken())
            })
          }
          className="border border-[var(--border)] rounded-lg px-3 py-2 text-sm flex items-center gap-2 disabled:opacity-50"
        >
          <FileText size={16} /> Open logs
        </button>
        <button
          disabled={busy}
          onClick={() => void exportReport()}
          className="border border-[var(--border)] rounded-lg px-3 py-2 text-sm flex items-center gap-2 disabled:opacity-50"
        >
          <Download size={16} /> Export diagnostics
        </button>
      </div>
      <p className="text-xs text-[var(--muted)]">
        Diagnostic exports contain versions, status and counts. They exclude CSV
        paths and contents, organization identity, rules, logs and session
        credentials.
      </p>
      {feedback && (
        <p role={failed ? 'alert' : 'status'} className="text-sm">
          {feedback}
        </p>
      )}
      <h2 className="settings-subheading">Configuration backup & recovery</h2>
    </div>
  )
}
