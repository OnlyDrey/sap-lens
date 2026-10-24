import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2,
  CircleAlert,
  History,
  Download,
  Info,
} from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import { formatTimestamp } from '@/lib/dateFormat'
import { Dialog } from './Dialog'
import { Button } from './Button'
import { FormField, Input } from './Controls'
import { Select } from './Select'
import { StatusBadge, DataTable, Toolbar } from './Presentation'
import { RoleIdentifier } from './RoleIdentifier'
import { Pagination } from '@/components/Access/Shared'
import { useViewHistory } from '@/hooks/useViewHistory'
import { Notification } from './Notification'

export interface SourceResult {
  source: string
  name: string
  status: string
  reason?: string
  mode: string
  records?: number
  added?: number
  removed?: number
  modified?: number
  unchanged?: number
  message?: string
  recovery?: string
  category?: string
  previous_preserved?: boolean
}
export interface RefreshSummary {
  id?: string | null
  timestamp: string
  status: 'changed' | 'unchanged' | 'partial' | 'failed'
  checked: number
  updated: number
  unchanged: number
  failed: number
  skipped: number
  sources: SourceResult[]
}
interface Change {
  source: string
  source_name: string
  type: string
  identifier: string
  fields: { field: string; before: string; after: string }[]
  before?: Record<string, string>
  after?: Record<string, string>
}
interface ReportPage {
  id: string
  timestamp: string
  status: string
  sources: SourceResult[]
  items: Change[]
  total: number
  offset: number
  limit: number
}
const label = (value: string) => value.replace(/_/g, ' ')

export function RefreshReportDialog({
  report,
  mode,
  onClose,
}: {
  report: Pick<RefreshSummary, 'id' | 'sources' | 'timestamp'>
  mode: 'changes' | 'errors'
  onClose: () => void
}) {
  const { change: changeView } = useViewHistory()
  const [source, setSource] = useState(''),
    [kind, setKind] = useState(''),
    [search, setSearch] = useState(''),
    [term, setTerm] = useState(''),
    [offset, setOffset] = useState(0),
    [exportError, setExportError] = useState(''),
    [exportFeedback, setExportFeedback] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search), 180)
    return () => clearTimeout(timer)
  }, [search])
  useEffect(() => setOffset(0), [source, kind, term])
  const params = new URLSearchParams({
    source,
    kind,
    search: term,
    offset: String(offset),
  })
  const query = useQuery({
    queryKey: ['refresh-report', report.id, source, kind, term, offset],
    queryFn: () =>
      apiRequest<ReportPage>(
        `/api/data-sources/reports/${report.id}?${params}`,
      ),
    enabled: !!report.id,
  })
  const data = query.data,
    sources = data?.sources || report.sources
  const exportChanges = async () => {
    setExportError('')
    setExportFeedback('')
    try {
      const response = await fetch(
        `/api/data-sources/reports/${report.id}/export?${new URLSearchParams({ source, kind, search: term })}`,
        { headers: { 'X-SAP-Lens': applicationToken() }, cache: 'no-store' },
      )
      if (!response.ok)
        throw Error('Change export could not be created. Check local storage.')
      const reader = response.body?.getReader()
      if (!reader)
        throw Error('Change export stream is unavailable. Retry the export.')
      const decoder = new TextDecoder('utf-8', { fatal: true }),
        parts: string[] = []
      let bytes = 0
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          bytes += value.byteLength
          if (bytes > 32 * 1024 * 1024) {
            await reader.cancel()
            throw Error('Export exceeds 32 MiB. Narrow the change filters.')
          }
          parts.push(decoder.decode(value, { stream: true }))
        }
        parts.push(decoder.decode())
      } finally {
        reader.releaseLock()
      }
      const content = '\ufeff' + parts.join('').replace(/^\ufeff/, '')
      if (window.pywebview) {
        if (!window.pywebview.api.save_refresh_changes_csv)
          throw Error(
            'Update the desktop application for change-report export.',
          )
        const saved = await window.pywebview.api.save_refresh_changes_csv(
          applicationToken(),
          `sap-lens-refresh-changes-report-${(data?.timestamp || report.timestamp).slice(0, 10)}.csv`,
          content,
        )
        setExportFeedback(
          saved ? 'Changes CSV saved locally.' : 'Export cancelled.',
        )
      } else {
        const url = URL.createObjectURL(
            new Blob([content], { type: 'text/csv;charset=utf-8' }),
          ),
          link = document.createElement('a')
        link.href = url
        link.download = 'SAP-Lens-refresh-changes.csv'
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Export failed.')
    }
  }
  return (
    <Dialog
      title={mode === 'changes' ? 'CSV data changes' : 'Refresh errors'}
      onClose={onClose}
    >
      <p className="text-sm text-[var(--muted)]">
        {formatTimestamp(data?.timestamp || report.timestamp)} · Private local
        evidence
      </p>
      {query.isError && <p role="alert">{query.error.message}</p>}
      {query.isLoading && <p role="status">Loading refresh evidence…</p>}
      <div className="refresh-source-summary">
        {sources.map((result) => (
          <section key={result.source} className="ui-card">
            <strong>{result.name}</strong>{' '}
            <StatusBadge
              tone={
                result.status === 'failed'
                  ? 'error'
                  : result.status === 'updated'
                    ? 'success'
                    : 'neutral'
              }
            >
              {label(result.status)}
            </StatusBadge>
            {result.status === 'failed' ? (
              <>
                <p>{result.message}</p>
                <p className="text-sm">
                  {result.previous_preserved
                    ? 'Previous validated records preserved. '
                    : 'No prior valid snapshot was available. '}
                  {result.recovery}
                </p>
                <small>Category: {label(result.category || 'unknown')}</small>
                {['roles', 'users', 'employees'].includes(result.source) && (
                  <Button
                    onClick={() => {
                      onClose()
                      changeView({
                        settings: true,
                        settingsTarget: result.source as
                          'roles' | 'users' | 'employees',
                      })
                    }}
                  >
                    Review {result.name} source
                  </Button>
                )}
              </>
            ) : result.status === 'skipped' ? (
              <p className="text-sm">{result.message}</p>
            ) : (
              <p className="text-sm">
                {result.added || 0} added · {result.removed || 0} removed ·{' '}
                {result.modified || 0} modified · {result.unchanged || 0}{' '}
                unchanged
              </p>
            )}
          </section>
        ))}
      </div>
      {mode === 'changes' && report.id && (
        <>
          <div className="refresh-report-filters">
            <FormField label="Change source">
              <Select
                className="ui-control"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                {[
                  ['', 'All sources'],
                  ...sources
                    .filter(
                      (s) => s.status === 'updated' || s.status === 'unchanged',
                    )
                    .map((s) => [s.source, s.name]),
                ].map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Change type">
              <Select
                className="ui-control"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                {['', 'added', 'removed', 'modified'].map((value) => (
                  <option key={value} value={value}>
                    {value ? label(value) : 'All changes'}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Search changes">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </FormField>
          </div>
          <Toolbar>
            <span>
              {data ? `${data.total} matching changes` : 'Loading changes…'}
            </span>
            <Button
              disabled={!data || !data.total}
              onClick={() => void exportChanges()}
            >
              <Download size={16} />
              Export changes CSV
            </Button>
          </Toolbar>
          {exportError && <p role="alert">{exportError}</p>}
          {exportFeedback && <p role="status">{exportFeedback}</p>}
          <DataTable caption="CSV record changes">
            <thead>
              <tr>
                <th>Source / record</th>
                <th>Change</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((change, index) => (
                <tr key={index}>
                  <td>
                    <span className="text-xs">{change.source_name}</span>
                    <RoleIdentifier
                      value={change.identifier}
                      label="record identifier"
                    />
                  </td>
                  <td>
                    <StatusBadge>{change.type}</StatusBadge>
                  </td>
                  <td>
                    <details>
                      <summary>
                        {change.type === 'modified'
                          ? `${change.fields.length} changed fields`
                          : 'View record'}
                      </summary>
                      <dl className="change-fields">
                        {(change.fields.length
                          ? change.fields
                          : Object.entries(
                              change.after || change.before || {},
                            ).map(([field, value]) => ({
                              field,
                              before: change.type === 'removed' ? value : '',
                              after: change.type === 'added' ? value : '',
                            }))
                        ).map((field) => (
                          <div key={field.field}>
                            <dt>{label(field.field)}</dt>
                            <dd>
                              {change.type !== 'added' && (
                                <span>
                                  <b>Before:</b> {field.before || 'Empty'}
                                </span>
                              )}
                              {change.type !== 'removed' && (
                                <span>
                                  <b>After:</b> {field.after || 'Empty'}
                                </span>
                              )}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          {data && !data.total && <p>No changes match these filters.</p>}
          <Pagination
            label="Change report pages"
            offset={offset}
            limit={25}
            total={data?.total || 0}
            onChange={setOffset}
          />
        </>
      )}
      {!report.id && (
        <p>
          Report could not be saved. The error details above remain available
          until this window is closed.
        </p>
      )}
    </Dialog>
  )
}

export function RefreshBanner({
  report,
  onDismiss,
}: {
  report: RefreshSummary
  onDismiss: () => void
}) {
  const [viewer, setViewer] = useState<'changes' | 'errors' | null>(null)
  const failed = report.failed > 0,
    changed = !failed && report.updated > 0
  const title = failed
    ? report.status === 'partial'
      ? 'Refresh completed with errors'
      : 'Data refresh failed'
    : changed
      ? 'Data refreshed successfully'
      : 'All data is up to date'
  const Icon = failed ? CircleAlert : changed ? CheckCircle2 : Info
  return (
    <>
      <Notification
        variant={failed ? 'error' : changed ? 'success' : 'neutral'}
        className="refresh-banner"
        label="Refresh result"
      >
        <div className="refresh-banner-body">
          <Icon size={20} aria-hidden="true" />
          <div>
            <strong>{title}</strong>
            <p>
              {report.checked} CSV sources checked · {report.updated} updated ·{' '}
              {report.unchanged} unchanged · {report.failed} failed ·{' '}
              {report.skipped} skipped
            </p>
          </div>
          <div className="ui-toolbar">
            {failed ? (
              <Button onClick={() => setViewer('errors')}>View Errors</Button>
            ) : changed && report.id ? (
              <Button onClick={() => setViewer('changes')}>View Changes</Button>
            ) : null}
            <Button onClick={onDismiss} aria-label="Dismiss refresh report">
              Close
            </Button>
          </div>
        </div>
      </Notification>
      {viewer && (
        <RefreshReportDialog
          report={report}
          mode={viewer}
          onClose={() => setViewer(null)}
        />
      )}
    </>
  )
}

export function RefreshHistory() {
  const query = useQuery({
    queryKey: ['refresh-history'],
    queryFn: () =>
      apiRequest<{
        items: (Omit<RefreshSummary, 'sources'> & {
          sources?: SourceResult[]
        })[]
      }>('/api/data-sources/history'),
  })
  const [selected, setSelected] = useState<
    | (Pick<RefreshSummary, 'id' | 'timestamp' | 'sources'> & {
        mode: 'changes' | 'errors'
      })
    | null
  >(null)
  return (
    <section
      className="settings-card space-y-3"
      aria-label="CSV refresh history"
    >
      <h3 className="settings-subheading">
        <History size={18} />
        Recent CSV refreshes
      </h3>
      <p className="text-xs text-[var(--muted)]">
        Five recent reports retained privately. Dismissing a banner does not
        delete its report. Record details are excluded from diagnostic exports.
      </p>
      {query.isError && (
        <p role="alert">Refresh history is unavailable. Check local storage.</p>
      )}
      {query.isLoading && <p role="status">Loading refresh history…</p>}
      {query.data && !query.data.items.length && (
        <p>No saved refresh reports.</p>
      )}
      {query.data?.items.map((report) => (
        <div key={report.id} className="ui-toolbar">
          <span>
            {formatTimestamp(report.timestamp)} · {label(report.status)} ·{' '}
            {report.updated || 0} updated · {report.failed || 0} failed
          </span>
          {report.failed > 0 ? (
            <Button
              onClick={() =>
                setSelected({ ...report, sources: [], mode: 'errors' })
              }
            >
              View Errors
            </Button>
          ) : report.updated > 0 ? (
            <Button
              onClick={() =>
                setSelected({ ...report, sources: [], mode: 'changes' })
              }
            >
              View Changes
            </Button>
          ) : null}
        </div>
      ))}
      {selected && (
        <RefreshReportDialog
          report={selected}
          mode={selected.mode}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  )
}
