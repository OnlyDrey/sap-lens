import { SourceStatusSummary } from './SourceStatus'
import { SourceFileField } from './ImportControls'
import { DirectoryPreview } from './DirectoryPreview'
import { BrowserSourceUpload } from './BrowserSourceUpload'
import { ImportSection } from './ImportSection'
import { Toggle, SearchInput } from '@/components/Shared/Controls'
import { Button } from '@/components/Shared/Button'
import { StatusBadge } from '@/components/Shared/Presentation'
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
  Trash2,
  CheckCircle,
  Upload,
} from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import { fetchConfiguration, type Configuration } from '@/api/configuration'
import { formatTimestamp } from '@/lib/dateFormat'

interface Report {
  missing_identifiers?: number
  duplicate_identifiers?: { usernames: number; distinguished_names: number }
  records: number
  file_name?: string
  imported_at: string
  duplicate_emails: number
  missing_emails: number
  managers: Record<string, number>
  validation: string
}
export interface DirectoryStatus {
  digest?: string | null
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
              [
                'Missing employee identifiers',
                data.report.missing_identifiers ?? 0,
              ],
              [
                'Duplicate AD username keys',
                data.report.duplicate_identifiers?.usernames ?? 0,
              ],
              [
                'Duplicate DN keys',
                data.report.duplicate_identifiers?.distinguished_names ?? 0,
              ],
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
          Legacy path-only configuration: loaded records have not been confirmed
          as a durable import. Use Save durable directory snapshot when
          validated records are available, or validate and import a CSV. A path
          alone cannot recover missing records.
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
  const [groupText, setGroupText] = useState(
    (draft.unlicensed_user_groups || ['UNLICENSED']).join(', '),
  )
  useEffect(
    () =>
      setGroupText((draft.unlicensed_user_groups || ['UNLICENSED']).join(', ')),
    [draft.revision],
  )
  const saved=useQuery({queryKey:['configuration'],queryFn:fetchConfiguration})
  const directory = useQuery({
    queryKey: ['employee-status'],
    queryFn: () => apiRequest<DirectoryStatus>('/api/employees/status'),
  })
  return (
    <div className="space-y-3">
      {(
        [
          [
            'user_role_mapping',
            'User–Role Mapping',
            UsersRound,
            'Investigate SAP users, role assignments and release roles.',
            directory.data?.mapping_data_available,
          ],
          [
            'employee_directory',
            'Employee Directory',
            BookUser,
            'Keep local employee and manager records available independently of SAP matching.',
            directory.data?.loaded,
          ],
        ] as const
      ).map(([key, name, Icon, description, available]) => {
        const enabled = draft.features?.[key] ?? key === 'user_role_mapping'
        const savedEnabled=saved.data?.settings.features?.[key]??key==='user_role_mapping'
        const operational=key==='employee_directory'?directory.data?.operational_status==='ready':!!directory.data?.user_mapping_available
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
              <StatusBadge
                tone={operational?'success':!savedEnabled?'neutral':'warning'}
              >
                {!directory.data?'Checking operational status…':operational?'Operational':!savedEnabled?'Disabled in saved settings':!available?'Data required':'Identity enrichment unavailable'}
              </StatusBadge>
            </div>
            {saved.data&&enabled!==(saved.data.settings.features?.[key]??key==='user_role_mapping')&&<p role="status" className="ui-description">Pending change — choose Apply settings to save.</p>}
            <Toggle
              label={`${name} feature`}
              checked={enabled}
              onChange={(next) =>
                onChange({
                  ...draft,
                  features: {
                    employee_directory:
                      draft.features?.employee_directory ?? false,
                    user_role_mapping:
                      draft.features?.user_role_mapping ?? true,
                    [key]: next,
                  },
                })
              }
            />
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
      <section
        className="settings-card feature-card"
        aria-label="SAP Identity Enrichment dependencies"
      >
        <div>
          <h2 className="settings-subheading">
            <UsersRound size={18} aria-hidden="true" />
            SAP Identity Enrichment
          </h2>
          <p className="text-sm text-[var(--muted)]">
            Derived from User–Role Mapping and Employee Directory. Exact email
            matching enriches SAP profiles without overwriting SAP attributes.
          </p>
          <StatusBadge
            tone={
              directory.data?.operational_status === 'ready'
                ? 'success'
                : 'neutral'
            }
          >
            {directory.data?.operational_status === 'ready'
              ? 'Operational'
              : 'Unavailable'}
          </StatusBadge>
          <p className="text-xs">Runtime status uses saved preferences.</p>
          <p className="text-xs">
            {!draft.features?.employee_directory
              ? 'Enable Employee Directory. '
              : ''}
            {draft.features?.user_role_mapping === false
              ? 'Enable User–Role Mapping. '
              : ''}
            {!directory.data?.loaded ? 'Import directory records. ' : ''}
            {!directory.data?.mapping_data_available
              ? 'Import SAP user records. '
              : ''}
            Preferences and records are retained when dependencies are
            unavailable.
          </p>
        </div>
        <Button onClick={() => onConfigure('employees')}>
          <Settings2 size={16} />
          Configure identity sources
        </Button>
      </section>
      <label className="flex flex-col gap-1 text-sm">
        Unlicensed SAP User Groups
        <input
          className="settings-review-groups"
          value={groupText}
          onChange={(e) => {
            setGroupText(e.target.value)
            onChange({
              ...draft,
              unlicensed_user_groups: e.target.value
                .split(',')
                .map((v) => v.trim())
                .filter(Boolean),
            })
          }}
        />
        <span className="text-xs text-[var(--muted)]">
          Comma-separated group values. This classification does not prove
          license entitlement and never suppresses account security findings.
        </span>
      </label>
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
      <SearchInput aria-label="Search employees by name, email, department, job title, site or manager" placeholder="Search employees…" value={search} onChange={e=>setSearch(e.target.value)} onClear={()=>setSearch('')} autoComplete="off"/>

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
  mode?:'static'|'dynamic'
  savedPath: string
  dirty: boolean
  onImported: () => Promise<void>
  onFeatureSettings: () => void
}) {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: ['employee-status'],
    queryFn: () => apiRequest<DirectoryStatus>('/api/employees/status'),
  })
  const [uploaded,setUploaded]=useState(false)
  const [path, setPath] = useState(savedPath),
    [preview, setPreview] = useState<
      | (Report & {
          digest: string
          current_records?: number
          replacement?: Record<string, number>
        })
      | null
    >(null),
    [success, setSuccess] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
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
        [
          'employee-status',
          'employees',
          'employee-match',
          'dashboard',
          'account-review',
          'diagnostics',
          'data-health',
          'refresh-history',
        ].includes(String(q.queryKey[0])),
    })
    await onImported()
  }
  const choose = (value: string) => {
    setUploaded(false)
    setPath(value)
    setPreview(null)
    setSuccess('')
    setError('')
  }
  return (
    <div className="space-y-4">

      {status.data?.loaded && !status.data.persisted && (
        <Button
          disabled={busy || dirty || !status.data.digest}
          onClick={() =>
            void act(async () => {
              await apiRequest('/api/employees/persist', 'POST', {
                revision,
                digest: status.data!.digest,
              })
              await refresh()
              setSuccess(
                'Validated directory records saved locally. The original CSV is no longer required for restart.',
              )
            })
          }
        >
          <Save size={16} />
          Save durable directory snapshot
        </Button>
      )}
      <ImportSection
        step={1}
        title="Source file"
        description="Choose a local Employee Directory CSV. Selection alone does not import or replace records."
      >
        <p className="ui-description">Employee Directory uses a fixed import format: UTF-8 CSV with semicolon separators and the documented directory headers. No SAP role mapping is inferred.</p>
        <BrowserSourceUpload source="employees" disabled={busy||dirty} onUploaded={value=>{choose(value);setUploaded(true)}}/>
        <SourceFileField label="Employee Directory CSV location" value={path} onChange={choose} native={Boolean(window.pywebview?.api)} disabled={busy} browseLabel="Browse employee CSV" onBrowse={()=>void act(async()=>{const selected=await window.pywebview?.api.choose_csv(applicationToken());if(selected)choose(selected)})}/>
        <div className="ui-toolbar">
          <Button
            disabled={busy || !savedPath || dirty}
            onClick={() => {
              if (
                window.confirm(
                  'Remove the loaded Employee Directory and source configuration? The original CSV is not deleted.',
                )
              )
                void act(async () => {
                  const result = await apiRequest<{ cleanup_warning?: string }>(
                    '/api/employees/clear',
                    'POST',
                    { path: savedPath, revision },
                  )
                  setPreview(null)
                  await refresh()
                  setSuccess(
                    result.cleanup_warning ||
                      'Directory records and source configuration cleared. Original CSV unchanged.',
                  )
                })
            }}
          >
            <Trash2 size={16} />
            Clear directory data
          </Button>
        </div>
        <p className="text-sm" aria-label="Directory selection state">
          {preview
            ? 'Validated — review the preview and choose Import directory to save records.'
            : path && path !== savedPath
              ? 'CSV selected — not validated or imported.'
              : savedPath
                ? 'Previously imported source — validate again before replacement.'
                : 'No CSV selected. Employee Directory is optional.'}
        </p>
      </ImportSection>
      <ImportSection
        step={2}
        title="Validate & Preview"
        description="Validate the entire file, inspect data quality and review a paginated preview before confirming."
      >
        <Button
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
          <CheckCircle size={16} />
          Validate &amp; preview directory
        </Button>
        {preview && (
          <section className="space-y-3" aria-label="Directory import preview">
            <p>
              {preview.file_name} · {preview.records} records ·{' '}
              {preview.validation}
            </p>
            <p>
              {preview.duplicate_emails} duplicate email keys ·{' '}
              {preview.missing_emails} missing emails. Missing emails are
              warnings; records are retained. Duplicates are never automatically
              matched.
            </p>
            <DirectoryPreview
              path={path}
              digest={preview.digest}
              revision={revision}
            />
          </section>
        )}
      </ImportSection>
      <ImportSection
        step={3}
        title="Import / Replace"
        description="Confirmation activates a complete validated replacement and saves a private local snapshot. No cloud upload."
      >
        {preview ? (
          <>
            <p>
              Current:{' '}
              {preview.current_records ?? status.data?.report.records ?? 0}{' '}
              records · Incoming: {preview.records} records
            </p>
            {preview.replacement && (
              <p className="text-sm">
                {preview.replacement.added} added ·{' '}
                {preview.replacement.removed} removed ·{' '}
                {preview.replacement.modified} modified ·{' '}
                {preview.replacement.unchanged} unchanged
              </p>
            )}
            <p className="text-sm">
              Importing this file will replace the existing Employee Directory
              dataset. Records missing from the new CSV will be removed from the
              active dataset.
            </p>
          </>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            Validate a CSV to enable import confirmation.
          </p>
        )}
        <Button
          variant="primary"
          disabled={busy || dirty || !preview}
          onClick={() => {
            if (!preview) return
            if (
              (preview.current_records ?? 0) > 0 &&
              preview.digest !== status.data?.digest &&
              !window.confirm(
                'Replace the entire Employee Directory with this validated CSV? Records absent from the new file will be removed.',
              )
            )
              return
            void act(async () => {
              const imported = await apiRequest<
                DirectoryStatus & { cleanup_warning?: string }
              >('/api/employees/import', 'POST', {
                path,
                digest: preview.digest,
                revision,
                ...(uploaded?{mode:'static'}:{}),
              })
              setPreview(null)
              await refresh()
              setSuccess(
                imported.cleanup_warning ||
                  `Directory imported: ${imported.report.records} records saved locally. ${imported.enabled ? 'Enrichment is enabled.' : 'Enrichment is disabled; open Feature Settings to enable it.'}`,
              )
            })
          }}
        >
          <Upload size={16} />
          Import directory
        </Button>
      </ImportSection>
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
          <CheckCircle size={16} />
          {success}
        </p>
      )}
      {error && (
        <p role="alert" className="text-[var(--error)]">
          {error} Previous valid data is retained.
        </p>
      )}
      <SourceStatusSummary source="employees"/>
      <DirectoryDiagnostics sourceView onFeatureSettings={onFeatureSettings} />
      <EmployeeBrowser />
    </div>
  )
}
