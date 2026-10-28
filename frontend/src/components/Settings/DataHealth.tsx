import {SourceHealthSummary,useSourceEvidence} from './SourceStatus'
import { Button } from '@/components/Shared/Button'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, ChevronRight } from 'lucide-react'
import { apiRequest } from '@/api/client'
import { Pagination, QueryState } from '@/components/Access/Shared'
import { useViewHistory, userHref } from '@/hooks/useViewHistory'
interface Health {
  import_totals: Record<
    string,
    {
      parsed_rows: number | null
      unique_records: number | null
      duplicate_rows: number | null
    }
  >
  sources: {
    id: string
    name: string
    enabled: boolean
    configured: boolean
    available: boolean
    records: number | null
    snapshot: string
    last_successful: string | null
  }[]
  coverage: {
    label: string
    numerator: number | null
    denominator: number | null
    percent: number | null
  }[]
  findings: {
    id: string
    title: string
    severity: string
    count: number | null
    explanation: string
  }[]
  items: {
    identifier: string
    username?: string
    source: string
    destination: string
  }[]
  total: number
  validation_note: string
  directory_coverage_reason: string
}
export function DataHealth({
  onSource,
}: {
  onSource: (s: 'roles' | 'users' | 'employees' | 'sod') => void
}) {
  const [finding, setFinding] = useState(''),
    [offset, setOffset] = useState(0),
    { change } = useViewHistory()
  const result = useQuery({
    queryKey: ['data-health', finding, offset],
    queryFn: () =>
      apiRequest<Health>(
        `/api/data-health?${new URLSearchParams({ finding, offset: String(offset) })}`,
      ),
  })
  const sourceEvidence=useSourceEvidence('roles')
  const data = result.data
  return (
    <details className="settings-advanced">
      <summary className="flex items-center gap-2">
        <Activity size={17} />
        Data Health &amp; Coverage
      </summary>
      <QueryState loading={result.isFetching} error={result.error} />
      {data && (
        <div className="space-y-3 mt-3">
          <div className="health-source-grid">
            {data.sources.map((s) => (
              <article className="compact-health" key={s.id}>
                <h3 className="font-semibold">{s.name}</h3>
                {sourceEvidence.data?.sources.find(source=>source.id===s.id)?<SourceHealthSummary compact source={sourceEvidence.data.sources.find(source=>source.id===s.id)!}/>:<p>{s.available?'Validated data available':'Not loaded'} · {s.records??'—'} records · {s.snapshot}</p>}
                <Button
                  className="settings-secondary-button"
                  onClick={() =>
                    onSource(s.id as 'roles' | 'users' | 'employees' | 'sod')
                  }
                >
                  Source details <ChevronRight size={14} />
                </Button>
              </article>
            ))}
          </div>
          {data.coverage.map((c) => (
            <p key={c.label} className="text-sm">
              <strong>{c.label}</strong>:{' '}
              {c.numerator === null
                ? 'Unavailable'
                : `${c.numerator} / ${c.denominator} — ${c.percent === null ? 'No eligible records' : c.percent + '%'}`}
            </p>
          ))}
          {data.directory_coverage_reason && (
            <p className="text-sm">
              Directory coverage: {data.directory_coverage_reason}
            </p>
          )}
          <p className="text-sm text-[var(--muted)]">{data.validation_note}</p>
          {Object.entries(data.import_totals).map(
            ([name, counts]) =>
              counts.parsed_rows != null && (
                <p className="text-sm" key={name}>
                  {name === 'roles' ? 'Role Catalogue' : 'User Access'} import:{' '}
                  {counts.unique_records} / {counts.parsed_rows} unique source
                  rows; {counts.duplicate_rows} identical rows deduplicated.
                </p>
              ),
          )}
          <div className="health-findings">
            {data.findings.map((f) => (
              <Button
                className="settings-secondary-button text-left"
                key={f.id}
                disabled={f.count === null || f.count === 0}
                aria-pressed={finding === f.id}
                onClick={() => {
                  setFinding(f.id)
                  setOffset(0)
                }}
              >
                <span
                  className={`evidence-badge evidence-${f.severity === 'warning' ? 'warning' : 'neutral'}`}
                >
                  {f.severity}
                </span>
                {f.title} · {f.count ?? 'Unavailable'}
              </Button>
            ))}
          </div>
          {finding && (
            <section aria-label="Data Health finding records">
              <h3 className="font-semibold">
                {data.findings.find((f) => f.id === finding)?.title}
              </h3>
              <p className="text-sm">
                {data.findings.find((f) => f.id === finding)?.explanation}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th>Record</th>
                      <th>Source</th>
                      <th>Investigation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((r, i) => (
                      <tr key={i}>
                        <td>{r.identifier}</td>
                        <td>{r.source}</td>
                        <td>
                          {r.destination === 'user' ? (
                            <a
                              className="text-link"
                              href={userHref(r.username || r.identifier)}
                              onClick={(event) => {
                                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                                event.preventDefault()
                                change({
                                  settings: false,
                                  page: 'users',
                                  accessMode: 'directory',
                                  user: r.username || r.identifier,
                                })
                              }}
                            >
                              {r.username || r.identifier}
                            </a>
                          ) : (
                            <button
                              className="text-link"
                              onClick={() =>
                                change({
                                  settings: false,
                                  page: 'roles',
                                  detailRole: r.identifier,
                                })
                              }
                            >
                              Open role
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                label="Data Health records"
                offset={offset}
                total={data.total}
                limit={25}
                onChange={setOffset}
              />
            </section>
          )}
          <p className="text-sm text-[var(--muted)]">
            Directory missing emails, duplicate identifiers and manager
            relationships remain in Employee Directory source details. Technical
            errors and recovery remain in Health &amp; Diagnostics.
          </p>
        </div>
      )}
    </details>
  )
}
