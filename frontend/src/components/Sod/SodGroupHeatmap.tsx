import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Grid3x3, X } from 'lucide-react'
import { downloadFile, emptyFilters, EXPORT_NAME, scopeParams, sod, type ActivityColumn, type Filters, type GroupCell, type MatrixResult, type RiskColumn } from '@/api/sod'
import { Button, ButtonGroup } from '@/components/Shared/Button'
import { DisclosureChevron } from '@/components/Shared/DisclosureChevron'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { SortControl } from '@/components/Shared/FilterLayout'
import { EmptyState, ErrorState, LoadingState } from '@/components/Shared/Presentation'
import { useViewHistory, type SodView } from '@/hooks/useViewHistory'
import { announceExport } from '@/lib/exportNotice'
import { useLocalPreference } from '@/lib/localPreference'
import { SodPill } from '@/lib/sodAppearance'
import { useSodContext } from './SodShared'

type Kind = 'risk' | 'activity'
type Heat = MatrixResult<RiskColumn | ActivityColumn, GroupCell>
const MAX_COLUMNS = 25
const SORTS = [{ value: 'name', label: 'SAP User Group' }, { value: 'users', label: 'Distinct users' }, { value: 'items', label: 'Most risks or activities' }]
export const HEATMAP_PREFERENCE = 'sap-lens-sod-heatmap'
/** Pages that apply a group and risk/activity filter themselves, and the saved-filter slot each one reads. */
const FILTERABLE: Partial<Record<SodView, string>> = { 'risk-matrix': 'riskMatrix', 'activity-matrix': 'activityMatrix', explorer: 'explorer', reviews: 'queue' }
const list = (filters: Filters, key: string) => (Array.isArray(filters[key]) ? (filters[key] as string[]) : [])

/**
 * Distinct users per SAP User Group and risk (or activity) for the active review context. One instance sits under the shared Review Context on every SoD page.
 * On pages that filter by group and risk or activity it reads and writes those same filters (other filters are kept, the filters are visible and removable);
 * on the others a selection opens the Risk or Activity Matrix with the filter applied.
 */
export function SodGroupHeatmap() {
  const [kind, setKind] = useState<Kind>('risk'), [sort, setSort] = useState('users'), [descending, setDescending] = useState(true), [busy, setBusy] = useState(false)
  const [preference, setPreference] = useLocalPreference(HEATMAP_PREFERENCE, 'open'), expanded = preference !== 'closed'
  const { view: history, change } = useViewHistory(), [context] = useSodContext(), panel = useId()
  const sodView: SodView = history.sodView || 'overview', slot = FILTERABLE[sodView], stored = history.sodFilters
  const current: Filters = slot ? { ...emptyFilters, ...stored?.[slot] } : emptyFilters
  const risk = kind === 'risk', itemKey = risk ? 'risks' : 'activities', singleKey = risk ? 'risk' : 'activity'
  const groups = [...list(current, 'groups'), ...(typeof current.group === 'string' && current.group ? [current.group] : [])]
  const items = [...list(current, itemKey), ...(typeof current[singleKey] === 'string' && current[singleKey] ? [current[singleKey] as string] : [])]
  const params = scopeParams(context, emptyFilters, { group_by: 'group', limit: 200 })
  const query = useQuery({ queryKey: ['sod-matrix', 'heatmap', kind, params.toString()], queryFn: () => sod<Heat>(`/api/sod/matrix/${kind}`, params), enabled: expanded })
  const data = query.data
  if (data && data.coverage.status !== 'available') return null // the page's own notice explains an unavailable analysis
  const idOf = (column: RiskColumn | ActivityColumn) => (risk ? (column as RiskColumn).risk_id : (column as ActivityColumn).activity)
  const columns = (data?.columns || []).slice().sort((a, b) => b.users - a.users || idOf(a).localeCompare(idOf(b))).slice(0, MAX_COLUMNS)
  const rows = (data?.rows || []).slice().sort((a, b) => {
    const order = sort === 'name' ? a.user.localeCompare(b.user) : sort === 'users' ? (a.users ?? 0) - (b.users ?? 0) : Object.keys(a.cells).length - Object.keys(b.cells).length
    return (descending ? -order : order) || a.user.localeCompare(b.user)
  })
  const max = Math.max(1, ...rows.flatMap((row) => Object.values(row.cells).map((cell) => (cell as GroupCell).users)))
  const heat = (users: number) => `color-mix(in srgb, var(--error) ${Math.round(8 + (users / max) * 27)}%, var(--surface))`
  /** Apply a group and item selection, keeping every other filter. Pages without these filters hand the selection to the matching matrix. */
  const apply = (nextGroups: string[], nextItems: string[]) => {
    const target = slot ?? (risk ? 'riskMatrix' : 'activityMatrix')
    const base: Filters = { ...emptyFilters, ...stored?.[target] }
    const next: Filters = { ...base, group: '', groups: nextGroups, [singleKey]: '', [itemKey]: nextItems }
    change({ sodFilters: { ...stored, [target]: next as never }, ...(slot ? {} : { sodView: risk ? 'risk-matrix' as const : 'activity-matrix' as const }) })
  }
  const toggle = (values: string[], value: string) => (values.includes(value) ? values.filter((item) => item !== value) : [...values, value])
  const exportCsv = async () => {
    setBusy(true)
    try {
      const name = await downloadFile(`/api/sod/matrix/${kind}/group-export`, { params: scopeParams(context, emptyFilters), namePattern: EXPORT_NAME, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (error) {
      announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' })
    } finally { setBusy(false) }
  }
  const active = groups.length > 0 || items.length > 0
  return (
    <section className="dashboard-section sod-heatmap-section min-w-0 rounded-card bg-surface p-4" aria-label="SAP User Group heatmap" data-expanded={expanded}>
      <div className="sod-heatmap-bar">
        <h2 className="sod-heatmap-title">
          <button type="button" className="sod-heatmap-toggle" aria-expanded={expanded} aria-controls={panel} onClick={() => setPreference(expanded ? 'closed' : 'open')}>
            <DisclosureChevron open={expanded} />
            <Grid3x3 size={18} aria-hidden="true" />Conflicts by SAP User Group
          </button>
        </h2>
        {expanded && (
          <div className="sod-heatmap-controls" role="toolbar" aria-label="Heatmap controls">
            <ButtonGroup label="Heatmap columns" value={kind} onChange={(value) => setKind(value as Kind)} options={[{ value: 'risk', label: 'Risks' }, { value: 'activity', label: 'Activities' }]} />
            <SortControl label="Sort groups" value={sort} options={SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
            <ExportCSVButton label="Export heatmap CSV" loading={busy} disabled={!data?.rows.length} onClick={() => void exportCsv()} title={`Exports distinct users per SAP User Group and ${risk ? 'risk' : 'activity'}.`} />
          </div>
        )}
      </div>
      {active && (
        <div className="active-filter-row sod-heatmap-filters" role="group" aria-label="Active heatmap filters">
          {groups.map((group) => <HeatChip key={`g-${group}`} label={`SAP User Group ${group}`} onRemove={() => apply(groups.filter((item) => item !== group), items)}>SAP User Group: {group}</HeatChip>)}
          {items.map((item) => <HeatChip key={`i-${item}`} label={`${risk ? 'Risk' : 'Activity'} ${item}`} onRemove={() => apply(groups, items.filter((value) => value !== item))}>{risk ? 'Risk' : 'Activity'}: {item}</HeatChip>)}
          <Button size="compact" variant="ghost" onClick={() => apply([], [])}>Clear heatmap filters</Button>
        </div>
      )}
      <div id={panel} hidden={!expanded}>
        {expanded && (query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Heatmap unavailable" />
          : !data ? <LoadingState />
          : !rows.length ? <EmptyState>No potential conflicts in the selected evidence. Results describe imported evidence only.</EmptyState>
          : <>
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="SAP User Group heatmap table">
              <table className="sod-heatmap">
                <caption className="sr-only">Distinct users per SAP User Group and {risk ? 'risk' : 'activity'}. A user in several groups counts in each group. Select a group, a {risk ? 'risk' : 'activity'} or a cell to filter.</caption>
                <thead><tr><th scope="col">SAP User Group</th><th scope="col">Users</th>{columns.map((column) => {
                  const id = idOf(column), selected = items.includes(id)
                  return <th scope="col" key={id} data-selected={selected || undefined}>
                    <button type="button" className="sod-heat-head" aria-pressed={selected} aria-label={`${id}: ${selected ? 'remove ' : 'filter to this '}${risk ? 'risk' : 'activity'}${selected ? ' filter' : ''}`} onClick={() => apply(groups, toggle(items, id))}><SodPill kind={kind} value={id} /></button>
                  </th>
                })}</tr></thead>
                <tbody>
                  {rows.map((row) => {
                    const rowSelected = groups.includes(row.user)
                    return (
                      <tr key={row.user} data-selected={rowSelected || undefined}>
                        <th scope="row"><button type="button" className="sod-heat-group" aria-pressed={rowSelected} title={row.user} aria-label={`${row.user}: ${rowSelected ? 'remove SAP User Group filter' : 'filter to this SAP User Group'}`} onClick={() => apply(toggle(groups, row.user), items)}>{row.user}</button></th>
                        <td>{(row.users ?? 0).toLocaleString()}</td>
                        {columns.map((column) => {
                          const id = idOf(column), cell = row.cells[id] as GroupCell | undefined, exact = rowSelected && items.includes(id)
                          return <td key={id}>{cell
                            ? <button type="button" className="sod-heat-cell" aria-pressed={exact} style={{ ['--heat' as string]: heat(cell.users) }} aria-label={`${cell.users} ${cell.users === 1 ? 'user' : 'users'} in group ${row.user} with ${id}. Show these users.`}
                                onClick={() => (exact && groups.length === 1 && items.length === 1 ? apply([], []) : apply([row.user], [id]))}>{cell.users}</button>
                            : <span className="sod-heat-empty" aria-label="No users">·</span>}</td>
                        })}
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot><tr><th scope="row">Distinct users</th><td>{data.totals.users.toLocaleString()}</td>{columns.map((column) => <td key={idOf(column)}>{column.users.toLocaleString()}</td>)}</tr></tfoot>
              </table>
            </div>
            <p className="ui-description">
              A user in several SAP User Groups counts in each group, so group counts can add up to more than the distinct total.
              {data.columns.length > MAX_COLUMNS ? ` Showing the ${MAX_COLUMNS} most affected of ${data.columns.length} ${risk ? 'risks' : 'activities'}.` : ''}
              {slot ? ' Selections filter this page.' : ` Selections open the ${risk ? 'Risk' : 'Activity'} Matrix with the filter applied.`}
            </p>
            {data.total_rows > rows.length && !slot && <Button variant="ghost" onClick={() => apply([], [])}>Open the full matrix</Button>}
          </>)}
      </div>
    </section>
  )
}

function HeatChip({ children, label, onRemove }: { children: React.ReactNode; label: string; onRemove: () => void }) {
  return <span className="transaction-chip">{children}<button type="button" aria-label={`Remove filter ${label}`} onClick={onRemove}><X size={13} aria-hidden="true" /></button></span>
}
