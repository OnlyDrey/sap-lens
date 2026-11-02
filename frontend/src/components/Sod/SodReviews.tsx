import {SodQueueBulk} from './SodQueueBulk'
import {SAPUserLink} from '@/components/Shared/SAPUserLink'
import { Kpi } from '@/components/Shared/Kpi'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ContextInfo, type UserQueueRow } from '@/api/sod'
import { useHistoryValue } from '@/hooks/useViewHistory'
import { Button } from '@/components/Shared/Button'
import { UserGroupCell } from '@/components/Shared/UserGroup'
import { ArrowUpDown, ArrowDown, ArrowUp, ClipboardCheck, ListChecks, Wrench } from 'lucide-react'
import { ErrorState, DataTable, EmptyState, LoadingState } from '@/components/Shared/Presentation'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Pagination } from '@/components/Access/Shared'
import { announceExport } from '@/lib/exportNotice'
import { CoverageNotice, SodFilters, keepWithinContext, useFilterChangeReset, useSodContext, useSodFilters, useSodSubject } from './SodShared'
import { stateTone } from '@/lib/kpiTone'
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
    [busy, setBusy] = useState(false),[bulkOpen,setBulkOpen]=useState(false)
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
  const sort=String(filters.queue_sort||''),descending=filters.descending===true
  const heading=(key:string,label:string)=><th aria-sort={sort===key?(descending?'descending':'ascending'):undefined}><button type="button" className="inline-flex items-center gap-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus" aria-label={`Sort by ${label}`} onClick={()=>{reset();setFiltersState({...filters,queue_sort:key,descending:sort===key?!descending:false})}}>{label}{sort===key?(descending?<ArrowDown size={13} aria-hidden="true"/>:<ArrowUp size={13} aria-hidden="true"/>):<ArrowUpDown size={13} aria-hidden="true"/>}</button></th>
  const part = (value: { total: number; decided: number }) => (value.total ? `${value.decided}/${value.total}` : '–')
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD review work queue">
      <CoverageNotice info={data} />
      <SodFilters view="sod_queue" filters={filters} setFilters={(value) => { reset(); setFiltersState(value) }}
        fields={['group', 'username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'category', 'validity']}
        actions={<><Button onClick={()=>setBulkOpen(true)} disabled={!data?.reviewable||!data.total}>Bulk review</Button><ExportCSVButton loading={busy} disabled={!data?.total} onClick={() => void exportCsv()} title="Exports every review item for the filtered users with its decision." /></>}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <section className="sod-tiles" aria-label="Review progress">
          {PROGRESS.map(([value, label]) => <Kpi key={value} label={label} value={(data.counts[value || 'all'] ?? 0).toLocaleString()} tone={stateTone(label, data.counts[value || 'all'] ?? 0)} active={progress === value} onClick={() => { reset(); setProgress(value) }} />)}
        </section>
        <p className="ui-description">One row per SAP user. Completion covers unique role, activity and risk access-review items in the selected scope, across pages. Current role/activity decisions can provide derived coverage; formal acceptance remains explicit. Open Review shows the same scope and provenance.</p>
        {data.items.length ? <DataTable caption="SoD review work queue" tableClassName="sod-config-table">
          <thead><tr>{heading('username','SAP user')}{heading('group','SAP User Group')}{heading('progress','Progress')}{heading('activity','Activities')}{heading('assignment','Role assignments')}{heading('risk','Risk access review')}{heading('acceptance','Formal acceptance')}{heading('removal','Removal recommendations')}<th>Open</th></tr></thead>
          <tbody>{data.items.map((row) => (
            <tr key={row.user}>
              <td><SAPUserLink username={row.user} /></td>
              <td><UserGroupCell groups={row.groups} /></td>
              <td><div className="flex items-center gap-2 whitespace-nowrap"><progress className="w-24 max-w-full" max={Math.max(row.total, 1)} value={row.decided} aria-label={`${row.user} decided ${row.decided} of ${row.total}`} /><span className="text-xs">{row.decided}/{row.total}</span></div>{row.removal > 0 && <p className="mt-1 text-xs text-muted">{row.removal} removal recommended</p>}</td>
              <td>{part(row.activity)}</td>
              <td>{part(row.assignment)}</td>
              <td>{part(row.acceptance)}</td><td>{part(row.formal_acceptance)}</td><td>{row.removal||'–'}</td>
              <td><Button variant="primary" size="compact" onClick={() => setSubject({ user: row.user })} aria-label={`Open review for ${row.user}`}><ClipboardCheck size={14} aria-hidden="true" />Open review</Button></td>
            </tr>))}</tbody>
        </DataTable> : <EmptyState>Nothing matches this queue scope. Results describe imported evidence only; missing sources are not proof of no conflict.</EmptyState>}
        <Pagination label="Queue pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} />
      </>}
      </SodFilters>
      {bulkOpen&&<SodQueueBulk context={context} filters={filters} onClose={()=>setBulkOpen(false)}/>}
    </section>
  )
}
