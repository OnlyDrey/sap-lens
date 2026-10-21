import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Download, FileText, FolderOpen } from 'lucide-react'
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
      <section className="settings-card space-y-4">
        <h2 className="settings-subheading">
          <Activity size={18} aria-hidden="true" /> Application status
        </h2>
        <div className="flex gap-2 items-center text-sm">
          <span
            className={
              query.isError ? 'text-[var(--error)]' : 'text-[var(--success)]'
            }
          >
            Local service:{' '}
            {query.isError
              ? 'unavailable'
              : query.data?.backend_status || 'checking…'}
          </span>
          <button
            onClick={() => void query.refetch()}
            className="ml-auto settings-secondary-button"
          >
            Check again
          </button>
        </div>
        {query.data && (
          <dl className="settings-status-list">
            <dt>Application version</dt>
            <dd>{query.data.version}</dd>
            <dt>Current data status</dt>
            <dd>{query.data.cached_roles} roles loaded</dd>
            <dt>Last successful refresh</dt>
            <dd>
              {query.data.last_successful_load
                ? new Date(query.data.last_successful_load).toLocaleString()
                : 'No successful load yet'}
            </dd>
          </dl>
        )}
      </section>
      <section className="settings-card space-y-3">
        <h2 className="settings-subheading">Data & storage</h2>
        <p className="text-xs text-[var(--muted)]">
          These locations are shown only in this application and excluded from
          diagnostic exports.
        </p>
        <dl className="settings-status-list">
          <dt>Current data source</dt>
          <dd>{query.data?.data_source || 'No CSV configured'}</dd>
          <dt>Local application data</dt>
          <dd>{query.data?.application_directory || 'Checking…'}</dd>
        </dl>
        <button
          className="settings-secondary-button"
          disabled={
            !native || busy || !window.pywebview?.api.open_configuration_folder
          }
          onClick={() =>
            void act(async () => {
              await window.pywebview?.api.open_configuration_folder?.(
                applicationToken()
              )
            })
          }
        >
          <FolderOpen size={16} /> Open configuration folder
        </button>
        <p className="text-xs text-[var(--muted)]">
          Open the per-user folder containing settings, backups and application
          logs.
        </p>
      </section>
      <section className="settings-card space-y-3">
        <h2 className="settings-subheading">Troubleshooting</h2>
        <p className="text-sm text-[var(--text2)]">
          View local logs for detailed errors, or export a redacted status
          report to share with support.
        </p>
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
          Diagnostic exports contain versions, status and counts. They exclude
          CSV paths and contents, organization identity, rules, logs and session
          credentials.
        </p>
        {feedback && (
          <p role={failed ? 'alert' : 'status'} className="text-sm">
            {feedback}
          </p>
        )}
        <details className="settings-advanced">
          <summary>Technical details</summary>
          <dl className="settings-status-list">
            <dt>Configuration schema</dt>
            <dd>{query.data?.configuration_schema ?? 'Checking…'}</dd>
            <dt>Configuration revision</dt>
            <dd>{query.data?.configuration_revision ?? 'Checking…'}</dd>
            <dt>Platform</dt>
            <dd>{query.data?.platform ?? 'Checking…'}</dd>
          </dl>
        </details>
      </section>
    </div>
  )
}
