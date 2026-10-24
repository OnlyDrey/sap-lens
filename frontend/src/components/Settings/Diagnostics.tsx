import { DirectoryDiagnostics } from './EmployeeDirectory'
import { SourceBadge } from '@/components/Shared/SourceBadge'
import { formatTimestamp } from '@/lib/dateFormat'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Download, FileText, FolderOpen } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
interface DataSource {
  enabled?: boolean
  id: string; name: string; configured: boolean; loaded: boolean; configured_path?: string; loaded_path?: string; attempted_path?: string;
  availability: string; records: number; assignments: number; last_successful_load: string | null; error: string | null; loading: boolean
}
interface Snapshot {
  sources: DataSource[]
  version: string
  configuration_schema: number
  configuration_revision: number
  backend_status: string
  data_source: string
  application_directory: string
  cached_roles: number
  last_successful_load: string | null
  last_failed_load?:string|null
  storage_available?:boolean
  platform: string
}
export function Diagnostics({ native, onEmployeeSettings, onEmployeeFeatures }: { native: boolean; onEmployeeFeatures?: () => void; onEmployeeSettings?: () => void }) {
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
<details className="settings-advanced"><summary>Employee Directory technical details</summary><DirectoryDiagnostics onConfigure={onEmployeeSettings} onFeatureSettings={onEmployeeFeatures}/></details>
      <section className="settings-card space-y-4">
        <div className="flex items-center justify-between gap-3"><h2 className="settings-subheading">
          <Activity size={18} aria-hidden="true" /> Application status
        </h2><button onClick={()=>void query.refetch()} className="settings-secondary-button">Check again</button></div>
        <div className="review-metrics"><div className="compact-health"><span>Local service</span><strong>{query.isError?'Unavailable':query.data?.backend_status||'Checking…'}</strong></div><div className="compact-health"><span>Last successful refresh</span><strong className="text-sm">{formatTimestamp(query.data?.last_successful_load)}</strong></div><div className="compact-health"><span>Application storage</span><strong>{query.data?.storage_available?'Present':'Not created'}</strong></div></div>

        <details className="settings-advanced"><summary>Health details and refresh history</summary>{query.data && (
          <dl className="settings-status-list">
            <dt>Application version</dt>
            <dd>{query.data.version}</dd>
            <dt>Current data status</dt>
            <dd className="flex flex-wrap gap-2">{query.data.sources.map(source => <span key={source.id}>{source.name}: {source.records.toLocaleString()} {source.id === 'users' ? source.records === 1 ? 'user' : 'users' : source.records === 1 ? 'role' : 'roles'} · {source.enabled === false ? <span>Disabled · retained data</span> : <SourceBadge loading={source.loading} error={source.error} loaded={source.loaded}/>}</span>)}</dd>
            <dt>Application storage</dt><dd>{query.data.storage_available ? 'Directory present' : 'Created on first save'}</dd><dt>Last failed refresh</dt><dd>{formatTimestamp(query.data.last_failed_load,'No failed refresh in this session')}</dd>
            <dt>Last successful refresh</dt>
            <dd>
              {query.data.last_successful_load
                ? formatTimestamp(query.data.last_successful_load)
                : 'No successful load yet'}
            </dd>
          </dl>
        )}</details>
      </section>
      <section className="settings-card space-y-3">
        <h2 className="settings-subheading">Data & storage</h2>
        <details className="settings-advanced"><summary>Source locations and storage details</summary><p className="text-xs text-[var(--muted)]">
          These locations are shown only in this application and excluded from
          diagnostic exports.
        </p>
        {query.data && <div className="diagnostic-sources">{query.data.sources.map(source => <section className="information-card" key={source.id} aria-label={source.name}>
          <h3 className="font-semibold mb-3">{source.name}</h3>
          <dl className="information-list">
            <dt>Configured file</dt><dd>{source.configured_path || 'Not configured'}</dd>
            <dt>Loaded source</dt><dd>{source.loaded_path || 'No successful load'}</dd>
            <dt>Availability</dt><dd>{({ available_at_last_load:'Available at last successful load; current access not checked', not_checked:'Not checked', missing:'File missing on last attempt', access_denied:'Access denied on last attempt', invalid:'Validation failed on last attempt', failed:'Read failed on last attempt' } as Record<string,string>)[source.availability] || 'Not checked'}</dd>
            <dt>Last loaded</dt><dd>{source.last_successful_load ? formatTimestamp(source.last_successful_load) : 'Never'}</dd>
            <dt>Records</dt><dd>{source.records.toLocaleString()} {source.id === 'users' ? source.records === 1 ? 'user' : 'users' : source.records === 1 ? 'role' : 'roles'} · {source.assignments.toLocaleString()} {source.assignments === 1 ? 'assignment' : 'assignments'}</dd>
            <dt>Status</dt><dd>{source.enabled === false ? <span>Disabled · retained data</span> : <SourceBadge loading={source.loading} error={source.error} loaded={source.loaded}/>}</dd>
            {source.error && <><dt>Last attempt</dt><dd>{source.attempted_path || 'Unknown location'} · {source.error.replace(/_/g, ' ')}. Previously loaded data is retained.</dd></>}
          </dl>
        </section>)}</div>}
        <dl className="settings-status-list"><dt>Local application data</dt><dd>{query.data?.application_directory || 'Checking…'}</dd></dl>
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
        </details>
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
