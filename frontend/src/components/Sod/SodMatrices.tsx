import { Kpi } from '@/components/Shared/Kpi'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ActivityCell, type ActivityColumn, type Filters, type MatrixResult, type RiskCell, type RiskColumn } from '@/api/sod'
import { MatrixGrid, type MatrixCellView } from '@/components/Shared/MatrixGrid'
import { ErrorState, EmptyState, LoadingState, Toolbar } from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
import { Button } from '@/components/Shared/Button'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { Pagination } from '@/components/Access/Shared'
import { announceExport } from '@/lib/exportNotice'
import { SodPill } from '@/lib/sodAppearance'
import { stateTone } from '@/lib/kpiTone'
import { CoverageNotice, SodFilters, keepWithinContext, lifecycleView, useFilterChangeReset, useSodContext, useSodFilters, useSodSubject } from './SodShared'

type Risk = MatrixResult<RiskColumn, RiskCell>
type Activity = MatrixResult<ActivityColumn, ActivityCell>
const PAGE = 50
/** Users per page is one setting for both matrices and survives switching between them within the session. */
const MATRIX_SIZES = [10, 25, 50, 100, 'all'] as const
type MatrixSize = (typeof MATRIX_SIZES)[number]
const everyUser = 5000 // "All" asks for one page of up to this many users (the server's matrix page maximum)
const shared: { size: MatrixSize } = { size: PAGE }
/** Page and row grouping survive leaving the matrix (a role page, Back) within the session. */
const memory: Record<string, { offset: number; groupBy: 'none' | 'group' }> = {}
/** Collapsed SAP User Groups survive paging and leaving the matrix within the session. */
const collapsedMemory: Record<string, Set<string>> = {}

export const RiskMatrix = () => <MatrixPage kind="risk" />
export const ActivityMatrix = () => <MatrixPage kind="activity" />

function MatrixPage({ kind }: { kind: 'risk' | 'activity' }) {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters(kind === 'risk' ? 'riskMatrix' : 'activityMatrix'),
    [groupBy, setGroupByState] = useState<'none' | 'group'>(memory[kind]?.groupBy || 'none'),
    [collapsed, setCollapsedState] = useState<Set<string>>(collapsedMemory[kind] || new Set()),
    [offset, setOffsetState] = useState(memory[kind]?.offset || 0),
    [selected, setSelected] = useSodSubject(),
    [busy, setBusy] = useState(false),
    [pageSize, setPageSizeState] = useState<MatrixSize>(shared.size)
  const setPageSize = (value: MatrixSize) => { shared.size = value; setPageSizeState(value); setOffset(0) }
  const setOffset = (value: number) => { memory[kind] = { offset: value, groupBy }; setOffsetState(value) }
  const setCollapsed = (value: Set<string>) => { collapsedMemory[kind] = value; setCollapsedState(value) }
  const setGroupBy = (value: 'none' | 'group') => { memory[kind] = { offset: 0, groupBy: value }; setGroupByState(value) }
  const setFilters = (value: Filters) => {
    setOffset(0)
    setFiltersState(value)
  }
  useFilterChangeReset(filters, () => setOffset(0))
  const params = scopeParams(context, filters, { group_by: groupBy === 'group' ? 'user_group' : 'user', offset, limit: pageSize === 'all' ? everyUser : pageSize })
  const matrixKey = ['sod-matrix', kind, params.toString()],
    result = useQuery({ queryKey: matrixKey, queryFn: () => sod<Risk | Activity>(`/api/sod/matrix/${kind}`, params), placeholderData: keepWithinContext(matrixKey, params, ['group_by']) as never })
  const data = result.data
  // A page that no longer exists (filters changed on another page, a smaller result) returns to the first one.
  useEffect(() => { if (data && data.total_rows > 0 && offset >= data.total_rows) setOffset(0) }, [data?.total_rows, offset]) // eslint-disable-line react-hooks/exhaustive-deps
  const byUser = new Map((data?.rows || []).map((row) => [row.user, row]))
  const risk = kind === 'risk'
  const columns = (data?.columns || []).map((column) => {
    const id = risk ? (column as RiskColumn).risk_id : (column as ActivityColumn).activity
    return risk
      ? { id, label: id, node: <SodPill kind="risk" value={id} />, sub: `${column.users} users`, title: `${(column as RiskColumn).display_name || (column as RiskColumn).source_text || id} · criticality ${(column as RiskColumn).criticality}`, onFilter: () => setFilters({ ...filters, risk: '', risks: [id] }) }
      : { id, label: id, node: <SodPill kind="activity" value={id} />, sub: `${column.users} users`, title: `Activity ${id} · ${(column as ActivityColumn).risks.length} risks`, onFilter: () => setFilters({ ...filters, activity: '', activities: [id] }) }
  })
  const cell = (row: string, column: string): MatrixCellView | null => {
    const entry = byUser.get(row)?.cells[column]
    if (!entry) return null
    if (risk) {
      const value = entry as RiskCell,
        view = lifecycleView(value.acceptance),
        sides = Object.values(value.activities).reduce((sum, count) => sum + count, 0),
        undecided = (value.activities.Pending || 0) + (value.activities.Outdated || 0)
      return { icon: view.icon, tone: view.tone, text: view.text, sub: `${sides - undecided}/${sides}`,
        label: `${row}, risk ${column}: potential conflict detected, risk acceptance ${view.text}, ${sides - undecided} of ${sides} activities reviewed. Open investigation.` }
    }
    const value = entry as ActivityCell,
      view = lifecycleView(value.decision)
    return { icon: view.icon, tone: view.tone, text: view.text, sub: `×${value.roles}${value.duplicate ? ' ⧉' : ''}`,
      label: `${row}, activity ${column}: review ${view.text}, supplied by ${value.roles} role assignments${value.duplicate ? ', duplicate coverage' : ''}. Open investigation.` }
  }
  const open = (row: string, column: string) => {
    setSelected(risk ? { user: row, risk: column } : { user: row, activity: column })
  }
  const exportCsv = async () => {
    setBusy(true)
    try {
      const table = risk ? 'user_risk' : 'user_activity'
      const name = await downloadFile(`/api/sod/explorer/${table}/export`, { params: scopeParams(context, filters), namePattern: EXPORT_NAME, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (error) {
      announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' })
    } finally {
      setBusy(false)
    }
  }
  const grouped = groupBy === 'group',
    onPage = new Set((data?.rows || []).map((row) => row.group)),
    summaries = (data?.group_summaries || []).filter((item) => onPage.has(item.name)).map((item, index) => ({ ...item, continued: index === 0 && item.start < (data?.offset || 0) })),
    toggle = (name: string) => { const next = new Set(collapsed); if (next.has(name)) next.delete(name); else next.add(name); setCollapsed(next) }
  const legend = risk ? ['Pending', 'Accepted', 'Rejected', 'Outdated'] : ['Pending', 'Approved', 'Conditional', 'Removal required', 'Outdated']
  return (
    <section className="grid min-w-0 gap-4" aria-label={risk ? 'SoD risk matrix' : 'SoD activity matrix'}>
      <SodFilters view={risk ? 'sod_risk_matrix' : 'sod_activity_matrix'} filters={filters} setFilters={setFilters}
        fields={['group', 'risk', 'activity', 'username', 'role', 'role_suffix', 'tcode', 'category', 'validity', 'activity_decision', 'assignment_decision', 'acceptance']}
        sorts={[{ value: 'subject', label: 'Name' }, { value: 'group', label: 'SAP User Group' }, { value: 'findings', label: risk ? 'Most risks' : 'Most activities' }]}
        actions={<>
          <Select aria-label="Users per page" value={String(pageSize)} onChange={(event) => setPageSize(event.target.value === 'all' ? 'all' : (Number(event.target.value) as MatrixSize))} title="How many users the matrix lists per page">
            {MATRIX_SIZES.map((size) => <option key={size} value={size}>{size === 'all' ? 'All users' : `${size} users per page`}</option>)}
          </Select>
          <Select aria-label="Group by" value={groupBy} onChange={(event) => { setOffset(0); setGroupBy(event.target.value as 'none' | 'group') }}>
            <option value="none">No grouping</option>
            <option value="group">SAP User Group</option>
          </Select>
          <ExportCSVButton loading={busy} disabled={!data?.total_rows} onClick={() => void exportCsv()} title={`Exports the filtered ${risk ? 'user-risk' : 'user-activity'} table.`} />
        </>}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} />
        : !data ? <LoadingState />
        : <>
          <CoverageNotice info={data} />
          <section className="sod-tiles" aria-label={risk ? 'Risk matrix figures' : 'Activity matrix figures'}>
            {(risk
              ? [['Users with conflicts', data.totals.users], ['Distinct user-risk findings', data.totals.user_risk ?? 0], ['Risks shown', data.totals.risks ?? 0]]
              : [['Users with activity evidence', data.totals.users], ['User-activity pairs', data.totals.user_activity ?? 0], ['Activities shown', data.totals.activities ?? 0]]
            ).map(([label, value]) => <Kpi key={label} label={String(label)} value={Number(value).toLocaleString()} />)}
            {legend.map((value) => {
              const filterName = risk ? 'acceptance' : 'activity_decision',
                active = filters[filterName] === value,
                view = lifecycleView(value),
                count = data.status_counts?.[value] || 0
              return (
                <Kpi key={value} label={`${view.text}${risk ? ' risks' : ' activities'}`} value={count.toLocaleString()} active={active}
                  tone={stateTone(value, count)}
                  onClick={() => setFilters({ ...filters, [filterName]: active ? '' : value })} />
              )
            })}
            {filters[risk ? 'acceptance' : 'activity_decision'] && <Button size="compact" variant="ghost" onClick={() => setFilters({ ...filters, [risk ? 'acceptance' : 'activity_decision']: '' })}>Reset tile filters</Button>}
          </section>
          <Toolbar aria-label="Matrix range">
            <Pagination label="Matrix range" offset={data.offset} total={data.total_rows} limit={Math.min(data.limit, Math.max(data.total_rows, 1))} onChange={setOffset} unit="users" alwaysShow />
            {pageSize === 'all' && data.total_rows > everyUser && <span className="ui-description" role="status">The first {everyUser.toLocaleString()} users are listed; narrow the filters to see the others. Exports always include every filtered user.</span>}
          </Toolbar>
          <p className="ui-description">{risk ? 'Cells show the risk acceptance status and how many of the risk activities are reviewed (reviewed/total). Criticality and type are in the column tooltip and the investigation.' : 'Scope: activities that contribute to at least one potential conflict (both sides of an enabled, supported risk). Activities a role supplies beyond those are considered in Role Assignment Review. Cells show the activity review status and ×roles supplying it; ⧉ marks overlapping coverage.'}</p>
          <p className="ui-description">Totals count distinct users and distinct {risk ? 'user-risk' : 'user-activity'} pairs. {data.columns_truncated ? 'Showing the first 500 columns; narrow the filters. ' : ''}Select a cell to investigate and review. {groupBy === 'group' ? 'Users are listed once under their SAP User Group (the first selected group, else their first); grouping changes presentation only. ' : ''}Detected conflicts are potential and derived from imported evidence.</p>
          {data.rows.length
            ? <>
              {grouped && <Toolbar aria-label="Group controls">
                <span className="ui-description" role="status">{summaries.length} {summaries.length === 1 ? 'group' : 'groups'} on this page</span>
                <Button size="compact" onClick={() => setCollapsed(new Set())}>Expand all</Button>
                <Button size="compact" onClick={() => setCollapsed(new Set((data.group_summaries || []).map((item) => item.name)))}>Collapse all</Button>
              </Toolbar>}
              <MatrixGrid scrollKey={`sod-${kind}-${groupBy}`} caption={risk ? 'User by risk matrix' : 'User by activity matrix'} rowLabel="SAP user" codeRows columns={columns} groupColumn={!grouped}
                rows={data.rows.filter((row) => !grouped || !collapsed.has(row.group || '')).map((row) => ({ id: row.user, label: row.user, group: row.group, groups: row.groups,
                  sub: grouped && row.groups.length > 1 ? `Also in ${row.groups.filter((name) => name !== row.group).join(', ')}` : '' }))}
                groups={grouped ? summaries.map((item) => ({ id: item.name, label: item.name, collapsed: collapsed.has(item.name), onToggle: () => toggle(item.name),
                  summary: `${item.users.toLocaleString()} ${item.users === 1 ? 'user' : 'users'} · ${item.findings.toLocaleString()} ${risk ? 'risk' : 'activity'} ${item.findings === 1 ? 'finding' : 'findings'}${item.continued ? ' · continued' : ''}` })) : undefined}
                cell={cell} onSelect={open} onRow={(row) => setSelected({ user: row })}
                selected={selected ? { row: selected.user, col: selected.risk || selected.activity || '' } : null} />
            </>
            : <EmptyState>No users match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}
          <Pagination label="Matrix pages" offset={data.offset} total={data.total_rows} limit={data.limit} onChange={setOffset} unit="users" />
          {filters.risk || filters.activity || filters.group || ['risks', 'activities', 'groups'].some((name) => Array.isArray(filters[name]) && (filters[name] as string[]).length) ? <Button variant="ghost" onClick={() => setFilters({ ...filters, risk: '', activity: '', group: '', risks: [], activities: [], groups: [] })}>Show all risks, activities and groups</Button> : null}
        </>}
      </SodFilters>
    </section>
  )
}
