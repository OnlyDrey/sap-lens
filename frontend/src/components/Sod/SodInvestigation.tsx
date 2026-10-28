import { useState } from 'react'
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

export function SodInvestigation({ context, user, risk, activity, onClose }: { context: string; user: string; risk?: string; activity?: string; onClose: () => void }) {
  const qc = useQueryClient(),
    { change } = useViewHistory(),
    [form, setForm] = useState<FormState | null>(null),
    [selection, setSelection] = useState<string[]>([]),
    [simulation, setSimulation] = useState<null | { before: string[]; after: string[]; resolved: string[]; lost_activities: string[]; warnings: string[]; eliminates_all: boolean }>(null),
    [error, setError] = useState(''),
    [action, setAction] = useState<null | { assignment: AssignmentRow }>(null)
  const params = scopeParams(context, emptyFilters, { user, ...(risk ? { risk } : {}), ...(activity ? { activity } : {}) })
  const query = useQuery({ queryKey: ['sod-subject', params.toString()], queryFn: () => sod<Subject>('/api/sod/subject', params) })
  const data = query.data
  const ok = !!data?.reviewable
  const simulate = async (removed: string[]) => {
    setError('')
    try { setSimulation(await sodPost('/api/sod/simulate', { context, user, removed })) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Simulation failed.') }
  }
  const toggle = (id: string) => { setSimulation(null); setSelection((previous) => (previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id])) }
  const item = (key: string, ref: string, version: string): Item => ({ key, user, ref, evidence_version: version })
  const activities = data?.activities || []
  return (
    <SidePanel title={`${user}${risk ? ` · ${risk}` : activity ? ` · ${activity}` : ''}`} subtitle={data ? <>Potential conflict evidence, not effective authorization · evaluation {formatDate(data.as_of)}</> : undefined} onClose={onClose}>
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : !data ? <LoadingState /> : <>
        <section className="sod-section" aria-label="Subject summary">
          <Toolbar>
            <RoleIdentifier value={user} label="SAP username" onOpen={() => change({ page: 'users', accessMode: 'directory', user, userContext: {}, detailRole: null, settings: false })} openLabel={`Open SAP user ${user}`} />
            {data.groups.map((group) => <StatusBadge key={group}>{group}</StatusBadge>)}
            {data.frozen && <StatusBadge tone="info">Frozen snapshot, read only</StatusBadge>}
            {!data.frozen && !data.reviewable && <StatusBadge>Read only</StatusBadge>}
          </Toolbar>
          {data.account && <p className="ui-description">Directory match: {data.account.directory_match.replace(/_/g, ' ')} · AD {data.account.ad_status}{data.account.lock_status ? ` · SAP ${data.account.lock_status}` : ''}</p>}
        </section>

        {data.risk && <section className="sod-section" aria-label="Risk">
          <h3>Risk</h3>
          <Toolbar>
            <RoleIdentifier value={data.risk.risk_id} label="SoD risk" />
            <StatusBadge tone="warning">Potential conflict detected</StatusBadge>
            <StatusBadge>{data.risk.criticality}</StatusBadge>
            <span className="text-xs text-muted">Risk acceptance</span><LifecycleBadge value={data.risk.acceptance} />
          </Toolbar>
          <p>{data.risk.display_name || data.risk.source_text}</p>
          <p className="ui-description">{Object.entries(data.risk.sides).map(([side, names]) => `${side === 'ACTVT1' ? 'Activity 1' : 'Activity 2'}: ${names.join(', ')}`).join(' · ')}{data.risk.category ? ` · ${data.risk.category}` : ''}</p>
          {data.risk.event && <p className="ui-description">{data.risk.event.decision} by {data.risk.event.reviewer}, approver {data.risk.event.approver}, {formatTimestamp(data.risk.event.timestamp)}{data.risk.event.expires ? ` · expires ${formatDate(data.risk.event.expires)}` : ''}: {data.risk.event.justification}</p>}
          {!!data.risk.legacy_decisions.length && <AlertNote>{data.risk.legacy_decisions.length} legacy risk decision(s) recorded before activity-level review are retained as history and were not converted to a risk acceptance.</AlertNote>}
          <Toolbar>
            {ok && <Button onClick={() => setForm({ kind: 'acceptance', heading: `Risk acceptance · ${data.risk!.risk_id}`, items: [item(data.risk!.finding_id, data.risk!.risk_id, data.risk!.evidence_version)] })}><ClipboardCheck size={16} aria-hidden="true" />Decide risk acceptance</Button>}
          </Toolbar>
          <DecisionHistory kind="acceptance" context={context} keyId={data.risk.finding_id} label="Risk acceptance history" />
        </section>}

        {activities.length === 0 && <EmptyState>No conflict-relevant activity evidence for this selection.</EmptyState>}
        {activities.map((row) => (
          <ActivityBlock key={row.key} row={row} ok={ok} context={context} selection={selection} toggle={toggle}
            impact={data.impact?.per_assignment || {}}
            onActivity={() => setForm({ kind: 'activity', heading: `Activity review · ${row.activity}`, items: [item(row.key, row.activity, row.evidence_version)] })}
            onAssignment={(assignment, decision) => setForm({ kind: 'assignment', heading: `Role assignment · ${assignment.role}`, decision, items: [item(assignment.id, assignment.role, assignment.evidence_version)] })}
            onTrack={(assignment) => setAction({ assignment })}
            onRole={(name) => change({ detailRole: name })} />
        ))}

        {form && <DecisionForm key={form.heading} form={form} subject={data} onCancel={() => setForm(null)} onSaved={async () => { setForm(null); await invalidateSod(qc) }} />}

        {data.impact && <section className="sod-section" aria-label="Remediation impact">
          <h3><Wrench size={14} className="mr-1 inline" aria-hidden="true" />Remediation impact</h3>
          <p className="ui-description">Several remediation options can be valid. This is a what-if over a copy of the evidence; it never changes SAP or imported data, and a removal recommendation is not confirmed removal.</p>
          {data.impact.options.map((option) => (
            <Card key={option.slot}>
              <p><strong>{option.slot === 'ACTVT1' ? 'Activity 1' : 'Activity 2'} ({option.activities.join(', ')})</strong>: remove all {option.assignments.length} supplying assignment(s) ({option.roles.join(', ')}) to {option.resolves_risk ? 'resolve this risk' : 'reduce evidence'}{option.also_resolves.length ? `; also resolves ${option.also_resolves.join(', ')}` : ''}.</p>
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

        {data.related_risks.length > 0 && <section className="sod-section" aria-label="Related risks"><h3>Related risks for this user</h3><p>{data.related_risks.join(', ')}</p></section>}
      </>}
      {action && data && <ActionDialog context={context} revision={data.revision} user={user} assignment={action.assignment} risk={risk} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await invalidateSod(qc) }} />}
    </SidePanel>
  )
}

function ActivityBlock({ row, ok, context, selection, toggle, impact, onActivity, onAssignment, onTrack, onRole }: {
  row: ActivityDetail; ok: boolean; context: string; selection: string[]; toggle: (id: string) => void
  impact: Record<string, { resolves: string[]; remaining: string[]; lost_activities: string[]; affected_approved_activities: string[] }>
  onActivity: () => void; onAssignment: (assignment: AssignmentRow, decision: string) => void; onTrack: (assignment: AssignmentRow) => void; onRole: (role: string) => void
}) {
  return (
    <section className="sod-section" aria-label={`Activity ${row.activity}`}>
      <Toolbar>
        <h3>Activity {row.activity}</h3>
        <LifecycleBadge value={row.decision} />
        {row.duplicate_coverage && <StatusBadge tone="info">Supplied by {row.assignments.length} assignments</StatusBadge>}
        {ok && <Button onClick={onActivity}><ClipboardCheck size={16} aria-hidden="true" />Review activity</Button>}
      </Toolbar>
      <p className="ui-description">Transactions: {row.tcodes.join(', ')} · Risks: {row.risks.join(', ')}</p>
      {row.event && <p className="ui-description">{row.event.decision} by {row.event.reviewer}, {formatTimestamp(row.event.timestamp)}: {row.event.justification}{row.event.controls ? ` Conditions: ${row.event.controls}` : ''}</p>}
      <DecisionHistory kind="activity" context={context} keyId={row.key} label="Activity review history" />
      <ul className="grid gap-2" aria-label={`Role assignments supplying ${row.activity}`}>
        {row.assignments.map((assignment) => {
          const effect = impact[assignment.id]
          return (
            <li key={assignment.id} className="grid min-w-0 gap-2 rounded-card border border-line p-3">
              <Toolbar>
                <Checkbox checked={selection.includes(assignment.id)} onChange={() => toggle(assignment.id)} aria-label={`Include ${assignment.role} in what-if removal`}>Simulate</Checkbox>
                <RoleIdentifier value={assignment.role} onOpen={() => onRole(assignment.catalogue_roles[0] || assignment.role)} openLabel={`Open catalogue role ${assignment.catalogue_roles[0] || assignment.role}`} />
                <LifecycleBadge value={assignment.decision} />
              </Toolbar>
              <p className="text-xs text-muted">{assignment.user_group || 'No user group'} · {assignment.interval_status && <AssignmentStatus value={assignment.interval_status} />} {formatDate(assignment.valid_from)} → {formatDate(assignment.valid_to)}</p>
              <p className="text-xs">Also supplies: {assignment.other_activities.join(', ') || 'no other relevant activity'} · contributes to {assignment.risks.join(', ')}</p>
              {assignment.event && <p className="text-xs text-muted">{assignment.event.decision} by {assignment.event.reviewer}, {formatTimestamp(assignment.event.timestamp)}: {assignment.event.justification}</p>}
              {effect && <p className="text-xs">Removing this alone: {effect.resolves.length ? `resolves ${effect.resolves.join(', ')}` : 'resolves no risk'}; {effect.remaining.length ? `still detected: ${effect.remaining.join(', ')}` : 'no detected risks remain'}.{effect.affected_approved_activities.length > 0 && <strong className="text-error"> Ends approved access to {effect.affected_approved_activities.join(', ')}.</strong>}</p>}
              {ok && <Toolbar>
                <Button onClick={() => onAssignment(assignment, 'Keep')}>Keep</Button>
                <Button onClick={() => onAssignment(assignment, 'Remove')}>Remove</Button>
                {assignment.decision === 'Removal required' && <Button onClick={() => onTrack(assignment)}>Track action</Button>}
              </Toolbar>}
              <DecisionHistory kind="assignment" context={context} keyId={assignment.id} label="Assignment review history" />
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
