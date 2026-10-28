import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ContextInfo, type Filters, type Lifecycle } from '@/api/sod'
import { useHistoryValue, type SodExplorerTable } from '@/hooks/useViewHistory'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/Shared/Button'
import { ErrorState, DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Select } from '@/components/Shared/Select'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { Pagination } from '@/components/Access/Shared'
import { announceExport } from '@/lib/exportNotice'
import { formatDate } from '@/lib/dateFormat'
import { ConflictView } from './SodConflicts'
import { SodPill } from '@/lib/sodAppearance'
import { type FilterField, ContextBar, SodArea, CoverageNotice, SodFilters, LifecycleBadge, useSodContext, useSodFilters, useSodSubject } from './SodShared'

type TableName = Exclude<SodExplorerTable, 'roles'>
interface Row {
  user?: string; risk_id?: string; criticality?: string; category?: string; groups?: string[]; activities?: string[] | string; roles?: string[] | number; acceptance?: Lifecycle
  activity?: string; risks?: string[]; tcodes?: string[]; duplicate?: boolean; decision?: Lifecycle; id?: string; role?: string; valid_from?: string | null; valid_to?: string | null
  interval_status?: string | null; user_group?: string; users?: number; catalogue_roles?: string[]
}
interface Result extends ContextInfo { items: Row[]; total: number; offset: number; limit: number }
const COMMON: FilterField[] = ['username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'validity']
const FIELDS: Record<string, FilterField[]> = {
  user_risk: [...COMMON, 'group', 'category', 'criticality', 'activity_decision', 'assignment_decision', 'acceptance'],
  user_activity: [...COMMON, 'group', 'category', 'criticality', 'activity_decision', 'assignment_decision'],
  access_list: [...COMMON, 'group', 'activity_decision', 'assignment_decision'],
  lookup: COMMON,
}
const LABELS: Record<TableName, string> = { user_risk: 'User risk table', user_activity: 'User activity table', access_list: 'Access list', lookup: 'User & role lookup' }
const pills = (kind: 'risk' | 'activity', value?: string[] | string) => <span className="id-pill-list">{(Array.isArray(value) ? value : value ? [value] : []).map((item) => <SodPill key={item} kind={kind} value={item} />)}</span>
const list = (value?: string[] | string | number) => (Array.isArray(value) ? value.join(', ') : String(value ?? ''))

const TABS: { value: string; label: string }[] = [
  { value: 'user_risk', label: 'Users' }, { value: 'access_list', label: 'Assignments' }, { value: 'lookup', label: 'Roles' }, { value: 'roles', label: 'Role conflicts' },
]

/** Users (grouped by risk or activity), Assignments and Roles replace four near-duplicate tables; catalogue Role conflicts stay a distinct mode. */
export function SodExplorer() {
  const [table, setTable] = useHistoryValue('sodExplorer'),
    current = table || 'user_risk',
    tab = current === 'user_activity' ? 'user_risk' : current
  return (
    <ContentTabs label="Access Explorer views" value={tab} onChange={(value) => setTable(value as SodExplorerTable)} items={TABS}>
      {current === 'roles' ? <ConflictView key="roles" kind="roles" /> : <ExplorerTable key={current} table={current} onTable={(value) => setTable(value)} />}
    </ContentTabs>
  )
}

/** Compact row with an expandable evidence line; the toggle keeps the table scannable while preserving traceability. */
function Expandable({ id, label, summary, children, expanded, toggle }: { id: string; label: string; summary: ReactNode; children: ReactNode; expanded: boolean; toggle: (id: string) => void }) {
  return (
    <div className="sod-expandable">
      <button type="button" className="sod-expand-toggle" aria-expanded={expanded} aria-label={`${expanded ? 'Hide' : 'Show'} evidence for ${label}`} onClick={() => toggle(id)}>
        {expanded ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}{summary}
      </button>
      {expanded && <div className="sod-expandable-body">{children}</div>}
    </div>
  )
}

function AssignedUsers({ role, context, filters }: { role: string; context: string; filters: Filters }) {
  const params = scopeParams(context, { ...filters, role }, { limit: 25 }),
    result = useQuery({ queryKey: ['sod-explorer', 'access_list', 'assigned', params.toString()], queryFn: () => sod<Result>('/api/sod/explorer/access_list', params) })
  if (result.isError) return <p role="alert">Assigned users could not be loaded.</p>
  if (!result.data) return <p role="status">Loading assigned users…</p>
  return <ul className="sod-assigned" aria-label={`Users with ${role}`}>{result.data.items.map((row) => <li key={`${row.user}:${row.id}`}>{row.user}{row.user_group ? ` (${row.user_group})` : ''} · {formatDate(row.valid_from)} → {formatDate(row.valid_to)}</li>)}{result.data.total > result.data.items.length && <li className="text-muted">+{result.data.total - result.data.items.length} more in Assignments</li>}</ul>
}

function ExplorerTable({ table, onTable }: { table: TableName; onTable: (value: SodExplorerTable) => void }) {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('explorer'),
    [offset, setOffset] = useState(0),
    [, setSelected] = useSodSubject(),
    [busy, setBusy] = useState(false),
    [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (id: string) => setExpanded((previous) => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const params = scopeParams(context, filters, { offset, limit: 50 })
  const result = useQuery({ queryKey: ['sod-explorer', table, params.toString()], queryFn: () => sod<Result>(`/api/sod/explorer/${table}`, params) })
  const data = result.data
  const download = async (path: string, namePattern: RegExp, extra: Record<string, string> = {}) => {
    setBusy(true)
    try {
      const name = await downloadFile(path, { params: scopeParams(context, filters, extra), namePattern, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (cause) {
      announceExport({ kind: 'error', message: cause instanceof Error ? cause.message : 'Export failed.' })
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
      <SodFilters view="sod_explorer" filters={filters} setFilters={(value) => { setOffset(0); setFiltersState(value) }} fields={FIELDS[table]}
        sorts={[{ value: 'subject', label: 'Name' }]}
        actions={<>
          {(table === 'user_risk' || table === 'user_activity') && <Select aria-label="Group users by" value={table} onChange={(event) => onTable(event.target.value as SodExplorerTable)}><option value="user_risk">Grouped by risk</option><option value="user_activity">Grouped by activity</option></Select>}
          <ExportCSVButton loading={busy} disabled={!data?.total} onClick={() => void download(`/api/sod/explorer/${table}/export`, EXPORT_NAME)} title="Exports every filtered row across pages." />
          {table === 'user_risk' && context === 'current' && <Button disabled={busy || !data?.total} variant="outline" onClick={() => void download('/api/sod/analysis/export', /^sap-lens-sod-users-findings-\d{4}-\d{2}-\d{2}\.csv$/, { kind: 'users' })}>Export evidence CSV</Button>}
        </>}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <Toolbar>
          <h2 className="text-base font-semibold">{data.total} {table === 'lookup' ? 'roles' : 'rows'}</h2>
        </Toolbar>
        <p className="ui-description">Trace User → Risk → Activity → Transaction → Role → Assignment. Select a row to investigate; from the lookup, show the users behind a role.</p>
        {data.items.length ? <DataTable caption={LABELS[table]}>
          {table === 'user_risk' && <><thead><tr><th>SAP user</th><th>Risk</th><th>Activities</th><th>Evidence</th><th>Risk acceptance</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => { const id = `${row.user}:${row.risk_id}`; return <tr key={id}><td>{row.user}<p className="text-xs text-muted">{list(row.groups)}</p></td><td>{pills('risk', row.risk_id)}{row.category && <p><SodArea value={row.category} /></p>}</td><td>{pills('activity', row.activities)}</td>
              <td><Expandable id={id} label={`${row.user} ${row.risk_id}`} expanded={expanded.has(id)} toggle={toggle} summary={`${Array.isArray(row.roles) ? row.roles.length : row.roles} roles`}><p className="sod-break">{list(row.roles)}</p></Expandable></td>
              <td><LifecycleBadge value={row.acceptance || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, risk: row.risk_id })} aria-label={`Investigate ${row.user} ${row.risk_id}`}>Investigate</Button></td></tr> })}</tbody></>}
          {table === 'user_activity' && <><thead><tr><th>SAP user</th><th>Activity</th><th>Risks</th><th>Evidence</th><th>Review</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => { const id = `${row.user}:${row.activity}`; return <tr key={id}><td>{row.user}</td><td>{pills('activity', row.activity)}</td><td>{pills('risk', row.risks)}</td>
              <td><Expandable id={id} label={`${row.user} ${row.activity}`} expanded={expanded.has(id)} toggle={toggle} summary={`${String(row.roles)} role assignment${row.roles === 1 ? '' : 's'}`}><p>Transactions: {list(row.tcodes)}</p></Expandable>{row.duplicate && <StatusBadge tone="info">Overlap</StatusBadge>}</td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, activity: row.activity })} aria-label={`Investigate ${row.user} ${row.activity}`}>Investigate</Button></td></tr> })}</tbody></>}
          {table === 'access_list' && <><thead><tr><th>SAP user</th><th>Role assignment</th><th>Validity</th><th>Activities / risks</th><th>Review</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={`${row.user}:${row.id}`}><td>{row.user}<p className="text-xs text-muted">{row.user_group}</p></td><td className="sod-break">{row.role}</td><td>{row.interval_status && <AssignmentStatus value={row.interval_status} />}<p>{formatDate(row.valid_from)} → {formatDate(row.valid_to)}</p></td><td>{pills('activity', row.activities)}{pills('risk', row.risks)}</td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td><Button onClick={() => setSelected({ user: row.user!, activity: Array.isArray(row.activities) ? row.activities[0] : undefined })} aria-label={`Investigate ${row.user} ${row.role}`}>Investigate</Button></td></tr>)}</tbody></>}
          {table === 'lookup' && <><thead><tr><th>Assigned role</th><th>Users</th><th>Activities</th><th>Risks</th><th>Trace</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={row.role}><td className="sod-break">{row.role}<p className="text-xs text-muted">{list(row.catalogue_roles)}</p></td>
              <td><Expandable id={row.role!} label={row.role!} expanded={expanded.has(row.role!)} toggle={toggle} summary={`${row.users} user${row.users === 1 ? '' : 's'}`}><AssignedUsers role={row.role!} context={context} filters={filters} /></Expandable></td>
              <td>{pills('activity', row.activities)}</td><td>{pills('risk', row.risks)}</td>
              <td><Button onClick={() => showUsers(row.role!)} aria-label={`Show users with ${row.role}`}>Show users</Button></td></tr>)}</tbody></>}
        </DataTable> : <EmptyState>No rows match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}
        <Pagination label="Explorer pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} />
      </>}
      </SodFilters>
    </section>
  )
}
