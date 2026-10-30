import { Fragment, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { downloadFile, scopeParams, sod, sodPost, EXPORT_NAME, type AssignmentRow, type ContextInfo } from '@/api/sod'
import { useViewHistory } from '@/hooks/useViewHistory'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { ErrorState, DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { FormField, Input } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { NorwegianDateInput, parseNorwegianDate } from '@/components/Shared/NorwegianDateInput'
import { PAGE_SIZES, Pagination } from '@/components/Access/Shared'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { SodPill } from '@/lib/sodAppearance'
import { RoleEntry } from '@/components/Shared/RoleEntry'
import { moduleOfRoles, useRoleModules } from '@/hooks/useRoleModules'
import { announceExport } from '@/lib/exportNotice'
import { formatDate } from '@/lib/dateFormat'
import { AlertNote, CoverageNotice, SodFilters, invalidateSod, LifecycleBadge, useSodContext, useSodFilters, useSodSubject } from './SodShared'

const GROUPS = ['Remove assignment', 'Investigate assignment', 'Apply compensating control', 'Maintain access', 'No action required']
/** Handling that can carry a tracked action: removals and investigations. */
const TRACKABLE = ['Remove assignment', 'Investigate assignment']
const STATUSES = ['Open', 'In progress', 'Completed', 'Cancelled']
interface TrackedAction { id: string; user: string; activity: string; risk_id: string; assignment_id: string; role: string; recommended: string; reason: string; owner: string; due_date: string | null; status: string; completion_evidence: string; verification: string; history: { timestamp: string; actor: string; note: string }[] }
interface Row {
  user: string; activity: string; risks: string[]; role: string; catalogue_roles?: string[]; user_group?: string; assignment_id: string; valid_from: string | null; valid_to: string | null
  activity_decision: string; assignment_decision: string; risk_acceptance: string[]; recommended: string; reason: string; controls: string
  action: TrackedAction | null; owner: string; due_date: string | null; action_status: string; overdue: boolean; verification: string
}
interface Result extends ContextInfo { items: Row[]; total: number; summary: Record<string, number>; actions: TrackedAction[]; offset: number; limit: number }

const actorKey = 'sap-lens-sod-reviewer'
const remembered = () => { try { return sessionStorage.getItem(actorKey) || '' } catch { return '' } }

/** Create or update a tracked action. Completion is a manual claim; verification comes only from later source evidence. */
export function ActionDialog({ context, revision, user, assignment, row, risk, onClose, onSaved }: {
  context: string; revision: number; user: string; assignment?: AssignmentRow; row?: Row; risk?: string; onClose: () => void; onSaved: () => Promise<void>
}) {
  const existing = row?.action || null,
    [recommended, setRecommended] = useState(existing?.recommended || row?.recommended || 'Remove assignment'),
    [reason, setReason] = useState(existing?.reason || row?.reason || assignment?.event?.justification || ''),
    [owner, setOwner] = useState(existing?.owner || ''),
    [due, setDue] = useState(existing?.due_date ? formatDate(existing.due_date, '') : ''),
    [status, setStatus] = useState(existing?.status || 'Open'),
    [evidence, setEvidence] = useState(existing?.completion_evidence || ''),
    [actor, setActor] = useState(remembered),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const role = assignment?.role || row?.role || '', assignmentId = assignment?.id || row?.assignment_id || ''
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const date = due ? parseNorwegianDate(due) : null
      if (due && !date) throw Error('Use DD.MM.YYYY for the due date.')
      await sodPost('/api/sod/remediation/actions', {
        context, expected_revision: revision, actor, action_id: existing?.id || '', user, activity: row?.activity || '', risk_id: risk || row?.risks[0] || '',
        assignment_id: assignmentId, role, recommended, reason, owner, due_date: date, status, completion_evidence: evidence,
      })
      try { sessionStorage.setItem(actorKey, actor) } catch { /* optional convenience */ }
      await onSaved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The action could not be saved.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog title={existing ? 'Update remediation action' : 'Track remediation action'} onClose={onClose}
      footer={<><Button loading={busy} disabled={!actor.trim() || !reason.trim()} onClick={() => void save()}>Save action</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></>}>
      <p>{user}{role ? ` · ${role}` : ''}</p>
      <AlertNote>A completed action is a manual statement. It does not prove access was removed; only later source evidence can show that.</AlertNote>
      <FormField label="Recommended handling"><Select value={recommended} onChange={(event) => setRecommended(event.target.value)}>{GROUPS.map((value) => <option key={value}>{value}</option>)}</Select></FormField>
      <FormField label="Reason"><textarea className="ui-control min-h-20" value={reason} maxLength={4000} onChange={(event) => setReason(event.target.value)} /></FormField>
      <FormField label="Assigned owner"><Input value={owner} maxLength={120} onChange={(event) => setOwner(event.target.value)} /></FormField>
      <NorwegianDateInput label="Due date" value={due} onChange={setDue} />
      <FormField label="Status"><Select value={status} onChange={(event) => setStatus(event.target.value)}>{STATUSES.map((value) => <option key={value}>{value}</option>)}</Select></FormField>
      {status === 'Completed' && <FormField label="Completion evidence"><textarea className="ui-control min-h-16" value={evidence} maxLength={4000} onChange={(event) => setEvidence(event.target.value)} /></FormField>}
      <FormField label="Recorded by (self-reported)"><Input value={actor} maxLength={120} onChange={(event) => setActor(event.target.value)} /></FormField>
      {error && <p role="alert">{error}</p>}
    </Dialog>
  )
}

/** Parent row plus its expandable activity rows, kept together so the table stays a single valid tbody. */
function ParentRows({ parent, children, open }: { parent: ReactNode; children: ReactNode; open: boolean }) {
  return <Fragment>{parent}{open && children}</Fragment>
}

function RemediationRole({ role, catalogueRoles }: { role: string; catalogueRoles?: string[] }) {
  const code = moduleOfRoles(useRoleModules(), catalogueRoles)
  return <RoleEntry density="compact" moduleCode={code} title="Assigned role" identifier={role} identifierLabel="assigned role" />
}

export function RemediationView() {
  const qc = useQueryClient(),
    { change } = useViewHistory(),
    [context] = useSodContext(),
    [filters, setFiltersState] = useSodFilters('remediation'),
    [recommended, setRecommended] = useState(''),
    [offset, setOffset] = useState(0),
    [editing, setEditing] = useState<Row | null>(null),
    [, setSubject] = useSodSubject(),
    [busy, setBusy] = useState(false),
    [pageSize, setPageSizeState] = useState(50),
    [openKeys, setOpenKeys] = useState<Set<string>>(new Set())
  const toggleKey = (key: string) => setOpenKeys((previous) => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next })
  const params = scopeParams(context, filters, { recommended, offset, limit: pageSize })
  const result = useQuery({ queryKey: ['sod-remediation', params.toString()], queryFn: () => sod<Result>('/api/sod/remediation', params) })
  const data = result.data
  /** One parent per SAP user and role assignment; the server orders rows by user and role, so activity rows are contiguous. */
  const parents = (data?.items || []).reduce<{ key: string; user: string; rows: Row[] }[]>((list, row) => {
    const key = `${row.user}:${row.assignment_id}`, last = list[list.length - 1]
    if (last?.key === key) last.rows.push(row); else list.push({ key, user: row.user, rows: [row] })
    return list
  }, [])
  const exportCsv = async () => {
    setBusy(true)
    try {
      const name = await downloadFile('/api/sod/remediation/export', { params: scopeParams(context, filters, { recommended }), namePattern: EXPORT_NAME, kind: 'csv' })
      announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (cause) {
      announceExport({ kind: 'error', message: cause instanceof Error ? cause.message : 'Export failed.' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD remediation">
      <CoverageNotice info={data} />
      <SodFilters view="sod_queue" filters={filters} setFilters={(value) => { setOffset(0); setFiltersState(value) }}
        fields={['group', 'username', 'risk', 'activity', 'role', 'role_suffix', 'tcode', 'category', 'validity']}
        actions={<ExportCSVButton loading={busy} disabled={!data?.total} onClick={() => void exportCsv()} title="Exports the filtered remediation rows." />}>
      {result.isError ? <ErrorState error={result.error} onRetry={() => void result.refetch()} /> : !data ? <LoadingState /> : <>
        <Toolbar aria-label="Recommended handling">
          <Button variant={recommended ? 'secondary' : 'primary'} aria-pressed={!recommended} onClick={() => { setRecommended(''); setOffset(0) }}>All handling</Button>
          {GROUPS.map((group) => <Button key={group} variant={recommended === group ? 'primary' : 'secondary'} aria-pressed={recommended === group} onClick={() => { setRecommended(group); setOffset(0) }}>{group}: {data.summary[group] ?? 0}</Button>)}
          <StatusBadge tone={data.summary.undecided ? 'warning' : 'neutral'}>{data.summary.undecided ?? 0} awaiting review (not listed)</StatusBadge>
          <StatusBadge tone={data.summary.overdue ? 'error' : 'neutral'}>{data.summary.overdue ?? 0} overdue</StatusBadge>
          <Button variant="ghost" onClick={() => change({ sodView: 'reports' })}>Remediation report</Button>
        </Toolbar>
        <p className="ui-description">A proposed removal is not completed remediation. Verification compares with the latest imported evidence and is only conclusive when source coverage is complete.</p>
        {data.items.length ? <>
          <Toolbar aria-label="Remediation row controls">
            <span className="ui-description" role="status">{parents.length} {parents.length === 1 ? 'assignment' : 'assignments'} · {data.items.length} activity {data.items.length === 1 ? 'row' : 'rows'} on this page</span>
            <Button size="compact" onClick={() => setOpenKeys(new Set(parents.map((parent) => parent.key)))}>Expand all</Button>
            <Button size="compact" onClick={() => setOpenKeys(new Set())}>Collapse all</Button>
          </Toolbar>
          <DataTable caption="Access remediation rows" density="compact" sticky>
            <thead><tr><th>SAP user</th><th>Role assignment</th><th>Validity</th><th>Review</th><th>Recommended handling</th><th>Remediation</th><th className="col-actions">Actions</th></tr></thead>
            <tbody>{parents.map((parent) => {
              const open = openKeys.has(parent.key), first = parent.rows[0], tracked = parent.rows.find((row) => row.action) ?? first
              const decided = parent.rows.filter((row) => row.activity_decision !== 'Pending').length
              return <ParentRows key={parent.key} open={open}
                parent={<tr className="remediation-parent" data-open={open || undefined}>
                  <td><button type="button" className="sod-expand-toggle" aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} activities and risks for ${parent.user} ${first.role}`} onClick={() => toggleKey(parent.key)}>{open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}<strong>{parent.user}</strong></button>
                    <p className="text-xs text-muted whitespace-nowrap">SAP User Group: {first.user_group || 'Unknown'}</p></td>
                  <td><RemediationRole role={first.role} catalogueRoles={first.catalogue_roles} /></td>
                  <td className="whitespace-nowrap"><dl className="validity-dates"><div><dt>Valid from</dt><dd>{formatDate(first.valid_from)}</dd></div><div><dt>Valid to</dt><dd>{formatDate(first.valid_to)}</dd></div></dl></td>
                  <td><LifecycleBadge value={first.assignment_decision} /><p className="text-xs text-muted">{decided}/{parent.rows.length} activities decided</p></td>
                  <td>{[...new Set(parent.rows.map((row) => row.recommended))].sort((x, y) => GROUPS.indexOf(x) - GROUPS.indexOf(y)).map((value) => <StatusBadge key={value} tone={value === 'Remove assignment' ? 'error' : value === 'Investigate assignment' ? 'warning' : 'neutral'}>{value}</StatusBadge>)}</td>
                  <td>{tracked.action_status}{parent.rows.some((row) => row.overdue) && <StatusBadge tone="error">Overdue</StatusBadge>}<p className="text-xs text-muted">{tracked.owner || 'No owner'} · {tracked.due_date ? formatDate(tracked.due_date) : 'No due date'}</p></td>
                  <td className="col-actions"><div className="flex flex-wrap justify-end gap-1">
                    {data.reviewable && parent.rows.some((row) => TRACKABLE.includes(row.recommended)) && <Button size="compact" onClick={() => setEditing(parent.rows.find((row) => TRACKABLE.includes(row.recommended))!)}>{tracked.action ? 'Update action' : 'Track action'}</Button>}
                    <Button size="compact" onClick={() => setSubject({ user: parent.user, activity: first.activity })}>Investigate</Button>
                  </div></td>
                </tr>}
                children={parent.rows.map((row) => <tr key={row.activity} className="remediation-child">
                  <td colSpan={2}><span className="remediation-child-title">Activity</span> <SodPill kind="activity" value={row.activity} /> <span className="id-pill-list" aria-label={`Risks for ${row.activity}`}>{row.risks.map((risk) => <SodPill key={risk} kind="risk" value={risk} />)}</span></td>
                  <td colSpan={2}>Activity <LifecycleBadge value={row.activity_decision} /> · Risk acceptance: {row.risk_acceptance.join(', ') || '—'}</td>
                  <td><StatusBadge tone={row.recommended === 'Remove assignment' ? 'error' : row.recommended === 'Investigate assignment' ? 'warning' : 'neutral'}>{row.recommended}</StatusBadge><p className="text-xs">{row.reason || row.controls}</p></td>
                  <td className="text-xs" colSpan={2}>Verification: {row.verification}</td>
                </tr>)} />
            })}</tbody>
          </DataTable></> : <EmptyState>No decided items match. Pending reviews are excluded until a decision is recorded.</EmptyState>}
        <Pagination label="Remediation pages" offset={data.offset} total={data.total} limit={data.limit} onChange={setOffset} pageSizes={PAGE_SIZES} onPageSize={(value) => { setPageSizeState(value); setOffset(0) }} />
        {data.actions.length > 0 && <>
          <h3 className="text-base font-semibold">Tracked actions</h3>
          <DataTable caption="Tracked remediation actions">
            <thead><tr><th>Action</th><th>Owner / due</th><th>Status</th><th>Verification</th></tr></thead>
            <tbody>{data.actions.map((action) => (
              <tr key={action.id}><td>{action.user} · {action.role || action.activity || action.risk_id}<p className="text-xs">{action.recommended}: {action.reason}</p></td>
                <td>{action.owner || '—'}<p>{action.due_date ? formatDate(action.due_date) : '—'}</p></td><td>{action.status}{action.completion_evidence && <p className="text-xs">{action.completion_evidence}</p>}</td><td className="text-xs">{action.verification}</td></tr>))}</tbody>
          </DataTable></>}
      </>}
      </SodFilters>
      {editing && data && <ActionDialog context={context} revision={data.revision} user={editing.user} row={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await invalidateSod(qc) }} />}
    </section>
  )
}
