import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UsersRound } from 'lucide-react'
import { fetchGroups, fetchUserClassification, groupsKey, saveClassification, type ClassificationStatus, type UserClassification } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { EvidenceDisclosure, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { formatDate } from '@/lib/dateFormat'
import { actionLabel, confirmationText } from '@/lib/functionalGroupText'

export const classificationKey = (username: string) => ['functional-group-user', username] as const
const tone: Record<ClassificationStatus, 'success' | 'warning' | 'neutral'> = { Confirmed: 'success', 'Needs review': 'warning', Unassigned: 'neutral' }
export const ClassificationPill = ({ status }: { status: ClassificationStatus }) => <StatusBadge tone={tone[status]}>{status}</StatusBadge>

function lastReviewer() { try { return localStorage.getItem('sap-lens-reviewer') ?? '' } catch { return '' } }
function rememberReviewer(name: string) { try { localStorage.setItem('sap-lens-reviewer', name) } catch { /* optional convenience */ } }

/** Explicit classification form: nothing is preselected and a suggestion only fills the selector until the reviewer confirms. These are
 *  classification actions, not SAP role decisions. `changeId` ties the outcome to the organizational change under review. */
export function ClassificationForm({ username, data, changeId = '', onDone, onCancel }: { username: string; data: UserClassification; changeId?: string; onDone: () => void; onCancel?: () => void }) {
  const client = useQueryClient(), groups = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const current = data.classification
  const [choice, setChoice] = useState(current.group?.name ?? ''), [reviewer, setReviewer] = useState(lastReviewer), [rationale, setRationale] = useState('')
  const active = (groups.data?.items ?? []).filter(group => group.status === 'active' || group.id === current.group_id)
  const selected = active.find(group => group.name === choice)
  const save = useMutation({
    mutationFn: (clear: boolean) => saveClassification(username, { group_id: clear ? null : selected?.id ?? null, rationale, reviewer: reviewer.trim(), expected_revision: current.revision, change_id: changeId || undefined }),
    onSuccess: async () => { rememberReviewer(reviewer.trim()); await client.invalidateQueries({ queryKey: classificationKey(username) }); await client.invalidateQueries({ queryKey: ['account-review'] }); onDone() },
  })
  const label = !selected ? 'Select a group' : !current.group_id ? 'Assign group' : selected.id === current.group_id ? 'Confirm current group' : 'Change group'
  const suggestion = data.suggestion
  const noRationale = !rationale.trim() ? ' A rationale is required.' : ''
  return (
    <div className="grid gap-3">
      <FormField label="Functional Group">
        <Combobox label="Functional Group" value={choice} options={active.map(group => group.name)} onChange={setChoice} allowCustom={false} placeholder="Select a group" clearLabel="No group" openOnFocus={false} />
      </FormField>
      {suggestion && suggestion.status !== 'none' && (
        <div className="grid gap-1" role="group" aria-label="Suggestion">
          <p className="ui-description">{suggestion.status === 'ambiguous' ? 'Several rules match different groups; choose manually.' : 'Suggested from imported Directory data (advisory):'}</p>
          <ul>{suggestion.matches.map(match => (
            <li key={match.rule_id}>{match.group_name}: {match.reasons.join(' and ')}{' '}
              <Button onClick={() => setChoice(match.group_name)}>Use {match.group_name}</Button></li>))}</ul>
        </div>
      )}
      <FormField label="Reviewer"><input className={controlClass} value={reviewer} maxLength={120} onChange={event => setReviewer(event.target.value)} /></FormField>
      <FormField label="Rationale (required to clear)"><textarea className={controlClass} rows={3} maxLength={2000} value={rationale} onChange={event => setRationale(event.target.value)} /></FormField>
      {save.isError && <p role="alert">{save.error instanceof Error ? save.error.message : 'The classification could not be saved.'}</p>}
      <div className="ui-toolbar">
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
        {current.group_id && <Button variant="destructive" title={`Clears the Functional Group.${noRationale}`} disabled={!reviewer.trim() || !rationale.trim() || save.isPending} onClick={() => save.mutate(true)}>Clear group</Button>}
        {!current.group_id && changeId && <Button disabled={!reviewer.trim() || !rationale.trim() || save.isPending} onClick={() => save.mutate(true)}>Keep unassigned</Button>}
        <Button variant="primary" disabled={!reviewer.trim() || !selected || save.isPending} onClick={() => save.mutate(false)}>{label}</Button>
      </div>
    </div>
  )
}

export function ClassificationDialog({ username, data, changeId = '', onClose }: { username: string; data: UserClassification; changeId?: string; onClose: () => void }) {
  return <Dialog title={`Functional Group for ${username}`} onClose={onClose}><ClassificationForm username={username} data={data} changeId={changeId} onDone={onClose} onCancel={onClose} /></Dialog>
}

/** User Details: SAP Lens-maintained classification, separate from the imported Directory fields. A business classification only: SAP access is never changed. */
export function FunctionalGroupPanel({ username }: { username: string }) {
  const query = useQuery({ queryKey: classificationKey(username), queryFn: () => fetchUserClassification(username) })
  const [editing, setEditing] = useState(false)
  const data = query.data, current = data?.classification
  const confirmation = current ? confirmationText(current.confirmed_at, current.confirmed_by, current.status === 'Confirmed') : null
  return (
    <section aria-label="Functional Group" className="profile-functional-group">
      <div className="profile-group-header">
        <h2><UsersRound size={18} aria-hidden="true" />Functional Group</h2>
        {current && <Button onClick={() => setEditing(true)}><UsersRound size={16} aria-hidden="true" />{actionLabel(Boolean(current.group_id), current.status)}</Button>}
      </div>
      {query.isError ? <p role="alert">{query.error instanceof Error ? query.error.message : 'Functional Group data is unavailable.'}</p> : !current ? <LoadingState /> : (
        <>
          <div className="fg-summary">
            <strong className="fg-name" data-assigned={current.group ? '' : undefined}>{current.group?.name ?? 'Unassigned'}{current.group?.status === 'archived' && ' (archived)'}</strong>
            <ClassificationPill status={current.status} />
            {confirmation && <span className="fg-meta">{confirmation}</span>}
          </div>
          {current.review && <p className="fg-meta">Review required: {current.review.reason}</p>}
          {data?.suggestion?.status === 'suggested' && !current.group_id && <p className="fg-meta">Suggested: {data.suggestion.matches[0].group_name} ({data.suggestion.matches[0].reasons.join(' and ')})</p>}
          <p className="fg-meta">Business classification maintained in SAP Lens. It does not change SAP access.</p>
          <EvidenceDisclosure title="About Functional Groups"><p className="ui-description">Functional Groups are maintained in SAP Lens. Directory Department, Job Title and SAP User Group are imported and displayed separately.</p></EvidenceDisclosure>
          {editing && data && <ClassificationDialog username={username} data={data} onClose={() => setEditing(false)} />}
        </>
      )}
    </section>
  )
}

/** Account Review dialog section: classification outcome for an employee whose Department or Job Title changed. Separate from the SAP role decision. */
export function FunctionalGroupReview({ username, department, title, manager, detectedAt }: {
  username: string
  department?: { previous: string; current: string }
  title?: { previous: string; current: string }
  manager?: { previous: string; current: string } | null
  detectedAt?: string | null
}) {
  const query = useQuery({ queryKey: classificationKey(username), queryFn: () => fetchUserClassification(username) })
  const data = query.data, current = data?.classification
  const [open, setOpen] = useState(false)
  return (
    <section aria-label="Functional Group review" className="review-dialog-section">
      <h3>Functional Group review</h3>
      {query.isError ? <p role="alert">Functional Group data is unavailable.</p> : !current ? <LoadingState /> : (
        <>
          <dl className="profile-fields">
            <div><dt>Functional Group</dt><dd>{current.group?.name ?? 'Unassigned'} <ClassificationPill status={current.status} /></dd></div>
            {department && <div><dt>Directory Department</dt><dd>{department.previous || '—'} → {department.current || '—'}</dd></div>}
            {title && <div><dt>Job Title</dt><dd>{title.previous || '—'} → {title.current || '—'}</dd></div>}
            {manager && <div><dt>Manager</dt><dd>{manager.previous || '—'} → {manager.current || '—'}</dd></div>}
            {detectedAt && <div><dt>Change detected</dt><dd>{formatDate(detectedAt)}</dd></div>}
          </dl>
          {data?.suggestion?.status === 'suggested' && <p className="ui-description">Suggested: {data.suggestion.matches[0].group_name} ({data.suggestion.matches[0].reasons.join(' and ')})</p>}
          <p className="ui-description">Classification only. This does not record a SAP role decision and never changes SAP access.</p>
          {open ? <ClassificationForm username={username} data={data!} changeId={current.review?.change_id ?? ''} onDone={() => setOpen(false)} onCancel={() => setOpen(false)} />
            : <Button onClick={() => setOpen(true)}>{current.status === 'Needs review' ? 'Review Functional Group' : 'Change or confirm group'}</Button>}
        </>
      )}
    </section>
  )
}
