import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ContextInfo, type QueueItem } from '@/api/sod'
import { useHistoryValue } from '@/hooks/useViewHistory'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { ErrorState, DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { Checkbox } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Pagination } from '@/components/Access/Shared'
import { formatTimestamp } from '@/lib/dateFormat'
import { AlertNote, ContextBar, CoverageNotice, SodFilters, invalidateSod, KIND_LABEL, LifecycleBadge, useSodContext, useSodFilters, useSodSubject } from './SodShared'
import { DecisionForm, type FormState } from './SodInvestigation'
import { RemediationView } from './SodRemediation'

const STATUSES = ['Pending', 'Reviewed', 'Conditional', 'Removal required', 'Rejected', 'Risk acceptance pending', 'Awaiting approval', 'Outdated', 'Resolved', 'Historical']
interface Result extends ContextInfo { items: QueueItem[]; total: number; counts: Record<string, number>; offset: number; limit: number }
const itemKey = (item: QueueItem) => `${item.kind}:${item.key}`

export function SodReviews() {
  const [tab, setTab] = useHistoryValue('sodReviews')
  return (
    <ContentTabs label="Review areas" value={tab || 'queue'} onChange={(value) => setTab(value as 'queue' | 'remediation')} items={[{ value: 'queue', label: 'Work queue' }, { value: 'remediation', label: 'Remediation' }]}>
      {(tab || 'queue') === 'queue' ? <Queue /> : <RemediationView />}
    </ContentTabs>
  )
}

function Queue() {
  const qc = useQueryClient(),
    [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('queue'),
    [status, setStatus] = useState(''),
    [kind, setKind] = useState(''),
    [offset, setOffset] = useState(0),
    [picked, setPicked] = useState<Record<string, QueueItem>>({}),
    [batch, setBatch] = useState<FormState | null>(null),
    [, setSubject] = useSodSubject(),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false)
  const reset = () => { setOffset(0); setPicked({}) }
  const params = scopeParams(context, filters, { status, kind, offset, limit: 50 })
  const result = useQuery({ queryKey: ['sod-queue', params.toString()], queryFn: () => sod<Result>('/api/sod/queue', params) })
  const data = result.data
  const selected = Object.values(picked)
  const sameKind = selected.length > 0 && selected.every((item) => item.kind === selected[0].kind)
  const exportCsv = async () => {
    setBusy(true)
    setMessage('')
    try {
      const name = await downloadFile('/api/sod/queue/export', { params: scopeParams(context, filters, { status, kind }), namePattern: EXPORT_NAME, kind: 'csv' })
      setMessage(name ? `Exported ${name}.` : 'Export cancelled.')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Export failed.')
    } finally {
      setBusy(false)
    }
  }
  const toggle = (item: QueueItem) => setPicked((previous) => { const next = { ...previous }; if (next[itemKey(item)]) delete next[itemKey(item)]; else next[itemKey(item)] = item; return next })
  const decidable = (item: QueueItem) => !!data?.reviewable && item.lifecycle !== 'Historical' && item.lifecycle !== 'Resolved'
  const openItem = (item: QueueItem) => setSubject(item.kind === 'acceptance' ? { user: item.user, risk: item.ref } : item.kind === 'activity' ? { user: item.user, activity: item.ref } : { user: item.user, ...(item.risks[0] ? { risk: item.risks[0] } : {}) })
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD review work queue">
      <ContextBar info={data} />
      <CoverageNotice info={data} />
      <SodFilters view="sod_queue" filters={filters} setFilters={(value) => { reset(); setFiltersState(value) }}
        fields={['group', 'username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'category', 'criticality', 'validity']}
        actions={<>
          <Select aria-label="Review type" value={kind} onChange={(event) => { reset(); setKind(event.target.value) }}>
            <option value="">All review types</option>
            <option value="activity">Activity reviews</option>
            <option value="assignment">Role assignment reviews</option>
            <option value="acceptance">Risk acceptance</option>
          </Select>
          <ExportCSVButton loading={busy} disabled={!data?.total} onClick={() => void exportCsv()} title="Exports the filtered queue with decisions." />
        </>}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <Toolbar aria-label="Review status">
          <Button variant={status ? 'secondary' : 'primary'} aria-pressed={!status} onClick={() => { reset(); setStatus('') }}>All</Button>
          {STATUSES.map((name) => <Button key={name} variant={status === name ? 'primary' : 'secondary'} aria-pressed={status === name} onClick={() => { reset(); setStatus(name) }}>{name}: {data.counts[name] ?? 0}</Button>)}
        </Toolbar>
        <p className="ui-description">Activities are reviewed once per user across all risks they contribute to. Role assignments are reviewed separately, and risk acceptance is a third, independent decision. Batch review applies one decision only to the rows you select.</p>
        {message && <p role="status">{message}</p>}
        {selected.length > 0 && <Toolbar aria-label="Batch review">
          <StatusBadge>{selected.length} selected</StatusBadge>
          {sameKind ? <Button variant="primary" onClick={() => setBatch({ kind: selected[0].kind, heading: `Batch ${KIND_LABEL[selected[0].kind].toLowerCase()} review (${selected.length})`, items: selected.map((item) => ({ key: item.key, user: item.user, ref: item.ref, evidence_version: item.evidence_version })) })}>Review selected</Button>
            : <AlertNote>Select rows of one review type to review them together.</AlertNote>}
          <Button variant="ghost" onClick={() => setPicked({})}>Clear selection</Button>
        </Toolbar>}
        {data.items.length ? <DataTable caption="SoD review work queue">
          <thead><tr><th>Select</th><th>SAP user</th><th>Review type</th><th>Reference</th><th>Status</th><th>Decision</th><th>Open</th></tr></thead>
          <tbody>{data.items.map((item) => (
            <tr key={itemKey(item)}>
              <td>{decidable(item) && <Checkbox checked={!!picked[itemKey(item)]} onChange={() => toggle(item)} aria-label={`Select ${item.user} ${item.ref}`}><span className="sr-only">Select</span></Checkbox>}</td>
              <td>{item.user}</td>
              <td>{KIND_LABEL[item.kind]}</td>
              <td><span className="sod-break">{item.ref}</span><p className="text-xs text-muted">{item.risks.join(', ')}</p></td>
              <td><LifecycleBadge value={item.lifecycle} /></td>
              <td className="text-xs">{item.event ? <>{item.event.decision}<p>{item.event.reviewer} · {formatTimestamp(item.event.timestamp)}</p></> : 'No decision yet'}</td>
              <td>{item.lifecycle === 'Historical' || item.lifecycle === 'Resolved' ? <span className="text-xs text-muted">No longer detected</span> : <Button onClick={() => openItem(item)} aria-label={`Open ${item.user} ${item.ref}`}>Open</Button>}</td>
            </tr>))}</tbody>
        </DataTable> : <EmptyState>Nothing matches this queue scope. Results describe imported evidence only; missing sources are not proof of no conflict.</EmptyState>}
        <Pagination label="Queue pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} />
      </>}
      </SodFilters>
      {batch && data && <Dialog title={batch.heading} onClose={() => setBatch(null)} footer={<Button variant="ghost" onClick={() => setBatch(null)}>Close</Button>}>
        <DecisionForm form={batch} subject={data} onCancel={() => setBatch(null)} onSaved={async () => { setBatch(null); setPicked({}); await invalidateSod(qc) }} />
      </Dialog>}
    </section>
  )
}
