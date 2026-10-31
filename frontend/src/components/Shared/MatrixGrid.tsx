import { RoleIdentifier } from './RoleIdentifier'
import { UserGroupCell } from './UserGroup'
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

export interface MatrixColumnDef { id: string; label: string; node?: ReactNode; title?: string; sub?: string; onFilter?: () => void }
export interface MatrixCellView { icon: ReactNode; text: string; sub?: string; tone?: 'neutral' | 'success' | 'warning' | 'error' | 'info'; label: string }
const CELL = 96
const HEAD = 190
const GROUP = 150
const OVERSCAN = 6
const WINDOW_FROM = 48

/** Sticky-header matrix with a fixed first column, roving-focus arrow navigation and column windowing for wide data. */
/** Scroll offsets survive remounts (for example Back from a role page) within the session. */
const scrollMemory = new Map<string, { left: number; top: number }>()

export interface MatrixGroupDef { id: string; label: string; summary: string; collapsed: boolean; onToggle: () => void }

export function MatrixGrid({ caption, rowLabel, columns, rows, cell, onSelect, onRow, selected, scrollKey, codeRows, groups, groupColumn }: {
  /** Adds a dedicated "SAP User Group" column right after the row identity (rows carry `groups`). Leave it off when the groups are already the row headers. */
  groupColumn?: boolean
  /** Collapsible group headers in display order; rows name their group. A collapsed group has a header and no rows. */
  groups?: MatrixGroupDef[]
  scrollKey?: string
  /** Row labels are identifiers (for example SAP usernames) and render as copyable codeblocks. */
  codeRows?: boolean
  caption: string
  rowLabel: string
  columns: MatrixColumnDef[]
  /** `sub` is a secondary note (for example other groups of the user); it is kept as a tooltip and screen reader text, never as a second line under the identity. */
  rows: { id: string; label: string; sub?: string; group?: string; groups?: string[] }[]
  cell: (row: string, column: string) => MatrixCellView | null
  onSelect: (row: string, column: string) => void
  onRow?: (row: string) => void
  selected?: { row: string; col: string } | null
}) {
  const scroller = useRef<HTMLDivElement>(null),
    [range, setRange] = useState({ left: 0, width: 960 }),
    [active, setActive] = useState<string>(''),
    wanted = useRef(false),
    windowed = columns.length > WINDOW_FROM
  useEffect(() => {
    const node = scroller.current,
      saved = scrollKey ? scrollMemory.get(scrollKey) : undefined
    if (!node || !scrollKey) return
    if (saved) { node.scrollLeft = saved.left; node.scrollTop = saved.top }
    const remember = () => scrollMemory.set(scrollKey, { left: node.scrollLeft, top: node.scrollTop })
    node.addEventListener('scroll', remember, { passive: true })
    return () => node.removeEventListener('scroll', remember)
  }, [scrollKey])
  useEffect(() => {
    const node = scroller.current
    if (!node || !windowed) return
    const measure = () => setRange({ left: node.scrollLeft, width: node.clientWidth })
    measure()
    node.addEventListener('scroll', measure, { passive: true })
    window.addEventListener('resize', measure)
    return () => {
      node.removeEventListener('scroll', measure)
      window.removeEventListener('resize', measure)
    }
  }, [windowed, columns.length])
  const first = windowed ? Math.max(0, Math.floor(range.left / CELL) - OVERSCAN) : 0,
    last = windowed ? Math.min(columns.length, Math.ceil((range.left + range.width) / CELL) + OVERSCAN) : columns.length,
    visible = columns.slice(first, last)
  const exists = (r: number, c: number) => !!rows[r] && !!columns[c] && !!cell(rows[r].id, columns[c].id)
  let firstKey = ''
  for (let r = 0; r < rows.length && !firstKey; r++) for (let c = first; c < last && !firstKey; c++) if (exists(r, c)) firstKey = `${r}:${c}`
  const current = active || firstKey
  useEffect(() => {
    if (!wanted.current || !active) return
    // Windowed columns render after the scroll event; keep waiting until the target cell exists.
    const target = scroller.current?.querySelector<HTMLElement>(`[data-cell="${active}"]`)
    if (target) {
      wanted.current = false
      target.focus()
    }
  }, [active, first, last])
  const move = (event: KeyboardEvent<HTMLElement>) => {
    const delta: Record<string, [number, number]> = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] }
    const target = (event.target as HTMLElement).closest<HTMLElement>('[data-cell]')
    if (!target) return
    const [r0, c0] = target.dataset.cell!.split(':').map(Number)
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      for (let step = 0; step < columns.length; step++) {
        const candidate = event.key === 'Home' ? step : columns.length - 1 - step
        if (exists(r0, candidate)) return go(r0, candidate)
      }
      return
    }
    const step = delta[event.key]
    if (!step) return
    event.preventDefault()
    if (step[0] !== 0) {
      // Sparse matrices: move to the nearest detected cell in the next row that has one.
      for (let r = r0 + step[0]; r >= 0 && r < rows.length; r += step[0]) {
        let best = -1
        for (let c = 0; c < columns.length; c++) if (exists(r, c) && (best < 0 || Math.abs(c - c0) < Math.abs(best - c0))) best = c
        if (best >= 0) return go(r, best)
      }
      return
    }
    for (let c = c0 + step[1]; c >= 0 && c < columns.length; c += step[1]) if (exists(r0, c)) return go(r0, c)
  }
  const go = (r: number, c: number) => {
    const node = scroller.current
    if (node && windowed) {
      const left = c * CELL
      if (left < node.scrollLeft) node.scrollLeft = left
      else if (left + CELL > node.scrollLeft + node.clientWidth - pinned) node.scrollLeft = left + CELL - node.clientWidth + pinned
    }
    wanted.current = true
    setActive(`${r}:${c}`)
  }
  const pinned = HEAD + (groupColumn ? GROUP : 0)
  const renderRow = (row: { id: string; label: string; sub?: string; group?: string; groups?: string[] }, r: number) => (
            <tr key={row.id}>
              <th scope="row" className="matrix-row-head" title={row.sub || undefined}>
                {codeRows ? <RoleIdentifier value={row.label} label="SAP username" onOpen={onRow ? () => onRow(row.id) : undefined} openLabel={`Open ${row.label}`} /> : onRow ? <button type="button" className="matrix-row-button" onClick={() => onRow(row.id)} aria-label={`Open ${row.label}`}>{row.label}</button> : row.label}
                {row.sub && <span className="sr-only">{row.sub}</span>}
              </th>
              {groupColumn && <td className="matrix-identity-group"><UserGroupCell groups={row.groups} /></td>}
              {first > 0 && <td aria-hidden="true" colSpan={first} className="matrix-spacer" />}
              {visible.map((column, offset) => {
                const c = first + offset,
                  view = cell(row.id, column.id),
                  key = `${r}:${c}`
                if (!view) return <td key={column.id} className="matrix-cell matrix-empty"><span className="sr-only">No detected evidence</span></td>
                return (
                  <td key={column.id} className="matrix-cell" data-tone={view.tone || 'neutral'}>
                    <button type="button" data-cell={key} tabIndex={current === key ? 0 : -1} aria-label={view.label} aria-current={selected?.row === row.id && selected.col === column.id ? 'true' : undefined}
                      onFocus={() => setActive(key)} onClick={() => onSelect(row.id, column.id)}>
                      <span className="matrix-pill"><span className="matrix-icon" aria-hidden="true">{view.icon}</span><span className="matrix-text">{view.text}</span></span>
                      {view.sub && <span className="matrix-sub">{view.sub}</span>}
                    </button>
                  </td>
                )
              })}
              {last < columns.length && <td aria-hidden="true" colSpan={columns.length - last} className="matrix-spacer" />}
            </tr>
  )
  return (
    <div className="matrix-scroll" ref={scroller} role="region" aria-label={`Scrollable ${caption}`} onKeyDown={move}>
      <table className="matrix-grid" data-group-column={groupColumn || undefined} style={{ width: pinned + columns.length * CELL, ['--matrix-head' as string]: `${HEAD}px` }}>
        <caption className="sr-only">{caption}. Use arrow keys to move between detected cells; Enter opens the investigation.</caption>
        <colgroup>
          <col style={{ width: HEAD }} />
          {groupColumn && <col style={{ width: GROUP }} />}
          {columns.map((column) => <col key={column.id} style={{ width: CELL }} />)}
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className="matrix-corner">{rowLabel}</th>
            {groupColumn && <th scope="col" className="matrix-corner matrix-corner-group">SAP User Group</th>}
            {first > 0 && <th aria-hidden="true" colSpan={first} className="matrix-spacer" />}
            {visible.map((column) => (
              <th key={column.id} scope="col" className="matrix-col" title={column.title || column.label}>
                {column.onFilter ? <button type="button" className="matrix-col-button" onClick={column.onFilter} aria-label={`Filter to ${column.label}`}>{column.node ?? column.label}</button> : column.node ?? column.label}
                {column.sub && <small>{column.sub}</small>}
              </th>
            ))}
            {last < columns.length && <th aria-hidden="true" colSpan={columns.length - last} className="matrix-spacer" />}
          </tr>
        </thead>
        <tbody>
          {(groups ?? [{ id: '', label: '', summary: '', collapsed: false, onToggle: () => undefined }]).map((group) => {
            const members = rows.map((row, r) => ({ row, r })).filter(({ row }) => !groups || row.group === group.id)
            return [
              groups && <tr key={`group:${group.id}`} className="matrix-group-row" data-collapsed={group.collapsed || undefined}>
                <th scope="rowgroup" className="matrix-row-head matrix-group-head">
                  <button type="button" className="matrix-group-toggle" aria-expanded={!group.collapsed} aria-label={`${group.collapsed ? 'Expand' : 'Collapse'} SAP User Group ${group.label}`} onClick={group.onToggle}>
                    {group.collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}<span>{group.label}</span>
                  </button>
                  <small>{group.summary}</small>
                </th>
                <td colSpan={Math.max(1, columns.length) + (groupColumn ? 1 : 0)} className="matrix-group-fill" aria-hidden="true" />
              </tr>,
              ...members.map(({ row, r }) => renderRow(row, r)),
            ]
          })}
        </tbody>
      </table>
    </div>
  )
}
