import { SourceEssentials, SourceTechnicalFacts, SourceDetailsDialog, type SourceEvidence } from './SourceStatus'
import { IndependentColumns } from '@/components/Shared/IndependentColumns'
import { EnabledBadge } from '@/components/Shared/StatusBadges'
import { StatusCard } from '@/components/Shared/InvestigationPatterns'
import { RefreshHistory } from '@/components/Shared/RefreshReport'
import { Button } from '@/components/Shared/Button'
import { DirectoryDiagnostics } from './EmployeeDirectory'
import { formatTimestamp } from '@/lib/dateFormat'
import { useId, useState } from 'react'
import { DisclosureChevron } from '@/components/Shared/DisclosureChevron'
import { useQuery } from '@tanstack/react-query'
import { Activity, BookUser, Download, FileText, FolderOpen, Library, ShieldCheck, UsersRound, Eye } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
const SOURCE_ICONS: Record<string, React.ReactNode> = { roles: <Library size={18} aria-hidden="true"/>, users: <UsersRound size={18} aria-hidden="true"/>, employees: <BookUser size={18} aria-hidden="true"/>, sod: <ShieldCheck size={18} aria-hidden="true"/> }
interface DataSource {
  last_checked?: string|null
  mode?: string
  snapshot_available?: boolean
  dependency?: string
  enabled?: boolean
  id: string
  name: string
  configured: boolean
  loaded: boolean
  configured_path?: string
  loaded_path?: string
  attempted_path?: string
  availability: string
  records: number
  assignments: number
  last_successful_load: string | null
  error: string | null
  loading: boolean
}
interface Snapshot {
  deployment_mode?: string
  last_successful_refresh?: string | null
  sources: DataSource[]
  version: string
  configuration_schema: number
  configuration_revision: number
  backend_status: string
  data_source: string
  application_directory: string
  cached_roles: number
  last_successful_load: string | null
  last_failed_load?: string | null
  storage_available?: boolean
  platform: string
}
const availabilityLabel = (value: string) =>
  (
    ({
      running: 'Running',
      loading: 'Loading',
      available_at_last_load:
        'Available at last successful load; current access not checked',
      not_checked: 'Not checked',
      missing: 'File missing on last attempt',
      access_denied: 'Access denied on last attempt',
      invalid: 'Validation failed on last attempt',
      validation: 'Validation failed on last attempt',
      headers: 'Header validation failed on last attempt',
      encoding: 'Encoding validation failed on last attempt',
      snapshot: 'Durable snapshot unavailable',
      failed: 'Read failed on last attempt',
    }) as Record<string, string>
  )[value] || value.replace(/_/g, ' ')
export function Diagnostics({
  native,
  onEmployeeSettings,
  onEmployeeFeatures,
  onSource,
}: {
  onSource?: (source: 'roles' | 'users' | 'employees' | 'sod') => void
  native: boolean
  onEmployeeFeatures?: () => void
  onEmployeeSettings?: () => void
}) {
  const query = useQuery({
    queryKey: ['diagnostics'],
    queryFn: () => apiRequest<Snapshot>('/api/diagnostics'),
    refetchInterval: 5000,
  })
  const [detail,setDetail]=useState<DataSource|null>(null)
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
        'The action could not be completed. Check access to your application directory.',
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
            'Diagnostics exported without source paths, organization details or file contents.',
          )
        return
      }
      const report = await apiRequest('/api/diagnostics/export')
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
          type: 'application/json',
        }),
      )
      const link = document.createElement('a')
      link.href = url
      link.download = 'SAP-Lens-diagnostics.json'
      link.click()
      URL.revokeObjectURL(url)
      setFeedback(
        'Diagnostics exported without source paths, organization details or file contents.',
      )
    })
  return (
    <div className="space-y-5">
      <section className="settings-card space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="settings-subheading">
            <Activity size={18} aria-hidden="true" /> Application status
          </h2>
          <span className="text-xs">{query.data?.deployment_mode||'desktop'} · {query.data?.platform||'Checking platform'}</span>
          <Button
            onClick={() => void query.refetch()}
            className="settings-secondary-button"
          >
            Check again
          </Button>
        </div>
        <div className="diagnostic-health-grid"><StatusCard label="Source health" value={query.isError?'Unavailable':!query.data?'Checking…':query.data.sources.some(source=>source.enabled!==false&&source.error)?'Warnings':query.data.sources.some(source=>source.enabled!==false&&source.loaded)?'Ready':'Not configured'} tone={query.isError?'error':query.data?.sources.some(source=>source.enabled!==false&&source.error)?'warning':query.data?.sources.some(source=>source.enabled!==false&&source.loaded)?'success':'neutral'}/><StatusCard label="Local service" value={query.isError?'Unavailable':query.data?.backend_status?availabilityLabel(query.data.backend_status):'Checking…'} tone={query.isError?'error':query.data?.backend_status==='loading'?'info':query.data?'success':'neutral'}/><StatusCard label="Last successful refresh" value={formatTimestamp(query.data?.last_successful_refresh,'No successful refresh yet')}/><StatusCard label="Application storage" value={query.data?.storage_available?'Available':'Not created'} tone={query.data?.storage_available?'success':'neutral'}/></div>
        <p className="ui-description">Imports activate validated datasets; Global Refresh checks Dynamic sources. A successful import does not imply a successful Global Refresh. Static sources retain their snapshots.</p>

        <details className="settings-advanced">
          <summary>Health details and refresh history</summary>
          {query.data && (
            <dl className="settings-status-list">
              <dt>Application version</dt>
              <dd>{query.data.version}</dd>
              <dt>Application storage</dt>
              <dd>
                {query.data.storage_available
                  ? 'Directory present'
                  : 'Created on first save'}
              </dd>
              <dt>Last failed refresh</dt>
              <dd>
                {formatTimestamp(
                  query.data.last_failed_load,
                  'No failed refresh in this session',
                )}
              </dd>
              <dt>Last dataset activation</dt>
              <dd>
                {query.data.last_successful_load
                  ? formatTimestamp(query.data.last_successful_load)
                  : 'No successful load yet'}
              </dd>
            </dl>
          )}
        </details>
      </section>
      <section className="space-y-3" aria-label="Data source health">
        <h2 className="settings-subheading">Data source health</h2>
        <IndependentColumns breakpoints={SOURCE_COLUMNS} items={(query.data?.sources ?? []).map((source) => <SourceHealthCard key={source.id} source={source} onDetail={() => setDetail(source)} onSource={onSource} />)} />
      </section>
      {detail&&<SourceDetailsDialog source={detail} onClose={()=>setDetail(null)}>{detail.id==='employees'&&<DirectoryDiagnostics onConfigure={()=>{setDetail(null);onEmployeeSettings?.()}} onFeatureSettings={()=>{setDetail(null);onEmployeeFeatures?.()}}/>}</SourceDetailsDialog>}
      <RefreshHistory />
      <section className="settings-card space-y-3">
        <h2 className="settings-subheading">Data & storage</h2>
        <details className="settings-advanced">
          <summary>Source locations and storage details</summary>
          <p className="text-xs text-[var(--muted)]">
            These locations are shown only in this application and excluded from
            diagnostic exports.
          </p>
          <dl className="settings-status-list">
            <dt>Local application data</dt>
            <dd>{query.data?.application_directory || 'Checking…'}</dd>
          </dl>
          <Button
            className="settings-secondary-button"
            disabled={
              !native ||
              busy ||
              !window.pywebview?.api.open_configuration_folder
            }
            onClick={() =>
              void act(async () => {
                await window.pywebview?.api.open_configuration_folder?.(
                  applicationToken(),
                )
              })
            }
          >
            <FolderOpen size={16} /> Open configuration folder
          </Button>
          <p className="text-xs text-[var(--muted)]">
            Open the per-user folder containing settings, backups and
            application logs.
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

/** Wide screens show three columns, medium two, narrow one. */
const SOURCE_COLUMNS: [number, number][] = [[1400, 3], [700, 2]]
/** One source card: essentials, then Technical details (toggle) and Review source side by side; the technical facts open beneath the buttons. */
function SourceHealthCard({ source, onDetail, onSource }: { source: SourceEvidence; onDetail: () => void; onSource?: (source: 'roles' | 'users' | 'employees' | 'sod') => void }) {
  const [open, setOpen] = useState(false), id = useId()
  return (
    <section className="settings-card source-health-card" aria-label={source.name}>
      <header className="source-health-header">
        <h3 className="font-semibold">{SOURCE_ICONS[source.id] || <FileText size={18} aria-hidden="true"/>}{source.name}</h3>
        {source.enabled !== undefined && <EnabledBadge enabled={!!source.enabled} />}
      </header>
      <SourceEssentials source={source}/>
      <div className="source-health-actions">
        <Button aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}><DisclosureChevron open={open} />Technical details</Button>
        <Button onClick={() => onSource?.(source.id as 'roles' | 'users' | 'employees' | 'sod')}><Eye size={16} aria-hidden="true"/>Review source</Button>
      </div>
      {open && <div id={id} className="source-health-technical space-y-2">
        <SourceTechnicalFacts source={source}/>
        <Button onClick={onDetail}><FileText size={16} aria-hidden="true"/>Locations and diagnostics</Button>
      </div>}
    </section>
  )
}
