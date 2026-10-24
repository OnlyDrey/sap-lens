import { StatusPill } from '@/components/Shared/StatusPill'
import {
  EmployeeInformation,
  type Employee,
} from '@/components/Shared/EmployeeInformation'
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  UsersRound,
  Settings2,
  BookUser,
  Save,
  FolderOpen,
  Search,
  Trash2,
  CheckCircle,
  Upload,
} from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import type { Configuration } from '@/api/configuration'
import { formatTimestamp } from '@/lib/dateFormat'

interface Report {
  records: number
  file_name?: string
  imported_at: string
  duplicate_emails: number
  missing_emails: number
  managers: Record<string, number>
  validation: string
}
export interface DirectoryStatus {
  digest?:string|null
  mapping_data_available?: boolean
  enabled: boolean
  configured: boolean
  loaded: boolean
  operational_status?: string
  status: string
  error: string | null
  report: Partial<Report>
  coverage: Record<string, number>
  user_mapping_available: boolean
  persisted: boolean
  storage: string
  coverage_reason: string
  coverage_total: number
}
const label = (text: string) => text.replace(/_/g, ' ')

export function DirectoryDiagnostics({
  onConfigure,
  onFeatureSettings,
  sourceView = false,
}: {
  onConfigure?: () => void
  onFeatureSettings?: () => void
  sourceView?: boolean
} = {}) {
  const query = useQuery({
    queryKey: ['employee-status'],
    queryFn: () => apiRequest<DirectoryStatus>('/api/employees/status'),
    refetchInterval: 5000,
  })
  if (query.isError)
    return <p role="alert">Employee Directory status could not be checked.</p>
  const data = query.data
  if (!data) return <p role="status">Checking optional directory…</p>
  return (
    <section
      className="information-card space-y-3"
      aria-label={
        sourceView
          ? 'Directory import status'
          : 'Employee Directory diagnostics'
      }
    >
      <h3 className="font-semibold">
        Employee Directory · {label(data.status)}
        {data.operational_status === 'dependency_unavailable'
          ? ' · Identity enrichment unavailable'
          : ''}
      </h3>
      <p className="text-sm">
        {data.enabled ? 'Enabled' : 'Disabled'} ·{' '}
        {data.configured ? 'Source configured' : 'Not configured'} ·{' '}
        {data.loaded ? 'Data available' : 'No loaded data'} ·{' '}
        {data.persisted ? 'Records saved locally' : 'No durable records saved'}
      </p>
      {data.error && (
        <p role="alert" className="text-[var(--error)]">
          {data.error}
        </p>
      )}
      {sourceView ? (
        <>
          <div className="directory-quality-grid">
            {[
              ['Filename', data.report.file_name || 'No successful import'],
              [
                'Last successful import',
                data.report.imported_at
                  ? formatTimestamp(data.report.imported_at)
                  : 'Never',
              ],
              ['Records', data.report.records ?? 0],
              ['Validation', data.report.validation || 'Not validated'],
              ['Missing emails', data.report.missing_emails ?? 0],
              ['Duplicate emails', data.report.duplicate_emails ?? 0],
            ].map(([name, value]) => (
              <div key={name}>
                <span className="text-xs text-[var(--muted)]">{name}</span>
                <p>{value}</p>
              </div>
            ))}
          </div>
          <p className="text-sm">
            Manager relationships:{' '}
            {Object.entries(data.report.managers ?? {})
              .map(([key, value]) => `${label(key)}: ${value}`)
              .join(' · ') || 'Not evaluated'}
          </p>
          <p className="text-sm">
            SAP match coverage:{' '}
            {data.coverage_total > 0
              ? `${data.coverage.matched || 0} of ${data.coverage_total} SAP users matched (${Math.round((100 * (data.coverage.matched || 0)) / data.coverage_total)}%)`
              : data.coverage_reason || 'Not evaluated'}
          </p>
          {data.coverage_total > 0 && (
            <p className="text-xs text-[var(--muted)]">
              {Object.entries(data.coverage)
                .map(([key, value]) => `${label(key)}: ${value}`)
                .join(' · ')}
            </p>
          )}
          {data.report.missing_emails ? (
            <p className="text-sm text-[var(--warning)]">
              Missing emails are warnings. Those records are retained but cannot
              match a SAP identity by email.
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-sm">
          Storage: {label(data.storage || 'none')} · Dependency:{' '}
          {data.user_mapping_available
            ? 'satisfied'
            : data.coverage_reason || 'unavailable'}
          . Import history and data quality are under Data Sources → Employee
          Directory.
        </p>
      )}
      <p className="text-sm text-[var(--muted)]">
        Recovery: Data Sources → Employee Directory. Disabled or unconfigured
        optional sources do not affect SAP lookup health. Imported records are
        saved privately and remain usable without the original CSV. The
        timestamp is the confirmed import time.
      </p>
      {!data.enabled && (
        <p className="text-sm">
          Importing does not enable enrichment. Enable Employee Directory in
          Features and choose Apply settings to use the records.
        </p>
      )}
      {data.storage === 'legacy_path_only' && (
        <p className="text-sm text-[var(--warning)]">
          Legacy path-only configuration: loaded records have not been confirmed as a durable import. Use Save durable directory snapshot when validated records are available, or validate and import a CSV. A path alone cannot recover missing records.
        </p>
      )}
      {onFeatureSettings && (
        <button
          className="settings-secondary-button"
          onClick={onFeatureSettings}
        >
          {data.enabled
            ? 'Open Feature Settings'
            : 'Enable in Feature Settings'}
        </button>
      )}
      {onConfigure && (
        <button className="settings-secondary-button" onClick={onConfigure}>
          Review Employee Directory source
        </button>
      )}
    </section>
  )
}

export function FeatureSettings({
  draft,
  onChange,
  onConfigure,
}: {
  draft: Configuration
  onChange: (value: Configuration) => void
  onConfigure: (source: 'employees' | 'users') => void
}) {
  const [groupText,setGroupText]=useState((draft.unlicensed_user_groups||['UNLICENSED']).join(', '))
  useEffect(()=>setGroupText((draft.unlicensed_user_groups||['UNLICENSED']).join(', ')),[draft.revision])
  const directory = useQuery({
    queryKey: ['employee-status'],
    queryFn: () => apiRequest<DirectoryStatus>('/api/employees/status'),
  })
  return (
    <div className="space-y-3">
      {(
        [
          [
            'employee_directory',
            'Employee Directory',
            BookUser,
            'Enrich SAP identities with local employee and manager information.',
            directory.data?.loaded,
          ],
          [
            'user_role_mapping',
            'User–Role Mapping',
            UsersRound,
            'Investigate SAP users, role assignments and release roles.',
            directory.data?.mapping_data_available,
          ],
        ] as const
      ).map(([key, name, Icon, description, available]) => {
        const enabled = draft.features?.[key] ?? key === 'user_role_mapping'
        return (
          <section
            key={key}
            className="settings-card feature-card"
            aria-label={`${name} feature settings`}
          >
            <div>
              <h2 className="settings-subheading">
                <Icon size={18} aria-hidden="true" />
                {name}
              </h2>
              <p className="text-sm text-[var(--muted)]">{description}</p>
              <p className="text-xs">
                {directory.isError
                  ? 'Availability could not be checked.'
                  : available === undefined
                    ? 'Checking data availability…'
                    : available
                      ? 'Imported data available.'
                      : 'No imported data available.'}
              </p>
            </div>
            <button
              type="button"
              className="settings-secondary-button"
              role="switch"
              aria-label={`${name} feature`}
              aria-checked={enabled}
              onClick={() =>
                onChange({
                  ...draft,
                  features: {
                    employee_directory:
                      draft.features?.employee_directory ?? false,
                    user_role_mapping:
                      draft.features?.user_role_mapping ?? true,
                    [key]: !enabled,
                  },
                })
              }
            >
              <StatusPill enabled={enabled} />
            </button>
            <button
              type="button"
              className="settings-secondary-button"
              onClick={() =>
                onConfigure(
                  key === 'employee_directory' ? 'employees' : 'users',
                )
              }
            >
              <Settings2 size={15} aria-hidden="true" />
              Configure {name}
            </button>
          </section>
        )
      })}
      <label className="flex flex-col gap-1 text-sm">Unlicensed SAP User Groups<input className="settings-review-groups" value={groupText} onChange={e=>{setGroupText(e.target.value);onChange({...draft,unlicensed_user_groups:e.target.value.split(',').map(v=>v.trim()).filter(Boolean)})}}/><span className="text-xs text-[var(--muted)]">Comma-separated group values. This classification does not prove license entitlement and never suppresses account security findings.</span></label>
      <p className="text-sm text-[var(--muted)]">
        Apply settings to save changes. Disabling preserves source configuration
        and imported data. Employee identity enrichment requires enabled
        User–Role Mapping with SAP email data; Employee Directory remains
        independently enabled.
      </p>
    </div>
  )
}

export function EmployeeBrowser() {
  const [search, setSearch] = useState(''),
    [term, setTerm] = useState(''),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<{
      id: string
      generation: string
    } | null>(null)
  useEffect(() => {
    const timer = setTimeout(() => {
      setTerm(search)
      setOffset(0)
      setSelected(null)
    }, 180)
    return () => clearTimeout(timer)
  }, [search])
  const query = useQuery({
    queryKey: ['employees', term, offset],
    queryFn: () =>
      apiRequest<{ items: Employee[]; total: number; generation: string }>(
        `/api/employees?search=${encodeURIComponent(term)}&offset=${offset}`,
      ),
  })
  useEffect(() => {
    setSelected((previous) =>
      previous && previous.generation !== query.data?.generation
        ? null
        : previous,
    )
  }, [query.data?.generation])
  const detail = useQuery({
    queryKey: ['employee-record', selected?.id, selected?.generation],
    enabled: selected != null,
    queryFn: () =>
      apiRequest<Employee>(
        `/api/employees/record/${selected!.id}?generation=${selected!.generation}`,
      ),
  })
  return (
    <section className="space-y-3" aria-label="Employee search">
      <label className="block text-sm">
        <Search size={16} aria-hidden="true" className="inline-block mr-2 align-middle" />
        Search employees by name, email, department, job title, site or manager
        <input
          className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--surface2)] border-[var(--border)] text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          autoComplete="off"
        />
      </label>
      {query.isLoading && <p role="status">Loading employees…</p>}
      {query.isError && (
        <p role="alert">Directory search failed. Check Diagnostics.</p>
      )}
      {query.data && (
        <>
          <div className="access-table">
            <table>
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Department</th>
                  <th>Job title</th>
                  <th>Site</th>
                  <th>Manager</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((employee) => (
                  <tr key={employee.id}>
                    <td>
                      <button
                        className="settings-secondary-button"
                        onClick={() =>
                          setSelected({
                            id: employee.id,
                            generation: query.data!.generation,
                          })
                        }
                      >
                        {employee.name || employee.email || 'Unnamed employee'}
                      </button>
                    </td>
                    <td>{employee.department || '—'}</td>
                    <td>{employee.title || '—'}</td>
                    <td>{employee.site || '—'}</td>
                    <td>{employee.manager.name || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!query.data.total && <p>No employees match this search.</p>}
          <div className="flex gap-3 items-center">
            <button
              className="settings-secondary-button"
              disabled={!offset}
              onClick={() => {
                setOffset(Math.max(0, offset - 25))
                setSelected(null)
              }}
            >
              Previous employees
            </button>
            <span>{query.data.total} matching employees</span>
            <button
              className="settings-secondary-button"
              disabled={offset + 25 >= query.data.total}
              onClick={() => {
                setOffset(offset + 25)
                setSelected(null)
              }}
            >
              Next employees
            </button>
          </div>
        </>
      )}
      {detail.isError && selected?.generation === query.data?.generation && (
        <p role="alert">
          Employee details unavailable; search again if the directory changed.
        </p>
      )}
      {detail.data && selected?.generation === query.data?.generation && (
        <section className="information-card" aria-label="Employee details">
          <h3>Employee details</h3>
          <EmployeeInformation
            employee={detail.data}
            onManager={(id) =>
              setSelected({ id, generation: selected!.generation })
            }
          />
        </section>
      )}
    </section>
  )
}

export function EmployeeSource({
  revision,
  savedPath,
  dirty,
  onImported,
  onFeatureSettings,
}: {
  revision: number
  savedPath: string
  dirty: boolean
  onImported: () => Promise<void>
  onFeatureSettings: () => void
}) {
  const currentStatus=useQuery({queryKey:['employee-status'],queryFn:()=>apiRequest<DirectoryStatus>('/api/employees/status')})
  const [path, setPath] = useState(savedPath),
    [preview, setPreview] = useState<
      (Report & { digest: string; samples: Employee[] }) | null
    >(null),
    [success, setSuccess] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  useEffect(() => {
    setPath(savedPath)
    setPreview(null)
  }, [savedPath])
  const act = async (action: () => Promise<void>) => {
    setBusy(true)
    setError('')
    setSuccess('')
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Directory action failed.')
    } finally {
      setBusy(false)
    }
  }
  const refresh = async () => {
    await qc.invalidateQueries({
      predicate: (q) =>
        String(q.queryKey[0]).includes('employee') ||
        ['dashboard','account-review'].includes(String(q.queryKey[0])),
    })
    await onImported()
  }
  return (
    <div className="space-y-4">
      <section className="settings-card space-y-3">
        <h2 className="settings-subheading">
          <BookUser size={18} />
          Employee Directory CSV
        </h2>
        <p>
          1. Choose a CSV. 2. Validate and preview it. 3. Import directory. 4.
          Enable enrichment in Feature Settings. Import saves a private local
          snapshot; no cloud upload.
        </p>
        <DirectoryDiagnostics
          sourceView
          onFeatureSettings={onFeatureSettings}
        />
        {currentStatus.data?.loaded && !currentStatus.data.persisted && <button className="settings-secondary-button" disabled={busy||dirty||!currentStatus.data.digest} onClick={()=>void act(async()=>{await apiRequest('/api/employees/persist','POST',{revision,digest:currentStatus.data!.digest});await refresh();setSuccess('Validated directory records saved locally. The original CSV is no longer required for restart.')})}><Save size={16}/>Save durable directory snapshot</button>}
        <label className="block">
          Employee Directory CSV location
          <input
            className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--surface2)] border-[var(--border)] text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
            value={path}
            onChange={(e) => {
              setPath(e.target.value)
              setPreview(null)
              setSuccess('')
              setError('')
            }}
          />
        </label>
        <p className="text-sm" aria-label="Directory selection state">
          {preview
            ? 'Validated — review the preview and choose Import directory to save records.'
            : path && path !== savedPath
              ? 'CSV selected — not validated or imported.'
              : savedPath
                ? 'Previously imported source — validate again before replacement.'
                : 'No CSV selected. Employee Directory is optional.'}
        </p>
        <div className="flex gap-3 flex-wrap">
          <button
            className="settings-secondary-button"
            disabled={busy || !window.pywebview?.api}
            onClick={() =>
              void act(async () => {
                const selected =
                  await window.pywebview?.api.choose_csv(applicationToken())
                if (selected) {
                  setPath(selected)
                  setPreview(null)
                }
              })
            }
          >
            <FolderOpen size={16} />
            Browse employee CSV
          </button>
          <button
            className="settings-secondary-button"
            disabled={busy || !path || dirty}
            onClick={() =>
              void act(async () => {
                setPreview(null)
                setPreview(
                  await apiRequest('/api/employees/preview', 'POST', {
                    path,
                    revision,
                  }),
                )
              })
            }
          >
            Validate &amp; preview directory
          </button>
          <button
            className="settings-secondary-button"
            disabled={busy || !savedPath || dirty}
            onClick={() => {
              if (
                window.confirm(
                  'Remove the loaded Employee Directory and source configuration? The original CSV is not deleted.',
                )
              )
                void act(async () => {
                  const cleared = await apiRequest<{
                    cleanup_warning?: string
                  }>('/api/employees/clear', 'POST', {
                    path: savedPath,
                    revision,
                  })
                  setPreview(null)
                  await refresh()
                  setSuccess(
                    cleared.cleanup_warning ||
                      'Directory records and source configuration cleared. Original CSV unchanged.',
                  )
                })
            }}
          >
            <Trash2 size={16} />
            Clear directory data
          </button>
        </div>
        {dirty && (
          <p role="status">
            Save or cancel pending settings changes before importing directory
            data.
          </p>
        )}
        {busy && <p role="status">Reading local directory…</p>}
        {success && (
          <p
            role="status"
            className="text-[var(--success)] flex gap-2 items-center"
          >
            <CheckCircle size={16} aria-hidden="true" />
            {success}
          </p>
        )}
        {error && (
          <p role="alert" className="text-[var(--error)]">
            {error} Previous valid data is retained.
          </p>
        )}
        {preview && (
          <section
            className="information-card space-y-3"
            aria-label="Directory import preview"
          >
            <p>
              {preview.file_name} · {preview.records} records ·{' '}
              {preview.validation}
            </p>
            <p>
              {preview.duplicate_emails} duplicate email keys ·{' '}
              {preview.missing_emails} missing emails. Duplicates are never
              automatically matched.
            </p>
            <ul>
              {preview.samples.map((employee) => (
                <li key={employee.id}>
                  {employee.name || 'Unnamed employee'} ·{' '}
                  {employee.email || 'Missing email'} ·{' '}
                  {employee.department || 'No department'}
                </li>
              ))}
            </ul>
            <button
              className="settings-primary-button"
              disabled={busy || dirty}
              onClick={() =>
                void act(async () => {
                  const imported = await apiRequest<
                    DirectoryStatus & { cleanup_warning?: string }
                  >('/api/employees/import', 'POST', {
                    path,
                    digest: preview.digest,
                    revision,
                  })
                  setPreview(null)
                  await refresh()
                  setSuccess(
                    imported.cleanup_warning ||
                      `Directory imported: ${imported.report.records} records saved locally. ${imported.enabled ? 'Enrichment is enabled.' : 'Enrichment is disabled; open Feature Settings to enable it.'}`,
                  )
                })
              }
            >
              <Upload size={16} aria-hidden="true" />
              Import directory
            </button>
          </section>
        )}
      </section>

      <EmployeeBrowser />
    </div>
  )
}
