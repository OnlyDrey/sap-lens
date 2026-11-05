import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Tags } from 'lucide-react'
import { fetchGroups, fetchUserClassification, groupsKey, saveClassification, type ClassificationStatus, type UserClassification } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { formatDate } from '@/lib/dateFormat'

export const classificationKey = (username: string) => ['functional-group-user', username] as const
const tone: Record<ClassificationStatus, 'success' | 'warning' | 'neutral'> = { Confirmed: 'success', 'Needs review': 'warning', Unassigned: 'neutral' }
export const ClassificationPill = ({ status }: { status: ClassificationStatus }) => <StatusBadge tone={tone[status]}>{status}</StatusBadge>

function lastReviewer() { try { return localStorage.getItem('sap-lens-reviewer') ?? '' } catch { return '' } }
function rememberReviewer(name: string) { try { localStorage.setItem('sap-lens-reviewer', name) } catch { /* optional convenience */ } }

/** Explicit classification editor: nothing is preselected and a suggestion only fills the selector until the reviewer confirms. */
export function ClassificationDialog({ username, data, changeId = '', onClose }: { username: string; data: UserClassification; changeId?: string; onClose: () => void }) {
  const client = useQueryClient(), groups = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const current = data.classification
  const [choice, setChoice] = useState(current.group?.name ?? ''), [reviewer, setReviewer] = useState(lastReviewer), [rationale, setRationale] = useState('')
  const active = (groups.data?.items ?? []).filter(group => group.status === 'active' || group.id === current.group_id)
  const selected = active.find(group => group.name === choice)
  const save = useMutation({
    mutationFn: (clear: boolean) => saveClassification(username, { group_id: clear ? null : selected?.id ?? null, rationale, reviewer: reviewer.trim(), expected_revision: current.revision, change_id: changeId || undefined }),
    onSuccess: async () => { rememberReviewer(reviewer.trim()); await client.invalidateQueries({ queryKey: classificationKey(username) }); await client.invalidateQueries({ queryKey: ['account-review'] }); onClose() },
  })
  const verb = !current.group_id ? 'Assign' : selected?.id === current.group_id ? 'Confirm' : 'Change to'
  const suggestion = data.suggestion
  const ready = reviewer.trim() && (selected ? true : false)
  return (
    <Dialog title={`Functional Group for ${username}`} onClose={onClose}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        {current.group_id && <Button variant="destructive" disabled={!reviewer.trim() || !rationale.trim() || save.isPending} onClick={() => save.mutate(true)}>Clear group</Button>}
        {!current.group_id && changeId && <Button disabled={!reviewer.trim() || !rationale.trim() || save.isPending} onClick={() => save.mutate(true)}>Keep unassigned</Button>}
        <Button variant="primary" disabled={!ready || save.isPending} onClick={() => save.mutate(false)}>{selected ? `${verb} ${selected.name}` : 'Select a group'}</Button>
      </>}>
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
      </div>
    </Dialog>
  )
}

/** User Details: SAP Lens-maintained classification, separate from the imported Directory fields. */
export function FunctionalGroupPanel({ username }: { username: string }) {
  const query = useQuery({ queryKey: classificationKey(username), queryFn: () => fetchUserClassification(username) })
  const [editing, setEditing] = useState(false)
  const data = query.data, current = data?.classification
  return (
    <section aria-label="Functional Group" className="profile-group">
      <h2><Tags size={18} aria-hidden="true" />Functional Group</h2>
      {query.isError ? <p role="alert">{query.error instanceof Error ? query.error.message : 'Functional Group data is unavailable.'}</p> : !current ? <LoadingState /> : (
        <>
          <dl className="profile-fields">
            <div><dt>Functional Group</dt><dd>{current.group?.name ?? 'Unassigned'}{current.group?.status === 'archived' && ' (archived)'}</dd></div>
            <div><dt>Classification</dt><dd><ClassificationPill status={current.status} /></dd></div>
            {current.confirmed_at && <div><dt>Last confirmed</dt><dd>{formatDate(current.confirmed_at)} by {current.confirmed_by}</dd></div>}
            {current.review && <div><dt>Review required</dt><dd>{current.review.reason}</dd></div>}
          </dl>
          <p className="ui-description">Maintained in SAP Lens. Directory Department, Job Title and SAP User Group are imported and shown separately.</p>
          {data?.suggestion?.status === 'suggested' && !current.group_id && <p className="ui-description">Suggested: {data.suggestion.matches[0].group_name} ({data.suggestion.matches[0].reasons.join(' and ')})</p>}
          <Button onClick={() => setEditing(true)}>{current.group_id ? 'Change or confirm' : 'Assign group'}</Button>
          {editing && data && <ClassificationDialog username={username} data={data} onClose={() => setEditing(false)} />}
        </>
      )}
    </section>
  )
}
