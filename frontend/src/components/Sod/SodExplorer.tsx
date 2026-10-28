import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ContextInfo, type Lifecycle } from '@/api/sod'
import { useHistoryValue, type SodExplorerTable } from '@/hooks/useViewHistory'
import { Button } from '@/components/Shared/Button'
import { Card, ErrorState, DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { Pagination } from '@/components/Access/Shared'
import { formatDate } from '@/lib/dateFormat'
import { ConflictView } from './SodConflicts'
import { ContextBar, CoverageNotice, FilterBar, LifecycleBadge, useSodContext, useSodFilters, useSodSubject } from './SodShared'

type TableName = Exclude<SodExplorerTable, 'roles'>
interface Row {
  user?: string; risk_id?: string; criticality?: string; category?: string; groups?: string[]; activities?: string[] | string; roles?: string[] | number; acceptance?: Lifecycle
  activity?: string; risks?: string[]; tcodes?: string[]; duplicate?: boolean; decision?: Lifecycle; id?: string; role?: string; valid_from?: string | null; valid_to?: string | null
  interval_status?: string | null; user_group?: string; users?: number; catalogue_roles?: string[]
}
interface Result extends ContextInfo { items: Row[]; total: number; offset: number; limit: number }
const LABELS: Record<TableName, string> = { user_risk: 'User risk table', user_activity: 'User activity table', access_list: 'Access list', lookup: 'User & role lookup' }
const list = (value?: string[] | string | number) => (Array.isArray(value) ? value.join(', ') : String(value ?? ''))

export function SodExplorer() {
  const [table, setTable] = useHistoryValue('sodExplorer'),
    current = table || 'user_risk'
  return (
    <ContentTabs label="Access Explorer views" value={current} onChange={(value) => setTable(value as SodExplorerTable)}
      items={[...(Object.keys(LABELS) as TableName[]).map((value) => ({ value, label: LABELS[value] })), { value: 'roles', label: 'Role conflicts' }]}>
      {current === 'roles' ? <ConflictView key="roles" kind="roles" /> : <ExplorerTable key={current} table={current} onTable={(value) => setTable(value)} />}
    </ContentTabs>
  )
}

function ExplorerTable({ table, onTable }: { table: TableName; onTable: (value: SodExplorerTable) => void }) {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('explorer'),
    [offset, setOffset] = useState(0),
    [, setSelected] = useSodSubject(),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false)
  const params = scopeParams(context, filters, { offset, limit: 50 })
  const result = useQuery({ queryKey: ['sod-explorer', table, params.toString()], queryFn: () => sod<Result>(`/api/sod/explorer/${table}`, params) })
  const data = result.data
  const download = async (path: string, namePattern: RegExp, extra: Record<string, string> = {}) => {
    setBusy(true)
    setMessage('')
    try {
      const name = await downloadFile(path, { params: scopeParams(context, filters, extra), namePattern, kind: 'csv' })
      setMessage(name ? `Exported ${name}.` : 'Export cancelled.')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Export failed.')
    } finally {
      setBusy(false)
    }
  }
  const showUsers = (role: string) => {
    setFiltersState({ ...filters, role })
    onTable('access_list')
  }
  return (
    <section className="grid min-w-0 gap-4" aria-label={LABELS[table]}>
      <ContextBar info={data} />
      <CoverageNotice info={data} />
      <Card aria-label="Explorer filters"><FilterBar view="sod_explorer" filters={filters} setFilters={(value) => { setOffset(0); setFiltersState(value) }} /></Card>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <Toolbar>
          <h2 className="text-base font-semibold">{data.total} {table === 'lookup' ? 'roles' : 'rows'}</h2>
          <ExportCSVButton loading={busy} disabled={!data.total} onClick={() => void download(`/api/sod/explorer/${table}/export`, EXPORT_NAME)} title="Exports every filtered row across pages." />
          {table === 'user_risk' && context === 'current' && <Button disabled={busy || !data.total} variant="outline" onClick={() => void download('/api/sod/analysis/export', /^sap-lens-sod-users-findings-\d{4}-\d{2}-\d{2}\.csv$/, { kind: 'users' })}>Export evidence CSV</Button>}
        </Toolbar>
        <p className="ui-description">Trace User → Risk → Activity → Transaction → Role → Assignment. Select a row to investigate; from the lookup, show the users behind a role.</p>
        {message && <p role="status">{message}</p>}
        {data.items.length ? <DataTable caption={LABELS[table]}>
          {table === 'user_risk' && <><thead><tr><th>SAP user</th><th>Risk</th><th>Activities</th><th>Roles</th><th>Risk acceptance</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={`${row.user}:${row.risk_id}`}><td>{row.user}<p className="text-xs text-muted">{list(row.groups)}</p></td><td>{row.risk_id}<p className="text-xs text-muted">{row.criticality}{row.category ? ` · ${row.category}` : ''}</p></td><td>{list(row.activities)}</td><td className="sod-break">{list(row.roles)}</td><td><LifecycleBadge value={row.acceptance || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, risk: row.risk_id })} aria-label={`Investigate ${row.user} ${row.risk_id}`}>Investigate</Button></td></tr>)}</tbody></>}
          {table === 'user_activity' && <><thead><tr><th>SAP user</th><th>Activity</th><th>Risks</th><th>Transactions</th><th>Role assignments</th><th>Review</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={`${row.user}:${row.activity}`}><td>{row.user}</td><td>{row.activity}</td><td>{list(row.risks)}</td><td>{list(row.tcodes)}</td><td>{String(row.roles)}{row.duplicate && <StatusBadge tone="info">Overlap</StatusBadge>}</td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, activity: row.activity })} aria-label={`Investigate ${row.user} ${row.activity}`}>Investigate</Button></td></tr>)}</tbody></>}
          {table === 'access_list' && <><thead><tr><th>SAP user</th><th>Role assignment</th><th>Validity</th><th>Activities / risks</th><th>Review</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={`${row.user}:${row.id}`}><td>{row.user}<p className="text-xs text-muted">{row.user_group}</p></td><td className="sod-break">{row.role}</td><td>{row.interval_status && <AssignmentStatus value={row.interval_status} />}<p>{formatDate(row.valid_from)} → {formatDate(row.valid_to)}</p></td><td>{list(row.activities)}<p className="text-xs text-muted">{list(row.risks)}</p></td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, activity: Array.isArray(row.activities) ? row.activities[0] : undefined })} aria-label={`Investigate ${row.user} ${row.role}`}>Investigate</Button></td></tr>)}</tbody></>}
          {table === 'lookup' && <><thead><tr><th>Assigned role</th><th>Users</th><th>Activities</th><th>Risks</th><th>Trace</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={row.role}><td className="sod-break">{row.role}<p className="text-xs text-muted">{list(row.catalogue_roles)}</p></td><td>{row.users}</td><td>{list(row.activities)}</td><td>{list(row.risks)}</td>
              <td><Button onClick={() => showUsers(row.role!)} aria-label={`Show users with ${row.role}`}>Show users</Button></td></tr>)}</tbody></>}
        </DataTable> : <EmptyState>No rows match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}
        <Pagination label="Explorer pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} />
      </>}
    </section>
  )
}
