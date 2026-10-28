import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, FlaskConical, History, Wrench } from 'lucide-react'
import { emptyFilters, scopeParams, sod, sodPost, type ActivityDetail, type AssignmentRow, type DecisionEvent, type Subject } from '@/api/sod'
import { useViewHistory } from '@/hooks/useViewHistory'
import { SidePanel } from '@/components/Shared/SidePanel'
import { Button } from '@/components/Shared/Button'
import { Card, ErrorState, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { Checkbox, FormField, Input } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { NorwegianDateInput, parseNorwegianDate } from '@/components/Shared/NorwegianDateInput'
import { formatDate, formatTimestamp } from '@/lib/dateFormat'
import { SodPill } from '@/lib/sodAppearance'
import { AlertNote, invalidateSod, KIND_LABEL, LifecycleBadge } from './SodShared'
import { ActionDialog } from './SodRemediation'

type Kind = 'activity' | 'assignment' | 'acceptance'
export interface Item { key: string; user: string; ref: string; evidence_version: string }
export interface FormState { kind: Kind; items: Item[]; heading: string; decision?: string }
const OPTIONS: Record<Kind, { value: string; label: string }[]> = {
  activity: [{ value: 'Approved', label: 'Approved: the user needs this activity' }, { value: 'Conditional', label: 'Conditional: approved with conditions' }, { value: 'Remove', label: 'Remove: the user should not have this activity' }, { value: 'Pending', label: 'Reset to pending' }],
  assignment: [{ value: 'Keep', label: 'Keep this role assignment' }, { value: 'Remove', label: 'Remove this role assignment' }, { value: 'Pending', label: 'Reset to pending' }],
  acceptance: [{ value: 'Accepted', label: 'Accept the risk' }, { value: 'Rejected', label: 'Reject the risk' }, { value: 'Pending', label: 'Reset to pending' }],
}
const reviewerKey = 'sap-lens-sod-reviewer'
const rememberedReviewer = () => { try { return sessionStorage.getItem(reviewerKey) || '' } catch { return '' } }

const DECIDED = new Set(['Approved', 'Keep', 'Accepted', 'Conditional', 'Removal required', 'Rejected'])
const progressOf = (rows: { decision?: string; acceptance?: string }[]) => rows.filter((row) => DECIDED.has((row.decision ?? row.acceptance) as string)).length

/** Unified review workspace for one SAP user: three independent review sections, history on demand and read-only supporting evidence. */
export function SodInvestigation({ context, user, risk, activity, onClose }: { context: string; user: string; risk?: string; activity?: string; onClose: () => void }) {
  const qc = useQueryClient(),
    { change } = useViewHistory(),
    [form, setForm] = useState<FormState | null>(null),
    [picked, setPicked] = useState<Record<Kind, string[]>>({ activity: [], assignment: [], acceptance: [] }),
    [selection, setSelection] = useState<string[]>([]),
    [simulation, setSimulation] = useState<null | { before: string[]; after: string[]; resolved: string[]; lost_activities: string[]; warnings: string[]; eliminates_all: boolean }>(null),
    [error, setError] = useState(''),
    [action, setAction] = useState<null | { assignment: AssignmentRow }>(null),
    formRef = useRef<HTMLDivElement>(null)
  const params = scopeParams(context, emptyFilters, { user, ...(risk ? { risk } : {}), ...(activity ? { activity } : {}) })
  const query = useQuery({ queryKey: ['sod-subject', params.toString()], queryFn: () => sod<Subject>('/api/sod/subject', params) })
  const data = query.data
  const ok = !!data?.reviewable
  useEffect(() => { if (form) formRef.current?.scrollIntoView?.({ block: 'nearest' }) }, [form])
  const simulate = async (removed: string[]) => {
    setError('')
    try { setSimulation(await sodPost('/api/sod/simulate', { context, user, removed })) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Simulation failed.') }
  }
  const toggle = (id: string) => { setSimulation(null); setSelection((previous) => (previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id])) }
  const pick = (kind: Kind, key: string) => setPicked((previous) => ({ ...previous, [kind]: previous[kind].includes(key) ? previous[kind].filter((value) => value !== key) : [...previous[kind], key] }))
  const item = (key: string, ref: string, version: string): Item => ({ key, user, ref, evidence_version: version })
  const overview = data?.overview
  const activities = overview?.activities || [], assignments = overview?.assignments || [], risks = overview?.risks || []
  const total = activities.length + assignments.length + risks.length
  const done = progressOf(activities) + progressOf(assignments) + progressOf(risks)
  const batch = (kind: Kind, heading: string, rows: Item[]) => setForm({ kind, items: rows, heading })
  const focus = (name: string, kind: 'activity' | 'risk') => (kind === 'activity' ? activity === name : risk === name)
  return (
    <SidePanel title={`${user}${risk ? ` · ${risk}` : activity ? ` · ${activity}` : ''}`} subtitle={data ? <>Potential conflict evidence, not effective authorization · evaluation {formatDate(data.as_of)}</> : undefined} onClose={onClose}
      footer={data ? <><span className="text-xs" role="status">{done} of {total} reviews decided</span><Button variant="ghost" onClick={onClose}>Close</Button></> : undefined}>
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : !data || !overview ? <LoadingState /> : <>
        <section className="sod-section" aria-label="Subject summary">
          <Toolbar>
            <RoleIdentifier value={user} label="SAP username" onOpen={() => change({ page: 'users', accessMode: 'directory', user, userContext: {}, detailRole: null, settings: false })} openLabel={`Open SAP user ${user}`} />
            {data.groups.map((group) => <StatusBadge key={group}>{group}</StatusBadge>)}
            {data.frozen && <StatusBadge tone="info">Frozen snapshot, read only</StatusBadge>}
            {!data.frozen && !data.reviewable && <StatusBadge>Read only</StatusBadge>}
          </Toolbar>
          {data.account && <p className="ui-description">Directory match: {data.account.directory_match.replace(/_/g, ' ')} · AD {data.account.ad_status}{data.account.lock_status ? ` · SAP ${data.account.lock_status}` : ''}</p>}
          <p className="ui-description">Activity review, role assignment review and risk acceptance are separate decisions. None of them changes what is detected or changes SAP.</p>
        </section>
        {form && <div ref={formRef}><DecisionForm key={form.heading} form={form} subject={data} onCancel={() => setForm(null)} onSaved={async () => { setForm(null); setPicked({ activity: [], assignment: [], acceptance: [] }); await invalidateSod(qc) }} /></div>}

        <ReviewSection title="Activity Review" kind="activity" done={progressOf(activities)} total={activities.length} ok={ok} picked={picked.activity}
          onBatch={() => batch('activity', `Batch activity review (${picked.activity.length})`, activities.filter((row) => picked.activity.includes(row.key)).map((row) => item(row.key, row.activity, row.evidence_version)))}>
          {activities.map((row) => (
            <ReviewRow key={row.key} focused={focus(row.activity, 'activity')} label={row.activity} checked={picked.activity.includes(row.key)} onCheck={ok ? () => pick('activity', row.key) : undefined}
              title={<SodPill kind="activity" value={row.activity} />} meta={<>{row.roles} role assignment{row.roles === 1 ? '' : 's'}{row.duplicate_coverage ? ' · overlapping coverage' : ''} · risks {row.risks.join(', ')}</>} status={row.decision} event={row.event}
              actions={ok && <Button onClick={() => setForm({ kind: 'activity', heading: `Activity review · ${row.activity}`, items: [item(row.key, row.activity, row.evidence_version)] })} aria-label={`Review activity ${row.activity}`}><ClipboardCheck size={16} aria-hidden="true" />Review</Button>}
              history={<DecisionHistory kind="activity" context={context} keyId={row.key} label="Activity review history" />} />
          ))}
        </ReviewSection>

        <ReviewSection title="Role Assignment Review" kind="assignment" done={progressOf(assignments)} total={assignments.length} ok={ok} picked={picked.assignment}
          note="Reviewed with the other activities each role supplies, so one assignment can serve several approved activities."
          onBatch={() => batch('assignment', `Batch role assignment review (${picked.assignment.length})`, assignments.filter((row) => picked.assignment.includes(row.id)).map((row) => item(row.id, row.role, row.evidence_version)))}>
          {assignments.map((row) => (
            <ReviewRow key={row.id} label={row.role} checked={picked.assignment.includes(row.id)} onCheck={ok ? () => pick('assignment', row.id) : undefined}
              title={<RoleIdentifier value={row.role} onOpen={() => change({ detailRole: row.catalogue_roles[0] || row.role })} openLabel={`Open catalogue role ${row.catalogue_roles[0] || row.role}`} />}
              meta={<>{row.user_group || 'No user group'} · {row.interval_status && <AssignmentStatus value={row.interval_status} />} {formatDate(row.valid_from)} → {formatDate(row.valid_to)} · supplies {row.activities.join(', ')}</>} status={row.decision} event={row.event}
              actions={ok && <>
                <Button onClick={() => setForm({ kind: 'assignment', heading: `Role assignment · ${row.role}`, decision: 'Keep', items: [item(row.id, row.role, row.evidence_version)] })} aria-label={`Keep ${row.role}`}>Keep</Button>
                <Button onClick={() => setForm({ kind: 'assignment', heading: `Role assignment · ${row.role}`, decision: 'Remove', items: [item(row.id, row.role, row.evidence_version)] })} aria-label={`Remove ${row.role}`}>Remove</Button>
                {row.decision === 'Removal required' && <Button onClick={() => setAction({ assignment: { id: row.id, role: row.role, valid_from: row.valid_from, valid_to: row.valid_to, user_group: row.user_group, interval_status: row.interval_status, tcodes: [], other_activities: row.activities, risks: row.risks, catalogue_roles: row.catalogue_roles, evidence_version: row.evidence_version, decision: row.decision, event: row.event } })}>Track action</Button>}
              </>}
              history={<DecisionHistory kind="assignment" context={context} keyId={row.id} label="Assignment review history" />} />
          ))}
        </ReviewSection>

        <ReviewSection title="Risk Acceptance" kind="acceptance" done={progressOf(risks)} total={risks.length} ok={ok} picked={picked.acceptance}
          note="Accepting a risk needs a justification, an approver different from the reviewer and optional controls. It never suppresses detection."
          onBatch={() => batch('acceptance', `Batch risk acceptance (${picked.acceptance.length})`, risks.filter((row) => picked.acceptance.includes(row.finding_id)).map((row) => item(row.finding_id, row.risk_id, row.evidence_version)))}>
          {risks.map((row) => (
            <ReviewRow key={row.finding_id} focused={focus(row.risk_id, 'risk')} label={row.risk_id} checked={picked.acceptance.includes(row.finding_id)} onCheck={ok ? () => pick('acceptance', row.finding_id) : undefined}
              title={<SodPill kind="risk" value={row.risk_id} />} meta={<>{row.display_name || row.source_text} · <span className="sod-meta">criticality {row.criticality}</span></>} status={row.acceptance} event={row.event}
              actions={ok && <Button onClick={() => setForm({ kind: 'acceptance', heading: `Risk acceptance · ${row.risk_id}`, items: [item(row.finding_id, row.risk_id, row.evidence_version)] })} aria-label={`Decide risk acceptance ${row.risk_id}`}><ClipboardCheck size={16} aria-hidden="true" />Decide</Button>}
              history={<DecisionHistory kind="acceptance" context={context} keyId={row.finding_id} label="Risk acceptance history" />} />
          ))}
        </ReviewSection>
        {!!data.risk?.legacy_decisions.length && <AlertNote>{data.risk.legacy_decisions.length} legacy risk decision(s) recorded before activity-level review are retained as history and were not converted to a risk acceptance.</AlertNote>}

        {total === 0 && <EmptyState>No conflict-relevant evidence for this user.</EmptyState>}

        <details className="sod-section" aria-label="Supporting evidence" open={!!(risk || activity)}>
          <summary><h3 className="inline">Supporting evidence and removal impact</h3></summary>
          {data.activities.map((row) => <ActivityBlock key={row.key} row={row} selection={selection} toggle={toggle} impact={data.impact?.per_assignment || {}} onRole={(name) => change({ detailRole: name })} />)}
          {data.impact && <section className="sod-section" aria-label="Remediation impact">
            <h3><Wrench size={14} className="mr-1 inline" aria-hidden="true" />Remediation impact</h3>
            <p className="ui-description">Several remediation options can be valid. This is a what-if over a copy of the evidence; it never changes SAP or imported data, and a removal recommendation is not confirmed removal.</p>
            {data.impact.options.map((option) => (
              <Card key={option.slot}>
                <p><strong>{option.slot === 'ACTVT1' ? 'Activity 1' : 'Activity 2'} ({option.activities.join(', ')})</strong>: remove all {option.assignments.length} supplying assignment(s) ({option.roles.join(', ')}) to {option.resolves_risk ? 'resolve this risk' : 'reduce evidence'}{option.also_resolves?.length ? `; also resolves ${option.also_resolves.join(', ')}` : ''}</p>
                {option.warnings.map((warning) => <AlertNote key={warning}>{warning}</AlertNote>)}
                <Button onClick={() => { setSelection(option.assignments); void simulate(option.assignments) }}><FlaskConical size={16} aria-hidden="true" />Simulate this option</Button>
              </Card>
            ))}
          </section>}
          <section className="sod-section" aria-label="What-if simulation">
            <h3><FlaskConical size={14} className="mr-1 inline" aria-hidden="true" />What-if removal</h3>
            <p className="ui-description">{selection.length ? `${selection.length} assignment(s) selected.` : 'Select role assignments above to simulate removing them.'}</p>
            <Button disabled={!selection.length} onClick={() => void simulate(selection)}>Simulate removal</Button>
            {error && <p role="alert">{error}</p>}
            {simulation && <Card aria-label="Simulation result">
              <p>Before: {simulation.before.join(', ') || 'none'} · After: {simulation.after.join(', ') || 'none'}</p>
              <p>Resolved by this change: {simulation.resolved.join(', ') || 'none'}{simulation.eliminates_all ? ' (all detected risks for this user)' : ''}</p>
              <p>Activities no longer supplied: {simulation.lost_activities.join(', ') || 'none'}</p>
              {simulation.warnings.map((warning) => <AlertNote key={warning}>{warning}</AlertNote>)}
            </Card>}
          </section>
          {data.related_risks.length > 0 && <p className="ui-description">Related risks for this user: {data.related_risks.join(', ')}</p>}
        </details>
      </>}
      {action && data && <ActionDialog context={context} revision={data.revision} user={user} assignment={action.assignment} risk={risk} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await invalidateSod(qc) }} />}
    </SidePanel>
  )
}

function ReviewSection({ title, kind, done, total, ok, picked, note, onBatch, children }: { title: string; kind: Kind; done: number; total: number; ok: boolean; picked: string[]; note?: string; onBatch: () => void; children: ReactNode }) {
  return (
    <section className="sod-section sod-review-section" aria-label={title} data-kind={kind}>
      <Toolbar><h3>{title}</h3><StatusBadge tone={total > 0 && done === total ? 'success' : 'neutral'}>{done}/{total} decided</StatusBadge>
        {ok && picked.length > 0 && <Button variant="primary" onClick={onBatch}>Review selected ({picked.length})</Button>}</Toolbar>
      {note && <p className="ui-description">{note}</p>}
      {total === 0 ? <p className="ui-description">Nothing to review in this section.</p> : <ul className="sod-review-list" aria-label={`${title} items`}>{children}</ul>}
    </section>
  )
}

function ReviewRow({ label, title, meta, status, event, actions, history, checked, onCheck, focused }: {
  label: string; title: ReactNode; meta: ReactNode; status: string; event: DecisionEvent | null; actions?: ReactNode; history: ReactNode; checked: boolean; onCheck?: () => void; focused?: boolean
}) {
  return (
    <li className="sod-review-row" data-focused={focused || undefined}>
      <div className="sod-review-main">
        {onCheck && <Checkbox checked={checked} onChange={onCheck} aria-label={`Select ${label}`}><span className="sr-only">Select</span></Checkbox>}
        <span className="min-w-0">{title}</span>
        <LifecycleBadge value={status} />
      </div>
      <p className="text-xs text-muted">{meta}</p>
      {event && <p className="text-xs text-muted">{event.decision} by {event.reviewer}, {formatTimestamp(event.timestamp)}: {event.justification}{event.controls ? ` Conditions: ${event.controls}` : ''}</p>}
      {actions && <div className="sod-review-actions">{actions}</div>}
      {history}
    </li>
  )
}

function ActivityBlock({ row, selection, toggle, impact, onRole }: {
  row: ActivityDetail; selection: string[]; toggle: (id: string) => void
  impact: Record<string, { resolves: string[]; remaining: string[]; lost_activities: string[]; affected_approved_activities: string[] }>
  onRole: (role: string) => void
}) {
  return (
    <section className="sod-section" aria-label={`Activity ${row.activity}`}>
      <Toolbar><h3>Activity {row.activity}</h3>{row.duplicate_coverage && <StatusBadge tone="info">Supplied by {row.assignments.length} assignments</StatusBadge>}</Toolbar>
      <p className="ui-description">Transactions: {row.tcodes.join(', ')} · Risks: {row.risks.join(', ')}</p>
      <ul className="grid gap-2" aria-label={`Role assignments supplying ${row.activity}`}>
        {row.assignments.map((assignment) => {
          const effect = impact[assignment.id]
          return (
            <li key={assignment.id} className="grid min-w-0 gap-2 rounded-card border border-line p-3">
              <Toolbar>
                <Checkbox checked={selection.includes(assignment.id)} onChange={() => toggle(assignment.id)} aria-label={`Include ${assignment.role} in what-if removal`}>Simulate</Checkbox>
                <RoleIdentifier value={assignment.role} onOpen={() => onRole(assignment.catalogue_roles[0] || assignment.role)} openLabel={`Open catalogue role ${assignment.catalogue_roles[0] || assignment.role} (evidence)`} />
              </Toolbar>
              <p className="text-xs text-muted">{assignment.user_group || 'No user group'} · {assignment.interval_status && <AssignmentStatus value={assignment.interval_status} />} {formatDate(assignment.valid_from)} → {formatDate(assignment.valid_to)}</p>
              <p className="text-xs">Transactions: {assignment.tcodes.join(', ')} · also supplies: {assignment.other_activities.join(', ') || 'no other relevant activity'} · contributes to {assignment.risks.join(', ')}</p>
              {effect && <p className="text-xs">Removing this alone: {effect.resolves.length ? `resolves ${effect.resolves.join(', ')}` : 'resolves no risk'}; {effect.remaining.length ? `still detected: ${effect.remaining.join(', ')}` : 'no detected risks remain'}.{effect.affected_approved_activities.length ? ` Would affect approved activities: ${effect.affected_approved_activities.join(', ')}.` : ''}</p>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function DecisionHistory({ kind, context, keyId, label }: { kind: Kind; context: string; keyId: string; label: string }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['sod-subject', 'history', kind, context, keyId], queryFn: () => sod<{ items: DecisionEvent[] }>(`/api/sod/decisions/${kind}/history`, new URLSearchParams({ key: keyId, context })), enabled: open })
  return (
    <details onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer items-center gap-1 text-xs"><History size={12} aria-hidden="true" />{label}</summary>
      {open && (query.isError ? <p role="alert">History unavailable; original storage is retained.</p> : !query.data ? <LoadingState /> : !query.data.items.length ? <p className="text-xs text-muted">No decisions recorded.</p>
        : <ol className="grid gap-2 py-2">{query.data.items.map((event) => (
          <li key={event.event_id} className="text-xs">
            <LifecycleBadge value={event.decision === 'Remove' ? 'Removal required' : event.decision} /> {event.reviewer}{event.approver ? ` / approver ${event.approver}` : ''} · {formatTimestamp(event.timestamp)}
            <p>{event.justification}</p>
            {event.controls && <p>Conditions or controls: {event.controls}</p>}
            {event.expires && <p>Expires {formatDate(event.expires)}</p>}
            <p className="text-muted">Evidence version {event.evidence_version.slice(0, 12)} retained with this decision.</p>
          </li>))}</ol>)}
    </details>
  )
}

export function DecisionForm({ form, subject, onCancel, onSaved }: { form: FormState; subject: Pick<Subject, 'context' | 'revision' | 'generation'>; onCancel: () => void; onSaved: () => Promise<void> }) {
  const options = OPTIONS[form.kind],
    [decision, setDecision] = useState(form.decision || options[0].value),
    [reviewer, setReviewer] = useState(rememberedReviewer),
    [approver, setApprover] = useState(''),
    [justification, setJustification] = useState(''),
    [controls, setControls] = useState(''),
    [expires, setExpires] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const needsControls = form.kind === 'activity' && decision === 'Conditional' || form.kind === 'acceptance' && decision === 'Accepted'
  const formal = form.kind === 'acceptance' && decision !== 'Pending'
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const date = expires ? parseNorwegianDate(expires) : null
      if (expires && !date) throw Error('Use DD.MM.YYYY for the expiration date.')
      await sodPost(`/api/sod/decisions/${form.kind}`, { context: subject.context, expected_revision: subject.revision, expected_generation: subject.generation, items: form.items, decision, reviewer, approver, justification, controls, expires: date })
      try { sessionStorage.setItem(reviewerKey, reviewer) } catch { /* optional convenience */ }
      await onSaved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The decision could not be saved.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="sod-section" aria-label={form.heading}>
      <h3>{form.heading}</h3>
      <p className="ui-description">Names are self-reported, not verified identities or signatures. Every save adds an immutable history event with the evidence it was based on. This does not change SAP or the detected conflict.</p>
      <FormField label={`${KIND_LABEL[form.kind]} decision`}>
        <Select value={decision} onChange={(event) => setDecision(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</Select>
      </FormField>
      <FormField label="Reviewer (self-reported)"><Input value={reviewer} maxLength={120} onChange={(event) => setReviewer(event.target.value)} /></FormField>
      {formal && <FormField label="Approver (must differ from reviewer)"><Input value={approver} maxLength={120} onChange={(event) => setApprover(event.target.value)} /></FormField>}
      <FormField label="Justification"><textarea className="ui-control min-h-20" value={justification} maxLength={4000} onChange={(event) => setJustification(event.target.value)} /></FormField>
      {(needsControls || form.kind === 'acceptance' && formal) && <FormField label={form.kind === 'activity' ? 'Conditions' : 'Compensating controls (optional)'}><textarea className="ui-control min-h-16" value={controls} maxLength={8000} onChange={(event) => setControls(event.target.value)} /></FormField>}
      {form.kind === 'acceptance' && decision === 'Accepted' && <NorwegianDateInput label="Acceptance expires (optional)" value={expires} onChange={setExpires} />}
      {error && <p role="alert">{error}</p>}
      <Toolbar>
        <Button loading={busy} disabled={!reviewer.trim() || !justification.trim() || formal && !approver.trim() || form.kind === 'activity' && decision === 'Conditional' && !controls.trim()} onClick={() => void save()}>Save decision</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </Toolbar>
    </section>
  )
}
