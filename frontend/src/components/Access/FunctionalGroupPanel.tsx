import {useReviewerName} from '@/hooks/useReviewerIdentity'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Settings2, Trash2, UsersRound } from 'lucide-react'
import { addMembership, fetchUserClassification, removeMembership, type Classification, type Membership, type SuggestedGroup, type UserClassification, type ClassificationStatus } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { EvidenceDisclosure, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { confirmationText } from '@/lib/functionalGroupText'
import { GroupPicker } from './GroupPicker'

export const classificationKey = (username: string) => ['functional-group-user', username] as const
const tone: Record<ClassificationStatus, 'success' | 'warning' | 'neutral'> = { Confirmed: 'success', 'Needs review': 'warning', Unassigned: 'neutral' }
export const ClassificationPill = ({ status }: { status: ClassificationStatus }) => <StatusBadge tone={tone[status]}>{status}</StatusBadge>

function lastReviewer() { try { return localStorage.getItem('sap-lens-reviewer') ?? '' } catch { return '' } }
function rememberReviewer(name: string) { try { localStorage.setItem('sap-lens-reviewer', name) } catch { /* optional convenience */ } }
const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

/** After any membership change the user's own views, the directory, filters, counts and Account Review are refreshed. */
export function useRefreshClassification(username: string) {
  const client = useQueryClient()
  return async () => {
    await Promise.all([classificationKey(username), ['functional-groups'], ['functional-group-options'], ['functional-group-members'], ['access-users'], ['access-user'], ['account-review']]
      .map(queryKey => client.invalidateQueries({ queryKey })))
  }
}

/** Suggestions are advisory: one entry per group with every explaining rule, and a group the user already belongs to is labelled as such. */
function Suggestions({ items, onAdd, pending }: { items: SuggestedGroup[]; onAdd: (groupId: string) => void; pending: boolean }) {
  if (!items.length) return null
  return (
    <div className="grid gap-1" role="group" aria-label="Suggested groups">
      <p className="ui-description">Suggested from imported Directory data (advisory; nothing is assigned until you add it):</p>
      <ul className="fg-suggestions">{items.map(item => (
        <li key={item.group_id}>
          <div className="fg-suggestion-head"><strong>{item.group_name}</strong>
            {item.already_member ? <StatusBadge tone="success">Already a member</StatusBadge> : <Button size="compact" disabled={pending} onClick={() => onAdd(item.group_id)} aria-label={`Add suggested group ${item.group_name}`}><Plus size={14} aria-hidden="true" />Add</Button>}</div>
          <span className="fg-meta">{item.reasons.join(' · ')}</span>
        </li>))}</ul>
    </div>
  )
}

/** One membership row: group, its own status and confirmation text, and its own actions (confirm when a review is open, remove with a rationale). */
function MembershipRow({ item, busy, onConfirm, onRemove }: { item: Membership; busy: boolean; onConfirm?: () => void; onRemove: () => void }) {
  const text = confirmationText(item.confirmed_at, item.confirmed_by, item.status === 'Confirmed')
  return (
    <li className="fg-membership" data-status={item.status}>
      <div className="fg-membership-main">
        <strong className="fg-name">{item.group.name}{item.group.status === 'archived' && ' (archived)'}</strong>
        <ClassificationPill status={item.status} />
        {text && <span className="fg-meta">{text}</span>}
        {item.review && <span className="fg-meta">Review required: {item.review.reason}</span>}
      </div>
      <div className="fg-membership-actions">
        {onConfirm && item.status === 'Needs review' && <Button size="compact" disabled={busy} onClick={onConfirm} aria-label={`Confirm ${item.group.name}`}>Confirm</Button>}
        <Button size="compact" variant="outline" disabled={busy} onClick={onRemove} aria-label={`Remove ${item.group.name}`}><Trash2 size={14} aria-hidden="true" />Remove</Button>
      </div>
    </li>
  )
}

/** Reviewer and rationale shared by the actions of one dialog. The reviewer is self-reported unless the server authenticates one. */
function useReviewer() {
  const [reviewer, setReviewer] = useReviewerName(lastReviewer), [rationale, setRationale] = useState('')
  return { reviewer, setReviewer, rationale, setRationale }
}

/** Manage the Functional Groups of one user: add groups (several at once, new ones created inline), confirm or remove memberships individually. A business
 *  classification only: SAP access is never changed. Adding keeps every existing membership. */
export function ManageGroupsDialog({ username, data, changeId = '', onClose }: { username: string; data: UserClassification; changeId?: string; onClose: () => void }) {
  const refresh = useRefreshClassification(username)
  const { reviewer, setReviewer, rationale, setRationale } = useReviewer()
  const [picked, setPicked] = useState<string[]>([]), [removing, setRemoving] = useState<Membership | null>(null), [removeRationale, setRemoveRationale] = useState('')
  const current: Classification = data.classification
  const held = current.group_ids
  const run = useMutation({
    mutationFn: async (job: { add?: string[]; confirm?: string; remove?: { group: string; reason: string } }) => {
      let revision = current.revision, result: Classification = current
      for (const group of job.add ?? []) { const done = await addMembership({ username, group_id: group, rationale, reviewer: reviewer.trim(), expected_revision: revision, change_id: changeId || undefined }); result = done.classification; revision = result.revision }
      if (job.confirm) result = (await addMembership({ username, group_id: job.confirm, rationale, reviewer: reviewer.trim(), expected_revision: revision, change_id: changeId || undefined })).classification
      if (job.remove) result = (await removeMembership({ username, group_id: job.remove.group, rationale: job.remove.reason, reviewer: reviewer.trim(), expected_revision: revision, change_id: changeId || undefined })).classification
      return result
    },
    onSuccess: async (_result, job) => { rememberReviewer(reviewer.trim()); await refresh(); setPicked([]); setRemoving(null); setRemoveRationale(''); setRationale(''); if (job.add) onClose() },
  })
  const needReviewer = !reviewer.trim()
  const toAdd = picked.filter(id => !held.includes(id))
  return (
    <Dialog title={`Functional Groups for ${username}`} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={needReviewer || !toAdd.length || run.isPending} onClick={() => run.mutate({ add: toAdd })}>
        <Plus size={16} aria-hidden="true" />{toAdd.length ? `Add ${toAdd.length} ${toAdd.length === 1 ? 'group' : 'groups'}` : 'Add groups'}</Button></>}>
      <div className="grid min-w-0 gap-3">
        <p className="ui-description">Business classification maintained in SAP Lens. Adding a group keeps the user's other groups and never changes SAP access.</p>
        {current.memberships.length > 0 ? (
          <ul className="fg-memberships" aria-label="Current Functional Groups">{current.memberships.map(item => (
            <MembershipRow key={item.group_id} item={item} busy={run.isPending || needReviewer} onConfirm={() => run.mutate({ confirm: item.group_id })} onRemove={() => { setRemoving(item); setRemoveRationale('') }} />))}</ul>
        ) : <p className="ui-description">Not a member of any Functional Group.</p>}
        {removing && (
          <div role="group" aria-label={`Remove ${removing.group.name}`} className="fg-remove">
            <p>Remove <strong>{removing.group.name}</strong>? The user's other groups are kept and the removal is recorded in the history.</p>
            <FormField label="Rationale (required)"><textarea className={controlClass} rows={2} maxLength={2000} value={removeRationale} onChange={event => setRemoveRationale(event.target.value)} /></FormField>
            <div className="ui-toolbar"><Button onClick={() => setRemoving(null)}>Keep group</Button>
              <Button variant="destructive" disabled={needReviewer || !removeRationale.trim() || run.isPending} onClick={() => run.mutate({ remove: { group: removing.group_id, reason: removeRationale } })}>Remove group</Button></div>
          </div>
        )}
        <Suggestions items={data.suggestion?.groups ?? []} pending={run.isPending || needReviewer} onAdd={group => setPicked(previous => (previous.includes(group) ? previous : [...previous, group]))} />
        <GroupPicker selected={picked} onChange={setPicked} disabledIds={held} />
        <FormField label="Reviewer"><input className={controlClass} readOnly value={reviewer} maxLength={120} onChange={event => setReviewer(event.target.value)} /></FormField>
        <FormField label="Rationale (optional when adding)"><textarea className={controlClass} rows={2} maxLength={2000} value={rationale} onChange={event => setRationale(event.target.value)} /></FormField>
        {run.isError && <p role="alert">{message(run.error, 'The change could not be saved.')}</p>}
      </div>
    </Dialog>
  )
}

/** User Details: SAP Lens-maintained classification, separate from the imported Directory fields. A business classification only: SAP access is never changed. */
export function FunctionalGroupPanel({ username }: { username: string }) {
  const query = useQuery({ queryKey: classificationKey(username), queryFn: () => fetchUserClassification(username) })
  const [editing, setEditing] = useState(false)
  const data = query.data, current = data?.classification
  const count = current?.memberships.length ?? 0
  return (
    <section aria-label="Functional Group" className="profile-functional-group">
      <div className="profile-group-header">
        <h2><UsersRound size={18} aria-hidden="true" />Functional Groups</h2>
        {current && (
          <span className="inline-flex flex-wrap gap-2">
            <Button variant={count ? 'secondary' : 'primary'} onClick={() => setEditing(true)} aria-label={count ? 'Add group' : 'Assign group'}>{count ? <Plus size={16} aria-hidden="true" /> : <UsersRound size={16} aria-hidden="true" />}{count ? 'Add group' : 'Assign group'}</Button>
            {count > 0 && <Button onClick={() => setEditing(true)} aria-label="Manage groups"><Settings2 size={16} aria-hidden="true" />Manage groups</Button>}
          </span>
        )}
      </div>
      {query.isError ? <p role="alert">{message(query.error, 'Functional Group data is unavailable.')}</p> : !current ? <LoadingState /> : (
        <>
          {count ? (
            <>
              {/* Active groups first; memberships of archived groups stay visible as their own, clearly labelled list. */}
              {[['Functional Group memberships', current.memberships.filter(item => item.group.status !== 'archived'), ''] as const,
                ['Archived Functional Group memberships', current.memberships.filter(item => item.group.status === 'archived'), 'Archived groups (kept on the user, cannot be newly assigned)'] as const].map(([label, items, heading]) => items.length > 0 && (
                <div key={label} className="grid gap-1">
                  {heading && <h3 className="fg-meta">{heading}</h3>}
                  <ul className="fg-memberships" aria-label={label}>{items.map(item => (
                    <li key={item.group_id} className="fg-membership" data-status={item.status}>
                      <div className="fg-membership-main">
                        <strong className="fg-name">{item.group.name}{item.group.status === 'archived' && ' (archived)'}</strong>
                        <ClassificationPill status={item.status} />
                        {confirmationText(item.confirmed_at, item.confirmed_by, item.status === 'Confirmed') && <span className="fg-meta">{confirmationText(item.confirmed_at, item.confirmed_by, item.status === 'Confirmed')}</span>}
                        {item.review && <span className="fg-meta">Review required: {item.review.reason}</span>}
                      </div>
                    </li>))}</ul>
                </div>))}
            </>
          ) : <div className="fg-summary"><strong className="fg-name">Unassigned</strong><ClassificationPill status="Unassigned" /></div>}
          {(data?.suggestion?.groups ?? []).some(group => !group.already_member) && (
            <p className="fg-meta">Suggested (advisory): {data!.suggestion!.groups.filter(group => !group.already_member).map(group => group.group_name).join(', ')}</p>)}
          <p className="fg-meta">Business classification maintained in SAP Lens. It does not change SAP access.</p>
          <EvidenceDisclosure title="About Functional Groups"><p className="ui-description">Functional Groups are maintained in SAP Lens. A user can belong to several groups. Directory Department, Job Title and SAP User Group are imported and displayed separately.</p></EvidenceDisclosure>
          {editing && data && <ManageGroupsDialog username={username} data={data} onClose={() => setEditing(false)} />}
        </>
      )}
    </section>
  )
}

/** Account Review dialog section: classification outcome for an employee whose Department or Job Title changed. Each membership is reconfirmed or removed on its own. */
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
  const changeId = current?.memberships.find(item => item.review)?.review?.change_id ?? ''
  return (
    <section aria-label="Functional Group review" className="review-dialog-section">
      <h3>Functional Group review</h3>
      {query.isError ? <p role="alert">Functional Group data is unavailable.</p> : !current ? <LoadingState /> : (
        <>
          <ul className="fg-memberships" aria-label="Functional Group memberships under review">{current.memberships.map(item => (
            <li key={item.group_id} className="fg-membership"><div className="fg-membership-main"><strong className="fg-name">{item.group.name}</strong><ClassificationPill status={item.status} /></div></li>))}
            {!current.memberships.length && <li className="ui-description">Unassigned</li>}</ul>
          <dl className="profile-fields">
            {department && <div><dt>Directory Department</dt><dd>{department.previous || '—'} → {department.current || '—'}</dd></div>}
            {title && <div><dt>Job Title</dt><dd>{title.previous || '—'} → {title.current || '—'}</dd></div>}
            {manager && <div><dt>Manager</dt><dd>{manager.previous || '—'} → {manager.current || '—'}</dd></div>}
            {detectedAt && <div><dt>Change detected</dt><dd>{detectedAt}</dd></div>}
          </dl>
          <p className="ui-description">Classification only. This does not record a SAP role decision and never changes SAP access.</p>
          <Button onClick={() => setOpen(true)}>{current.status === 'Needs review' ? 'Review Functional Groups' : 'Manage groups'}</Button>
          {open && data && <ManageGroupsDialog username={username} data={data} changeId={changeId} onClose={() => setOpen(false)} />}
        </>
      )}
    </section>
  )
}
