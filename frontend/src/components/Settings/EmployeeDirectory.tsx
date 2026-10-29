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
  ShieldCheck,
  Save, ArrowLeft, ArrowRight,
} from 'lucide-react'
import { apiRequest } from '@/api/client'
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
      {sourceView&&<><p className="ui-description">{data.report.records??0} imported records · {data.coverage_total?`${data.coverage.matched??0} / ${data.coverage_total} SAP identities matched · ${(((data.coverage.matched??0)/data.coverage_total)*100).toFixed(1)}%`:data.coverage_reason||'SAP matching not evaluated'}</p>{!!(data.report.missing_emails||data.report.duplicate_emails)&&<p className="ui-description"><StatusBadge tone="warning">Data quality warnings</StatusBadge> {data.report.missing_emails||0} missing emails · {data.report.duplicate_emails||0} duplicate email keys. View diagnostics for details.</p>}</>}
      <details open={!sourceView}><summary>View diagnostics</summary>
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
      </details>
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
  onConfigure: (source: 'employees' | 'users' | 'sod') => void
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
  const sodSource = useQuery({
    queryKey: ['sod-catalogue-source'],
    queryFn: () => apiRequest<{ source: { loaded: boolean; risks: number; records: number } }>('/api/sod/catalogue?limit=1'),
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
          [
            'sod',
            'Segregation of Duties',
            ShieldCheck,
            'Analyze potential SoD conflicts, review them and report on them. Turning it on is always a manual choice; importing a matrix never enables it.',
            sodSource.data ? sodSource.data.source.loaded : undefined,
          ],
        ] as const
      ).map(([key, name, Icon, description, available]) => {
        const defaults: Record<string, boolean> = { user_role_mapping: true, employee_directory: false, sod: false }
        const enabled = draft.features?.[key] ?? defaults[key]
        const savedEnabled=saved.data?.settings.features?.[key]??defaults[key]
        const mappingSaved=saved.data?.settings.features?.user_role_mapping??true
        const operational=key==='employee_directory'?directory.data?.operational_status==='ready':key==='sod'?!!sodSource.data?.source.loaded&&mappingSaved&&savedEnabled&&!!directory.data?.mapping_data_available:!!directory.data?.user_mapping_available
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
                {!directory.data?'Checking operational status…':operational?'Operational':!savedEnabled?'Disabled in saved settings':key==='sod'&&!mappingSaved?'Requires User–Role Mapping':!available?'Data required':key==='sod'?'User access data required':'Identity enrichment unavailable'}
              </StatusBadge>
              {saved.data&&enabled!==(saved.data.settings.features?.[key]??key==='user_role_mapping')&&<p role="status" className="ui-description">Pending change — choose Apply settings to save.</p>}
            </div>
            <div className="feature-controls">
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
                      sod: draft.features?.sod ?? false,
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
                    key === 'employee_directory' ? 'employees' : key === 'sod' ? 'sod' : 'users',
                  )
                }
              >
                <Settings2 size={15} aria-hidden="true" />
                Configure source
              </button>
            </div>
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
          <div className="feature-operational"><StatusBadge
            tone={
              directory.data?.operational_status === 'ready'
                ? 'success'
                : 'neutral'
            }
          >
            {directory.data?.operational_status === 'ready'
              ? 'Operational'
              : 'Unavailable'}
          </StatusBadge></div>
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
          Configure source
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
          <div className="employee-pagination flex flex-wrap gap-3 items-center">
            <button
              className="settings-secondary-button"
              aria-label="Previous employees"
              disabled={!offset}
              onClick={() => {
                setOffset(Math.max(0, offset - 25))
                setSelected(null)
              }}
            >
              <ArrowLeft size={16} aria-hidden="true"/> Previous
            </button>
            <span>{query.data.total} matching employees</span>
            <button
              className="settings-secondary-button"
              aria-label="Next employees"
              disabled={offset + 25 >= query.data.total}
              onClick={() => {
                setOffset(offset + 25)
                setSelected(null)
              }}
            >
              Next <ArrowRight size={16} aria-hidden="true"/>
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

/** Recovery of existing validated legacy records; this never rereads a CSV. */
export function DirectorySnapshotRecovery({onPersisted}:{onPersisted:()=>Promise<void>}) {
  const qc=useQueryClient(),status=useQuery({queryKey:['employee-status'],queryFn:()=>apiRequest<DirectoryStatus>('/api/employees/status')})
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  if(!status.data?.loaded||status.data.persisted||!status.data.digest)return null
  return <div><Button disabled={busy} onClick={()=>{setBusy(true);setError('');void (async()=>{
    const current=await fetchConfiguration()
    await apiRequest('/api/employees/persist','POST',{revision:current.settings.revision,digest:status.data!.digest})
    await onPersisted();await qc.invalidateQueries({queryKey:['employee-status']})
  })().catch(cause=>setError(cause instanceof Error?cause.message:'Snapshot recovery failed.')).finally(()=>setBusy(false))}}><Save size={16} aria-hidden="true"/>Save durable directory snapshot</Button>{error&&<p role="alert">{error}</p>}</div>
}
