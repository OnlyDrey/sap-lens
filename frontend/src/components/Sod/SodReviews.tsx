import { Kpi } from '@/components/Shared/Kpi'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ContextInfo, type UserQueueRow } from '@/api/sod'
import { useHistoryValue } from '@/hooks/useViewHistory'
import { Button } from '@/components/Shared/Button'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { ClipboardCheck, ListChecks, Wrench } from 'lucide-react'
import { ErrorState, DataTable, EmptyState, LoadingState } from '@/components/Shared/Presentation'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Pagination } from '@/components/Access/Shared'
import { announceExport } from '@/lib/exportNotice'
import { CoverageNotice, SodFilters, keepWithinContext, useFilterChangeReset, useSodContext, useSodFilters, useSodSubject } from './SodShared'
import { RemediationView } from './SodRemediation'


export function SodReviews() {
  const [tab, setTab] = useHistoryValue('sodReviews')
  return (
    <ContentTabs label="Review areas" value={tab || 'queue'} onChange={(value) => setTab(value as 'queue' | 'remediation')} items={[{ value: 'queue', label: 'Work queue', icon: <ListChecks size={16} aria-hidden="true" /> }, { value: 'remediation', label: 'Remediation', icon: <Wrench size={16} aria-hidden="true" /> }]}>
      {(tab || 'queue') === 'queue' ? <Queue /> : <RemediationView />}
    </ContentTabs>
  )
}

const PROGRESS = [['', 'All users'], ['outstanding', 'Needs review'], ['complete', 'Complete'], ['removal', 'Removal recommended']] as const
interface UserResult extends ContextInfo { items: UserQueueRow[]; total: number; counts: Record<string, number>; offset: number; limit: number }

/** One row per SAP user. Each review type keeps its own progress; Open Review loads the unified workspace. */
function Queue() {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('queue'),
    [progress, setProgress] = useState(''),
    [offset, setOffset] = useState(0),
    [, setSubject] = useSodSubject(),
    [busy, setBusy] = useState(false)
  const reset = () => setOffset(0)
  useFilterChangeReset(filters, reset)
  const params = scopeParams(context, filters, { progress, offset, limit: 50 })
  const result = useQuery({ queryKey: ['sod-queue', 'users', params.toString()], queryFn: () => sod<UserResult>('/api/sod/queue/users', params), placeholderData: keepWithinContext(['sod-queue', 'users', params.toString()], params) as never })
  const data = result.data
  const exportCsv = async () => {
    setBusy(true)
    try {
      const name = await downloadFile('/api/sod/queue/export', { params: scopeParams(context, filters), namePattern: EXPORT_NAME, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (cause) {
      announceExport({ kind: 'error', message: cause instanceof Error ? cause.message : 'Export failed.' })
    } finally {
      setBusy(false)
    }
  }
  const part = (value: { total: number; decided: number }) => (value.total ? `${value.decided}/${value.total}` : '–')
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD review work queue">
      <CoverageNotice info={data} />
      <SodFilters view="sod_queue" filters={filters} setFilters={(value) => { reset(); setFiltersState(value) }}
        fields={['group', 'username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'category', 'validity']}
        actions={<ExportCSVButton loading={busy} disabled={!data?.total} onClick={() => void exportCsv()} title="Exports every review item for the filtered users with its decision." />}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <section className="sod-tiles" aria-label="Review progress">
          {PROGRESS.map(([value, label]) => <Kpi key={value} label={label} value={(data.counts[value || 'all'] ?? 0).toLocaleString()} active={progress === value} onClick={() => { reset(); setProgress(value) }} />)}
        </section>
        <p className="ui-description">One row per SAP user. Activity review, role assignment review and risk acceptance are independent decisions with their own progress. Open Review shows all three for the user.</p>
        {data.items.length ? <DataTable caption="SoD review work queue" tableClassName="sod-config-table">
          <thead><tr><th>SAP user</th><th>Progress</th><th>Activities</th><th>Role assignments</th><th>Risk acceptance</th><th>Open</th></tr></thead>
          <tbody>{data.items.map((row) => (
            <tr key={row.user}>
              <td><RoleIdentifier value={row.user} label="SAP username" />{row.removal > 0 && <p className="text-xs text-muted">{row.removal} removal recommended</p>}</td>
              <td><progress max={Math.max(row.total, 1)} value={row.decided} aria-label={`${row.user} decided ${row.decided} of ${row.total}`} /> <span className="text-xs">{row.decided}/{row.total}</span></td>
              <td>{part(row.activity)}</td>
              <td>{part(row.assignment)}</td>
              <td>{part(row.acceptance)}</td>
              <td><Button variant="primary" size="compact" onClick={() => setSubject({ user: row.user })} aria-label={`Open review for ${row.user}`}><ClipboardCheck size={14} aria-hidden="true" />Open review</Button></td>
            </tr>))}</tbody>
        </DataTable> : <EmptyState>Nothing matches this queue scope. Results describe imported evidence only; missing sources are not proof of no conflict.</EmptyState>}
        <Pagination label="Queue pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} />
      </>}
      </SodFilters>
    </section>
  )
}
