import { Kpi } from '@/components/Shared/Kpi'
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type AssignmentPick, type AssignmentSelection, type BulkAction, type ContextInfo, type Filters, type Lifecycle } from '@/api/sod'
import { useHistoryValue, useViewHistory, type SodExplorerTable } from '@/hooks/useViewHistory'
import { ArrowUpRight, ListTree, ScanSearch, UsersRound } from 'lucide-react'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { ErrorState, DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Select } from '@/components/Shared/Select'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { PAGE_SIZES, Pagination } from '@/components/Access/Shared'
import { BulkToolbar, PageCheckbox, RowCheckbox, useBulkSelection } from '@/components/Shared/BulkSelection'
import { BulkReviewDialog } from './SodBulkReview'
import { announceExport } from '@/lib/exportNotice'
import { formatDate } from '@/lib/dateFormat'
import { ConflictView } from './SodConflicts'
import { SodPill } from '@/lib/sodAppearance'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { type FilterField, keepWithinContext, useFilterChangeReset, reviewStatusParam, SodArea, RoleCodeList, CoverageNotice, SodFilters, LifecycleBadge, useSodContext, useSodFilters, useSodSubject } from './SodShared'

type TableName = Exclude<SodExplorerTable, 'roles'>
interface Row {
  user?: string; risk_id?: string; criticality?: string; category?: string; groups?: string[]; activities?: string[] | string; roles?: string[] | number; acceptance?: Lifecycle
  activity?: string; risks?: string[]; tcodes?: string[]; duplicate?: boolean; decision?: Lifecycle; id?: string; role?: string; valid_from?: string | null; valid_to?: string | null
  interval_status?: string | null; user_group?: string; users?: number; catalogue_roles?: string[]; suffix?: string; evidence_version?: string
}
interface Progress { total: number; completed: number; pending: number; investigating: number; outdated: number; attention: number; removal: number }
interface Result extends ContextInfo { items: Row[]; total: number; offset: number; limit: number; progress?: Progress }
const COMMON: FilterField[] = ['username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'validity']
const FIELDS: Record<string, FilterField[]> = {
  user_risk: [...COMMON, 'group', 'category', 'activity_decision', 'assignment_decision', 'acceptance'],
  user_activity: [...COMMON, 'group', 'category', 'activity_decision', 'assignment_decision'],
  access_list: [...COMMON, 'group', 'review_status', 'assignment_decision'],
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

/** Opens the evidence of one row in a wide modal; the table stays a scannable summary. */
function EvidenceButton({ label, summary, onOpen }: { label: string; summary: ReactNode; onOpen: () => void }) {
  return <Button size="compact" aria-haspopup="dialog" aria-label={`Show evidence for ${label}`} onClick={onOpen}><ListTree size={14} aria-hidden="true" />{summary}</Button>
}

type Evidence =
  | { kind: 'roles'; user: string; risk: string; activities: string[]; roles: string[]; category?: string }
  | { kind: 'transactions'; user: string; activity: string; risks: string[]; tcodes: string[]; roles: number }
  | { kind: 'users'; role: string }

/** Wide evidence modal: a compact summary, a scrollable table and shortcuts to the user and to the investigation panel. */
function ExplorerEvidence({ evidence, context, filters, onClose, onInvestigate, onUser }: { evidence: Evidence; context: string; filters: Filters; onClose: () => void; onInvestigate: (user: string, risk?: string, activity?: string) => void; onUser: (user: string) => void }) {
  const title = evidence.kind === 'users' ? `Users with ${evidence.role}` : evidence.kind === 'roles' ? `Role evidence · ${evidence.user} · ${evidence.risk}` : `Transaction evidence · ${evidence.user} · ${evidence.activity}`
  const subject = evidence.kind === 'users' ? null : evidence.user
  return (
    <Dialog title={title} onClose={onClose}
      footer={subject ? <>
        <Button onClick={() => onUser(subject)}><ArrowUpRight size={16} aria-hidden="true" />Open SAP user</Button>
        <Button variant="primary" onClick={() => onInvestigate(subject, evidence.kind === 'roles' ? evidence.risk : undefined, evidence.kind === 'transactions' ? evidence.activity : undefined)}><ScanSearch size={16} aria-hidden="true" />Investigate</Button>
      </> : undefined}>
      {evidence.kind === 'roles' && <>
        <dl className="evidence-summary">
          <div><dt>SAP user</dt><dd><RoleIdentifier value={evidence.user} label="SAP username" /></dd></div>
          <div><dt>Risk</dt><dd>{pillsOf('risk', evidence.risk)}</dd></div>
          <div><dt>Activities</dt><dd>{pillsOf('activity', evidence.activities)}</dd></div>
          <div><dt>Roles</dt><dd>{evidence.roles.length}</dd></div>
        </dl>
        <p className="ui-description">Roles whose mapped transactions supply the activities of this risk. This is potential, transaction-derived evidence, not effective SAP authorization.</p>
        <div className="evidence-scroll" tabIndex={0} role="region" aria-label="Roles supplying this evidence">
          <DataTable caption="Roles supplying this evidence" density="compact"><thead><tr><th>Role</th></tr></thead><tbody>{evidence.roles.map((role) => <tr key={role}><td className="col-role"><RoleIdentifier value={role} label="assigned role" /></td></tr>)}</tbody></DataTable>
        </div>
      </>}
      {evidence.kind === 'transactions' && <>
        <dl className="evidence-summary">
          <div><dt>SAP user</dt><dd><RoleIdentifier value={evidence.user} label="SAP username" /></dd></div>
          <div><dt>Activity</dt><dd>{pillsOf('activity', evidence.activity)}</dd></div>
          <div><dt>Risks</dt><dd>{pillsOf('risk', evidence.risks)}</dd></div>
          <div><dt>Role assignments</dt><dd>{evidence.roles}</dd></div>
        </dl>
        <div className="evidence-scroll" tabIndex={0} role="region" aria-label="Transactions supplying this activity">
          <DataTable caption="Transactions supplying this activity" density="compact"><thead><tr><th>Transaction</th></tr></thead><tbody>{evidence.tcodes.map((code) => <tr key={code}><td><RoleIdentifier value={code} label="transaction" /></td></tr>)}</tbody></DataTable>
        </div>
      </>}
      {evidence.kind === 'users' && <AssignedUsers role={evidence.role} context={context} filters={filters} onInvestigate={(user) => onInvestigate(user)} onUser={onUser} />}
    </Dialog>
  )
}

/** Users behind one assigned role: a compact summary and a scrollable table with one row per distinct username and its assignment intervals. */
function AssignedUsers({ role, context, filters, onInvestigate, onUser }: { role: string; context: string; filters: Filters; onInvestigate: (user: string) => void; onUser: (user: string) => void }) {
  const params = scopeParams(context, { ...filters, role, roles: [] }, { limit: 200 }),
    result = useQuery({ queryKey: ['sod-explorer', 'access_list', 'assigned', params.toString()], queryFn: () => sod<Result>('/api/sod/explorer/access_list', params), placeholderData: keepWithinContext(['sod-explorer', 'access_list', 'assigned', params.toString()], params) as never })
  if (result.isError) return <p role="alert">Assigned users could not be loaded.</p>
  if (!result.data) return <p role="status">Loading assigned users…</p>
  const users = new Map<string, Row[]>()
  for (const row of result.data.items) users.set(row.user!, [...(users.get(row.user!) ?? []), row])
  const groups = new Set(result.data.items.map((row) => row.user_group || 'No user group'))
  return (
    <>
      <dl className="evidence-summary">
        <div><dt>Assigned role</dt><dd><RoleIdentifier value={role} label="assigned role" /></dd></div>
        <div><dt>Distinct users</dt><dd role="status">{users.size}</dd></div>
        <div><dt>SAP User Groups</dt><dd>{groups.size}</dd></div>
      </dl>
      <div className="evidence-scroll" tabIndex={0} role="region" aria-label={`Users with ${role}`}>
        <DataTable caption={`Users with ${role}`} density="compact">
          <thead><tr><th>SAP user</th><th>SAP User Group</th><th>Assignment</th><th className="col-actions"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{[...users].sort(([a], [b]) => a.localeCompare(b)).map(([user, rows]) => (
            <tr key={user}>
              <td><RoleIdentifier value={user} label="SAP username" onOpen={() => onUser(user)} openLabel={`Open SAP user ${user}`} /></td>
              <td className="whitespace-nowrap">{[...new Set(rows.map((row) => row.user_group || 'No user group'))].join(', ')}</td>
              <td>{rows.length === 1
                ? <span>{formatDate(rows[0].valid_from)} → {formatDate(rows[0].valid_to)}{rows[0].interval_status && rows[0].interval_status !== 'active' ? ` · ${rows[0].interval_status}` : ''}</span>
                : <details><summary>{rows.length} assignment intervals</summary><ul>{rows.map((row) => <li key={row.id}>{formatDate(row.valid_from)} → {formatDate(row.valid_to)}{row.interval_status ? ` · ${row.interval_status}` : ''}</li>)}</ul></details>}</td>
              <td className="col-actions"><Button size="compact" onClick={() => onInvestigate(user)} aria-label={`Investigate ${user}`}><ScanSearch size={14} aria-hidden="true" />Investigate</Button></td>
            </tr>
          ))}</tbody>
        </DataTable>
      </div>
      {result.data.total > result.data.items.length && <p className="ui-description">Showing the first {result.data.items.length} of {result.data.total} assignment records.</p>}
    </>
  )
}
const pillsOf = (kind: 'risk' | 'activity', value?: string[] | string) => <span className="inline-flex flex-wrap gap-1">{[value ?? []].flat().map((item) => <SodPill key={item} kind={kind} value={item} />)}</span>

const pickKey = (pick: AssignmentPick) => pick.key

function ExplorerTable({ table, onTable }: { table: TableName; onTable: (value: SodExplorerTable) => void }) {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('explorer'),
    [offset, setOffset] = useState(0),
    [, setSelected] = useSodSubject(),
    [busy, setBusy] = useState(false),
    [evidence, setEvidence] = useState<Evidence | null>(null),
    { change } = useViewHistory(),
    [pageSize, setPageSizeState] = useState(50),
    [dialog, setDialog] = useState<BulkAction | null>(null),
    [gathering, setGathering] = useState(false),
    [gatherNote, setGatherNote] = useState('')
  const selection = useBulkSelection<AssignmentPick>(pickKey)
  const setPageSize = (value: number) => { setPageSizeState(value); setOffset(0) }
  useFilterChangeReset(filters, () => setOffset(0))
  const openUser = (user: string) => { setEvidence(null); change({ page: 'users', accessMode: 'directory', user, userContext: {}, detailRole: null, settings: false }) }
  const investigate = (user: string, risk?: string, activity?: string) => { setEvidence(null); setSelected({ user, ...(risk ? { risk } : {}), ...(activity ? { activity } : {}) }) }
  const queue: Record<string, string> = table === 'access_list' ? { review_status: reviewStatusParam(filters) } : {}
  const params = scopeParams(context, filters, { offset, limit: pageSize, ...queue })
  const result = useQuery({ queryKey: ['sod-explorer', table, params.toString()], queryFn: () => sod<Result>(`/api/sod/explorer/${table}`, params), placeholderData: keepWithinContext(['sod-explorer', table, params.toString()], params) as never })
  const data = result.data
  const download = async (path: string, namePattern: RegExp, extra: Record<string, string> = {}) => {
    setBusy(true)
    try {
      const name = await downloadFile(path, { params: scopeParams(context, filters, { ...queue, ...extra }), namePattern, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (cause) {
      announceExport({ kind: 'error', message: cause instanceof Error ? cause.message : 'Export failed.' })
    } finally {
      setBusy(false)
    }
  }
  const rowPick = (row: Row): AssignmentPick => ({ key: row.id!, user: row.user!, ref: row.role!, suffix: row.suffix || '', evidence_version: row.evidence_version!, decision: row.decision || 'Pending', user_group: row.user_group || '' })
  const pageRows = table === 'access_list' && data ? data.items : []
  const pageSelected = pageRows.filter((row) => selection.has(row.id!)).length
  const selectAllMatching = async () => {
    setGathering(true); setGatherNote('')
    try {
      const all = await sod<AssignmentSelection>('/api/sod/explorer/access_list/selection', scopeParams(context, filters, queue))
      selection.add(all.items)
      setGatherNote(all.truncated ? `Only the first ${all.limit.toLocaleString()} of ${all.total.toLocaleString()} matching assignments were selected. Narrow the filters to cover the rest.` : `Selected all ${all.total.toLocaleString()} matching assignments.`)
    } catch (cause) {
      setGatherNote(cause instanceof Error ? cause.message : 'The matching assignments could not be loaded. The selection is unchanged.')
    } finally { setGathering(false) }
  }
  const picks = [...selection.items.values()]
  const showUsers = (role: string) => {
    setFiltersState({ ...filters, role: '', roles: [role] })
    onTable('access_list')
  }
  return (
    <section className="grid min-w-0 gap-4" aria-label={LABELS[table]}>
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
        {table === 'access_list' && data.progress && <section className="sod-tiles review-progress" aria-label="Role assignment review progress">
          {([['In scope', data.progress.total, 'all', ''], ['Completed (Keep or Remove)', data.progress.completed, 'reviewed', ''], ['Pending', data.progress.pending, 'pending', ''],
            ['Under investigation', data.progress.investigating, 'investigating', ''], ['Needs review', data.progress.attention, '', ''], ['Removal recommended', data.progress.removal, 'all', 'Removal required']] as const).map(([label, count, status, decision]) => {
            const active = (filters.review_status || '') === status && (typeof filters.assignment_decision === 'string' ? filters.assignment_decision : '') === decision
            return <Kpi key={label} label={label} value={count.toLocaleString()} active={active} tone={label === 'Needs review' && count ? 'warning' : 'neutral'}
              onClick={() => { setOffset(0); setFiltersState({ ...filters, review_status: active ? '' : status, assignment_decision: active ? '' : decision }) }} />
          })}
          <Kpi label="Outdated, re-review" value={data.progress.outdated.toLocaleString()} tone={data.progress.outdated ? 'warning' : 'neutral'} />
          {((filters.review_status || '') !== '' || filters.assignment_decision) && <Button size="compact" variant="ghost" onClick={() => { setOffset(0); setFiltersState({ ...filters, review_status: '', assignment_decision: '' }) }}>Reset tile filters</Button>}
        </section>}
        {table === 'access_list' && data.reviewable && <>
          {picks.length > 0
            ? <BulkToolbar label="Bulk assignment review" summary={`${picks.length.toLocaleString()} ${picks.length === 1 ? 'assignment' : 'assignments'} selected`}
              scope={`${pageSelected} on this page · ${picks.length - pageSelected} on other pages or outside the current filters · ${data.total.toLocaleString()} match the current filters`}>
              <Button size="compact" disabled={gathering || !data.total} onClick={() => void selectAllMatching()}>Select all {data.total.toLocaleString()} matching</Button>
              <Button size="compact" onClick={() => { selection.clear(); setGatherNote('') }}>Clear selection</Button>
              <Button size="compact" disabled={!picks.length} onClick={() => setDialog('Keep')}>Keep</Button>
              <Button size="compact" disabled={!picks.length} onClick={() => setDialog('Investigate')}>Investigate</Button>
              <Button size="compact" variant="destructive" disabled={!picks.length} onClick={() => setDialog('Remove')}>Recommend removal</Button>
            </BulkToolbar>
            : <p className="ui-description">Select assignments with the checkboxes, or <Button size="compact" variant="ghost" disabled={gathering || !data.total} onClick={() => void selectAllMatching()}>select all {data.total.toLocaleString()} matching</Button> to review them together. Reviews record decisions only; nothing changes in SAP.</p>}
          {gatherNote && <p role="status" className="ui-description">{gatherNote}</p>}
        </>}
        <p className="ui-description">Trace User → Risk → Activity → Transaction → Role → Assignment. Select a row to investigate; from the lookup, show the users behind a role.</p>
        {data.items.length ? <DataTable caption={LABELS[table]}>
          {table === 'user_risk' && <><thead><tr><th>SAP user</th><th>Risk</th><th>Activities</th><th>Evidence</th><th>Risk acceptance</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => { const id = `${row.user}:${row.risk_id}`; return <tr key={id}><td><RoleIdentifier value={row.user!} label="SAP username" /><p className="text-xs text-muted">{list(row.groups)}</p></td><td>{pills('risk', row.risk_id)}{row.category && <p><SodArea value={row.category} /></p>}</td><td>{pills('activity', row.activities)}</td>
              <td>{Array.isArray(row.roles) ? <EvidenceButton label={`${row.user} ${row.risk_id}`} summary={`${row.roles.length} ${row.roles.length === 1 ? 'role' : 'roles'}`} onOpen={() => setEvidence({ kind: 'roles', user: row.user!, risk: row.risk_id!, activities: [row.activities ?? []].flat(), roles: row.roles as string[], category: row.category })} /> : <RoleCodeList roles={row.roles} />}</td>
              <td><LifecycleBadge value={row.acceptance || 'Pending'} /></td>
              <td><Button size="compact" onClick={() => setSelected({ user: row.user!, risk: row.risk_id })} aria-label={`Investigate ${row.user} ${row.risk_id}`}><ScanSearch size={14} aria-hidden="true" />Investigate</Button></td></tr> })}</tbody></>}
          {table === 'user_activity' && <><thead><tr><th>SAP user</th><th>Activity</th><th>Risks</th><th>Evidence</th><th>Review</th><th>Open</th></tr></thead>
            <tbody>{data.items.map((row) => { const id = `${row.user}:${row.activity}`; return <tr key={id}><td><RoleIdentifier value={row.user!} label="SAP username" /></td><td>{pills('activity', row.activity)}</td><td>{pills('risk', row.risks)}</td>
              <td><EvidenceButton label={`${row.user} ${row.activity}`} summary={`${String(row.roles)} role assignment${row.roles === 1 ? '' : 's'}`} onOpen={() => setEvidence({ kind: 'transactions', user: row.user!, activity: row.activity!, risks: row.risks ?? [], tcodes: row.tcodes ?? [], roles: Number(row.roles) || 0 })} />{row.duplicate && <StatusBadge tone="info">Overlap</StatusBadge>}</td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td><Button size="compact" onClick={() => setSelected({ user: row.user!, activity: row.activity })} aria-label={`Investigate ${row.user} ${row.activity}`}><ScanSearch size={14} aria-hidden="true" />Investigate</Button></td></tr> })}</tbody></>}
          {table === 'access_list' && <><thead><tr><th className="col-select"><PageCheckbox label="Select all assignments on this page" selected={pageSelected} total={pageRows.length} onChange={(select) => select ? selection.add(pageRows.map(rowPick)) : selection.remove(pageRows.map((row) => row.id!))} /></th><th>SAP user</th><th>Role assignment</th><th>Risks</th><th>Activities</th><th>Review</th><th className="col-actions">Open</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={`${row.user}:${row.id}`} data-selected={selection.has(row.id!) || undefined}>
              <td className="col-select"><RowCheckbox label={`Select assignment ${row.role} for ${row.user}`} checked={selection.has(row.id!)} onChange={() => selection.toggle(rowPick(row))} /></td>
              <td><RoleIdentifier value={row.user!} label="SAP username" /></td>
              <td className="col-role"><RoleIdentifier value={row.role!} label="assigned role" />{row.interval_status && row.interval_status !== 'active' && <p><AssignmentStatus value={row.interval_status} /></p>}</td>
              <td>{pills('risk', row.risks)}</td><td>{pills('activity', row.activities)}</td><td><LifecycleBadge value={row.decision || 'Pending'} /></td>
              <td className="col-actions"><Button size="compact" onClick={() => setSelected({ user: row.user!, activity: Array.isArray(row.activities) ? row.activities[0] : undefined })} aria-label={`Investigate ${row.user} ${row.role}`}><ScanSearch size={14} aria-hidden="true" />Investigate</Button></td></tr>)}</tbody></>}
          {table === 'lookup' && <><thead><tr><th>Assigned role</th><th>Users</th><th>Risks</th><th>Activities</th><th className="col-actions">Trace</th></tr></thead>
            <tbody>{data.items.map((row) => <tr key={row.role}><td className="col-role"><RoleIdentifier value={row.role!} label="assigned role" /></td>
              <td><EvidenceButton label={row.role!} summary={`${row.users} user${row.users === 1 ? '' : 's'}`} onOpen={() => setEvidence({ kind: 'users', role: row.role! })} /></td>
              <td>{pills('risk', row.risks)}</td><td>{pills('activity', row.activities)}</td>
              <td className="col-actions"><Button size="compact" onClick={() => showUsers(row.role!)} aria-label={`Show users with ${row.role}`}><UsersRound size={14} aria-hidden="true" />Show users</Button></td></tr>)}</tbody></>}
        </DataTable> : <EmptyState>No rows match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}
        <Pagination label="Explorer pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} pageSizes={PAGE_SIZES} onPageSize={setPageSize} />
        {evidence && <ExplorerEvidence evidence={evidence} context={context} filters={filters} onClose={() => setEvidence(null)} onInvestigate={investigate} onUser={openUser} />}
        {dialog && <BulkReviewDialog action={dialog} picks={picks} info={data} onClose={() => setDialog(null)} onApplied={(recorded) => { selection.remove(recorded); setGatherNote('') }} />}
      </>}
      </SodFilters>
    </section>
  )
}
