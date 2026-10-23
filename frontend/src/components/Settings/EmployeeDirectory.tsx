import { StatusPill } from '@/components/Shared/StatusPill'
import {
  EmployeeInformation,
  type Employee,
} from '@/components/Shared/EmployeeInformation'
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookUser, FolderOpen, Search, Trash2 } from 'lucide-react'
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
  enabled: boolean
  configured: boolean
  loaded: boolean
  status: string
  error: string | null
  report: Partial<Report>
  coverage: Record<string, number>
  user_mapping_available: boolean
}
const label = (text: string) => text.replace(/_/g, ' ')

export function DirectoryDiagnostics({
  onConfigure,
}: { onConfigure?: () => void } = {}) {
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
      aria-label="Employee Directory diagnostics"
    >
      <h3 className="font-semibold">
        Employee Directory · {label(data.status)}
      </h3>
      <p className="text-sm">
        {data.enabled ? 'Enabled' : 'Disabled'} ·{' '}
        {data.configured ? 'Source configured' : 'Not configured'} ·{' '}
        {data.loaded ? 'Data available' : 'No loaded data'}
      </p>
      {data.error && (
        <p role="alert" className="text-[var(--error)]">
          {data.error}
        </p>
      )}
      <dl className="information-list">
        <dt>Filename</dt>
        <dd>{data.report.file_name || 'No successful import'}</dd>
        <dt>Validation</dt>
        <dd>{data.report.validation || 'Not validated'}</dd>
        <dt>Records</dt>
        <dd>{data.report.records ?? 0}</dd>
        <dt>Duplicate emails</dt>
        <dd>{data.report.duplicate_emails ?? 0}</dd>
        <dt>Missing emails</dt>
        <dd>{data.report.missing_emails ?? 0}</dd>
        <dt>Last successful import</dt>
        <dd>
          {data.report.imported_at
            ? formatTimestamp(data.report.imported_at)
            : 'Never'}
        </dd>
        <dt>User–Role Mapping</dt>
        <dd>
          {data.user_mapping_available
            ? 'Available; exact SAP email matching supported'
            : 'Not loaded; SAP match coverage unavailable'}
        </dd>
        <dt>SAP match coverage</dt>
        <dd>
          {Object.entries(data.coverage)
            .map(([key, value]) => `${label(key)}: ${value}`)
            .join(' · ') || 'Not evaluated'}
        </dd>
        <dt>Manager relationships</dt>
        <dd>
          {Object.entries(data.report.managers ?? {})
            .map(([key, value]) => `${label(key)}: ${value}`)
            .join(' · ') || 'Not evaluated'}
        </dd>
      </dl>
      <p className="text-sm text-[var(--muted)]">
        Recovery: Data Sources → Employee Directory. Disabled or unconfigured
        optional sources do not affect SAP lookup health. Freshness reflects the
        last successful read, not current filesystem availability.
      </p>
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
  onConfigure: () => void
}) {
  const enabled = draft.features?.employee_directory ?? false
  return (
    <section className="settings-card space-y-4">
      <h2 className="settings-subheading">
        <BookUser size={18} aria-hidden="true" />
        Employee Directory
      </h2>
      <p>
        Optionally enrich SAP users with employee and manager information from a
        local Active Directory CSV. SAP role and transaction investigation
        remains available without this feature.
      </p>
      <button
        className="settings-secondary-button"
        role="switch"
        aria-label="Employee Directory feature"
        aria-checked={enabled}
        onClick={() =>
          onChange({ ...draft, features: { employee_directory: !enabled } })
        }
      >
        <StatusPill enabled={enabled} />
      </button>
      <p className="text-sm">
        Configuration:{' '}
        {draft.employee_csv_path ? 'CSV configured' : 'Not configured'} ·
        Dependency: SAP email from User–Role Mapping for identity enrichment.
        Disabling preserves the source and imported records.
      </p>
      <button className="settings-secondary-button" onClick={onConfigure}>
        Configure Employee Directory
      </button>
      <DirectoryDiagnostics />
    </section>
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
        <Search size={16} aria-hidden="true" />
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
      {detail.isError && (
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
}: {
  revision: number
  savedPath: string
  dirty: boolean
  onImported: () => Promise<void>
}) {
  const [path, setPath] = useState(savedPath),
    [preview, setPreview] = useState<
      (Report & { digest: string; samples: Employee[] }) | null
    >(null),
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
      predicate: (q) => String(q.queryKey[0]).includes('employee'),
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
          Local Active Directory export · 16 required columns · UTF-8 (BOM
          supported) · semicolon delimiter. Preview and confirm before replacing
          the directory. No upload or managed CSV copy.
        </p>
        <label className="block">
          Employee Directory CSV location
          <input
            className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--surface2)] border-[var(--border)] text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
            value={path}
            onChange={(e) => {
              setPath(e.target.value)
              setPreview(null)
            }}
          />
        </label>
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
                  await apiRequest('/api/employees/clear', 'POST', {
                    path: savedPath,
                    revision,
                  })
                  setPreview(null)
                  await refresh()
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
                  await apiRequest('/api/employees/import', 'POST', {
                    path,
                    digest: preview.digest,
                    revision,
                  })
                  setPreview(null)
                  await refresh()
                })
              }
            >
              Confirm directory replacement
            </button>
          </section>
        )}
      </section>
      <DirectoryDiagnostics />
      <EmployeeBrowser />
    </div>
  )
}
