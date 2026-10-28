import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Grid3x3 } from 'lucide-react'
import { downloadFile, emptyFilters, EXPORT_NAME, scopeParams, sod, type ActivityColumn, type GroupCell, type MatrixResult, type RiskColumn } from '@/api/sod'
import { Button } from '@/components/Shared/Button'
import { ButtonGroup } from '@/components/Shared/Button'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { SortControl } from '@/components/Shared/FilterLayout'
import { EmptyState, ErrorState, LoadingState, SectionHeader } from '@/components/Shared/Presentation'
import { announceExport } from '@/lib/exportNotice'
import { SodPill } from '@/lib/sodAppearance'

type Kind = 'risk' | 'activity'
type Heat = MatrixResult<RiskColumn | ActivityColumn, GroupCell>
const MAX_COLUMNS = 25
const SORTS = [{ value: 'name', label: 'SAP user group' }, { value: 'users', label: 'Distinct users' }, { value: 'items', label: 'Most risks or activities' }]

/** Distinct users per SAP user group and risk (or activity) over current evidence; cells drill into the matrix for that group and item. */
export function SodGroupHeatmap({ onOpen }: { onOpen: (kind: Kind, patch: Record<string, string>) => void }) {
  const [kind, setKind] = useState<Kind>('risk'), [sort, setSort] = useState('users'), [descending, setDescending] = useState(true), [busy, setBusy] = useState(false)
  const params = scopeParams('current', emptyFilters, { group_by: 'group', limit: 200 })
  const query = useQuery({ queryKey: ['sod-matrix', 'heatmap', kind, params.toString()], queryFn: () => sod<Heat>(`/api/sod/matrix/${kind}`, params) })
  const risk = kind === 'risk', data = query.data
  const idOf = (column: RiskColumn | ActivityColumn) => (risk ? (column as RiskColumn).risk_id : (column as ActivityColumn).activity)
  const columns = (data?.columns || []).slice().sort((a, b) => b.users - a.users || idOf(a).localeCompare(idOf(b))).slice(0, MAX_COLUMNS)
  const rows = (data?.rows || []).slice().sort((a, b) => {
    const order = sort === 'name' ? a.user.localeCompare(b.user) : sort === 'users' ? (a.users ?? 0) - (b.users ?? 0) : Object.keys(a.cells).length - Object.keys(b.cells).length
    return (descending ? -order : order) || a.user.localeCompare(b.user)
  })
  const max = Math.max(1, ...rows.flatMap((row) => Object.values(row.cells).map((cell) => (cell as GroupCell).users)))
  const heat = (users: number) => `color-mix(in srgb, var(--error) ${Math.round(8 + (users / max) * 27)}%, var(--surface))`
  const exportCsv = async () => {
    setBusy(true)
    try {
      const name = await downloadFile(`/api/sod/matrix/${kind}/group-export`, { params: scopeParams('current', emptyFilters), namePattern: EXPORT_NAME, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (error) {
      announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' })
    } finally { setBusy(false) }
  }
  return (
    <section className="dashboard-section min-w-0 rounded-card bg-surface p-4" aria-label="SAP user group heatmap">
      <SectionHeader title="Conflicts by SAP user group" icon={<Grid3x3 size={18} aria-hidden="true" />} />
      <div className="page-toolbar-actions">
        <ButtonGroup label="Heatmap columns" value={kind} onChange={(value) => setKind(value as Kind)} options={[{ value: 'risk', label: 'Risks' }, { value: 'activity', label: 'Activities' }]} />
        <div className="page-toolbar-end">
          <SortControl label="Sort groups" value={sort} options={SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
          <ExportCSVButton loading={busy} disabled={!data?.rows.length} onClick={() => void exportCsv()} title={`Exports distinct users per SAP user group and ${risk ? 'risk' : 'activity'}.`} />
        </div>
      </div>
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        : !data ? <LoadingState />
        : !rows.length ? <EmptyState>No potential conflicts in current evidence. Results describe imported evidence only.</EmptyState>
        : <>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="SAP user group heatmap table">
            <table className="sod-heatmap">
              <caption className="sr-only">Distinct users per SAP user group and {risk ? 'risk' : 'activity'}. A user in several groups counts in each group.</caption>
              <thead><tr><th scope="col">SAP user group</th><th scope="col">Users</th>{columns.map((column) => <th scope="col" key={idOf(column)}><SodPill kind={kind} value={idOf(column)} /></th>)}</tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.user}>
                    <th scope="row">{row.user}</th>
                    <td>{(row.users ?? 0).toLocaleString()}</td>
                    {columns.map((column) => {
                      const cell = row.cells[idOf(column)] as GroupCell | undefined
                      return <td key={idOf(column)}>{cell
                        ? <button type="button" className="sod-heat-cell" style={{ ['--heat' as string]: heat(cell.users) }} aria-label={`${cell.users} ${cell.users === 1 ? 'user' : 'users'} in group ${row.user} with ${idOf(column)}. Show these users.`}
                            onClick={() => onOpen(kind, { group: row.user, [risk ? 'risk' : 'activity']: idOf(column) })}>{cell.users}</button>
                        : <span className="sod-heat-empty" aria-label="No users">·</span>}</td>
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><th scope="row">Distinct users</th><td>{data.totals.users.toLocaleString()}</td>{columns.map((column) => <td key={idOf(column)}>{column.users.toLocaleString()}</td>)}</tr></tfoot>
            </table>
          </div>
          <p className="ui-description">A user in several SAP user groups counts in each group, so group counts can add up to more than the distinct total. {data.columns.length > MAX_COLUMNS ? `Showing the ${MAX_COLUMNS} most affected of ${data.columns.length} ${risk ? 'risks' : 'activities'}; ` : ''}the matrix and the CSV list all of them.</p>
          {data.total_rows > rows.length && <Button variant="ghost" onClick={() => onOpen(kind, {})}>Open the full matrix</Button>}
        </>}
    </section>
  )
}
