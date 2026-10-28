import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { downloadFile, scopeParams, sod, EXPORT_NAME, type ActivityCell, type ActivityColumn, type Filters, type GroupCell, type MatrixResult, type RiskCell, type RiskColumn } from '@/api/sod'
import { MatrixGrid, type MatrixCellView } from '@/components/Shared/MatrixGrid'
import { ErrorState, EmptyState, LoadingState } from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
import { Button } from '@/components/Shared/Button'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { Pagination } from '@/components/Access/Shared'
import { announceExport } from '@/lib/exportNotice'
import { SodPill } from '@/lib/sodAppearance'
import { ContextBar, CoverageNotice, SodFilters, lifecycleView, useSodContext, useSodFilters, useSodSubject } from './SodShared'

type Risk = MatrixResult<RiskColumn, RiskCell>
type Activity = MatrixResult<ActivityColumn, ActivityCell>
const PAGE = 50
/** Page and row grouping survive leaving the matrix (a role page, Back) within the session. */
const memory: Record<string, { offset: number; groupBy: 'user' | 'group' }> = {}

export const RiskMatrix = () => <MatrixPage kind="risk" />
export const ActivityMatrix = () => <MatrixPage kind="activity" />

function MatrixPage({ kind }: { kind: 'risk' | 'activity' }) {
  const [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters(kind === 'risk' ? 'riskMatrix' : 'activityMatrix'),
    [groupBy, setGroupByState] = useState<'user' | 'group'>(memory[kind]?.groupBy || 'user'),
    [offset, setOffsetState] = useState(memory[kind]?.offset || 0),
    [selected, setSelected] = useSodSubject(),
    [busy, setBusy] = useState(false)
  const setOffset = (value: number) => { memory[kind] = { offset: value, groupBy }; setOffsetState(value) }
  const setGroupBy = (value: 'user' | 'group') => { memory[kind] = { offset: 0, groupBy: value }; setGroupByState(value) }
  const setFilters = (value: Filters) => {
    setOffset(0)
    setFiltersState(value)
  }
  const params = scopeParams(context, filters, { group_by: groupBy, offset, limit: PAGE })
  const result = useQuery({ queryKey: ['sod-matrix', kind, params.toString()], queryFn: () => sod<Risk | Activity>(`/api/sod/matrix/${kind}`, params) })
  const data = result.data
  const byUser = new Map((data?.rows || []).map((row) => [row.user, row]))
  const risk = kind === 'risk'
  const columns = (data?.columns || []).map((column) => {
    const id = risk ? (column as RiskColumn).risk_id : (column as ActivityColumn).activity
    return risk
      ? { id, label: id, node: <SodPill kind="risk" value={id} />, sub: `${column.users} users`, title: `${(column as RiskColumn).display_name || (column as RiskColumn).source_text || id} · criticality ${(column as RiskColumn).criticality}`, onFilter: () => setFilters({ ...filters, risk: id }) }
      : { id, label: id, node: <SodPill kind="activity" value={id} />, sub: `${column.users} users`, title: `Activity ${id} · ${(column as ActivityColumn).risks.length} risks`, onFilter: () => setFilters({ ...filters, activity: id }) }
  })
  const cell = (row: string, column: string): MatrixCellView | null => {
    const entry = byUser.get(row)?.cells[column]
    if (!entry) return null
    if (groupBy === 'group') {
      const count = (entry as GroupCell).users
      return { icon: <Users size={14} />, text: String(count), sub: count === 1 ? 'user' : 'users', label: `${count} users in group ${row} with ${column}. Show these users.` }
    }
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
    if (groupBy === 'group') {
      setGroupBy('user')
      setFilters({ ...filters, group: row, ...(risk ? { risk: column } : { activity: column }) })
      return
    }
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
  const legend = risk ? ['Pending', 'Accepted', 'Rejected', 'Outdated'] : ['Pending', 'Approved', 'Conditional', 'Removal required', 'Outdated']
  return (
    <section className="grid min-w-0 gap-4" aria-label={risk ? 'SoD risk matrix' : 'SoD activity matrix'}>
      <ContextBar info={data} />
      <SodFilters view={risk ? 'sod_risk_matrix' : 'sod_activity_matrix'} filters={filters} setFilters={setFilters}
        fields={['group', 'risk', 'activity', 'username', 'role', 'role_suffix', 'tcode', 'category', 'criticality', 'validity', 'activity_decision', 'assignment_decision', 'acceptance']}
        sorts={[{ value: 'subject', label: 'Name' }, { value: 'findings', label: risk ? 'Most risks' : 'Most activities' }]}
        actions={<>
          <Select aria-label="Rows" value={groupBy} onChange={(event) => { setOffset(0); setGroupBy(event.target.value as 'user' | 'group') }}>
            <option value="user">SAP users</option>
            <option value="group">SAP user groups</option>
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
            ).map(([label, value]) => <div className="sod-tile" key={label}><span>{label}</span><strong>{Number(value).toLocaleString()}</strong></div>)}
            {legend.map((value) => {
              const filterName = risk ? 'acceptance' : 'activity_decision',
                active = filters[filterName] === value,
                view = lifecycleView(value)
              return (
                <div className="sod-tile" key={value} data-active={active || undefined} data-tone={value === 'Pending' || value === 'Outdated' ? 'warning' : value === 'Rejected' || value === 'Removal required' ? 'error' : undefined}>
                  <button type="button" aria-pressed={active} onClick={() => setFilters({ ...filters, [filterName]: active ? '' : value })}>{view.text}{risk ? ' risks' : ' activities'}</button>
                  <strong>{(data.status_counts?.[value] || 0).toLocaleString()}</strong>
                </div>
              )
            })}
            {Object.entries((data as Risk).criticality || {}).map(([key, value]) => <div className="sod-tile" key={key}><span>Criticality {key}</span><strong>{value.user_risk.toLocaleString()}</strong><small>{value.users} users</small></div>)}
          </section>
          <p className="ui-description">{risk ? 'Cells show the risk acceptance status and how many of the risk activities are reviewed (reviewed/total). Criticality and type are in the column tooltip and the investigation.' : 'Scope: activities that contribute to at least one potential conflict (both sides of an enabled, supported risk). Activities a role supplies beyond those are considered in Role Assignment Review. Cells show the activity review status and ×roles supplying it; ⧉ marks overlapping coverage.'}</p>
          <p className="ui-description">Totals count distinct users and distinct {risk ? 'user-risk' : 'user-activity'} pairs. {data.columns_truncated ? 'Showing the first 500 columns; narrow the filters. ' : ''}{groupBy === 'group' ? 'Cells show distinct users per group; select one to list them. ' : 'Select a cell to investigate and review. '}Detected conflicts are potential and derived from imported evidence.</p>
          {data.rows.length
            ? <MatrixGrid scrollKey={`sod-${kind}-${groupBy}`} caption={risk ? 'User by risk matrix' : 'User by activity matrix'} rowLabel={groupBy === 'group' ? 'User group' : 'SAP user'} columns={columns}
                rows={data.rows.map((row) => ({ id: row.user, label: row.user, sub: groupBy === 'group' ? `${row.users} users` : row.groups.join(', ') }))}
                cell={cell} onSelect={open} onRow={groupBy === 'user' ? (row) => setSelected({ user: row }) : undefined}
                selected={selected ? { row: selected.user, col: selected.risk || selected.activity || '' } : null} />
            : <EmptyState>No users match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}
          <Pagination label="Matrix pages" offset={data.offset} total={data.total_rows} limit={data.limit} onChange={setOffset} />
          {filters.risk || filters.activity || filters.group ? <Button variant="ghost" onClick={() => setFilters({ ...filters, risk: '', activity: '', group: '' })}>Show all risks, activities and groups</Button> : null}
        </>}
      </SodFilters>
    </section>
  )
}
