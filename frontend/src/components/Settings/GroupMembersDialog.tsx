import {useReviewerName} from '@/hooks/useReviewerIdentity'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { fetchGroupMembers, removeMembership, type FunctionalGroup, type GroupMember } from '@/api/functionalGroups'
import { BulkAssignDialog } from '@/components/Access/BulkAssignDialog'
import { ClassificationPill } from '@/components/Access/FunctionalGroupPanel'
import { Pagination } from '@/components/Access/Shared'
import { Button } from '@/components/Shared/Button'
import { Checkbox, FormField, SearchInput, controlClass } from '@/components/Shared/Controls'
import { Dialog } from '@/components/Shared/Dialog'
import { DataTable, EmptyState, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
import { SAPUserLink } from '@/components/Shared/SAPUserLink'
import { confirmationText } from '@/lib/functionalGroupText'

const PAGE = 25
const message = (error: unknown) => (error instanceof Error ? error.message : 'The request failed.')
const parseNames = (text: string) => [...new Set(text.split(/[\s,;]+/).map(item => item.trim()).filter(Boolean))]

/** Members of one Functional Group: Directory context where the SAP user is uniquely linked, per-membership status and confirmation, add and remove (also in bulk).
 *  Only classification is changed (through the same audited APIs as User Details); SAP roles and access are never touched. */
export function GroupMembersDialog({ group, onClose }: { group: FunctionalGroup; onClose: () => void }) {
  const client = useQueryClient()
  const [search, setSearch] = useState(''), [status, setStatus] = useState(''), [offset, setOffset] = useState(0), [picked, setPicked] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState(false), [names, setNames] = useState(''), [assign, setAssign] = useState<string[] | null>(null)
  const [removal, setRemoval] = useState<GroupMember[] | null>(null), [reviewer, setReviewer] = useReviewerName(), [rationale, setRationale] = useState('')
  const query = useQuery({ queryKey: ['functional-group-members', group.id, search, status, offset], queryFn: () => fetchGroupMembers(group.id, { search, status, offset, limit: PAGE }), placeholderData: previous => previous })
  const refresh = () => Promise.all([['functional-group-members'], ['functional-groups'], ['functional-group-analysis'], ['functional-group-options'], ['access-users'], ['access-user'], ['functional-group-user'], ['functional-group-rules']].map(queryKey => client.invalidateQueries({ queryKey })))
  const remove = useMutation({
    mutationFn: async (members: GroupMember[]) => {
      const failures: string[] = []
      for (const member of members) {
        try { await removeMembership({ username: member.username, group_id: group.id, rationale, reviewer: reviewer.trim(), expected_revision: member.revision }) }
        catch (error) { failures.push(`${member.username}: ${message(error)}`) }
      }
      if (failures.length) throw new Error(`${failures.length} of ${members.length} could not be removed. ${failures.slice(0, 3).join(' · ')}`)
    },
    onSettled: async () => { await refresh() },
    onSuccess: () => { setRemoval(null); setPicked(new Set()); setRationale('') },
  })
  const data = query.data
  const items = data?.items ?? []
  const allOnPage = items.length > 0 && items.every(item => picked.has(item.username))
  const toggle = (username: string) => setPicked(previous => { const next = new Set(previous); if (next.has(username)) next.delete(username); else next.add(username); return next })
  const selectedMembers = items.filter(item => picked.has(item.username))
  if (assign) return <BulkAssignDialog usernames={assign} lockedGroupIds={[group.id]} onClose={() => { setAssign(null); setAdding(false); setNames('') }} onChanged={() => void refresh()} />
  return (
    <Dialog title={`Members of ${group.name}`} onClose={onClose} footer={null}>
      <div className="grid min-w-0 gap-3">
        <p className="ui-description">{group.status === 'archived' ? 'Archived group: members are kept; new members cannot be added until it is restored. ' : ''}Classification only. Adding or removing a member never changes SAP access.</p>
        <div className="ui-toolbar">
          <SearchInput aria-label="Search members" placeholder="Search members" value={search} onChange={event => { setSearch(event.target.value); setOffset(0) }} onClear={() => { setSearch(''); setOffset(0) }} />
          <Select aria-label="Filter by membership status" value={status} onChange={event => { setStatus(event.target.value); setOffset(0) }}>
            <option value="">All statuses</option><option value="Confirmed">Confirmed</option><option value="Needs review">Needs review</option></Select>
          <Button onClick={() => setAdding(true)} disabled={group.status !== 'active'}><Plus size={16} aria-hidden="true" />Add users</Button>
          {picked.size > 0 && <Button variant="outline" onClick={() => { setRemoval(selectedMembers); setRationale('') }}><Trash2 size={16} aria-hidden="true" />Remove {picked.size} selected</Button>}
        </div>
        {adding && (
          <div role="group" aria-label="Add users to the group" className="fg-remove">
            <FormField label="SAP usernames" description="One per line, or separated by commas or semicolons. Only users in the SAP user data are added."><textarea className={controlClass} rows={3} value={names} onChange={event => setNames(event.target.value)} /></FormField>
            <div className="ui-toolbar"><Button onClick={() => { setAdding(false); setNames('') }}>Cancel</Button><Button variant="primary" disabled={!parseNames(names).length} onClick={() => setAssign(parseNames(names))}>Continue</Button></div>
          </div>
        )}
        {removal && (
          <div role="group" aria-label="Remove members" className="fg-remove">
            <p>Remove {removal.length === 1 ? <strong>{removal[0].username}</strong> : `${removal.length} members`} from <strong>{group.name}</strong>? Their other groups are kept; each removal is recorded in the history.</p>
            <FormField label="Reviewer"><input className={controlClass} readOnly value={reviewer} maxLength={120} onChange={event => setReviewer(event.target.value)} /></FormField>
            <FormField label="Rationale (required)"><textarea className={controlClass} rows={2} maxLength={2000} value={rationale} onChange={event => setRationale(event.target.value)} /></FormField>
            {remove.isError && <p role="alert">{message(remove.error)}</p>}
            <div className="ui-toolbar"><Button onClick={() => setRemoval(null)}>Keep members</Button>
              <Button variant="destructive" disabled={!reviewer.trim() || !rationale.trim() || remove.isPending} onClick={() => remove.mutate(removal)}>Remove from group</Button></div>
          </div>
        )}
        {query.isError ? <p role="alert">{message(query.error)}</p> : !data ? <LoadingState /> : items.length ? (
          <DataTable caption={`Members of ${group.name}`} density="compact">
            <thead><tr>
              <th className="col-select"><Checkbox aria-label="Select all members on this page" checked={allOnPage} onChange={() => setPicked(previous => { const next = new Set(previous); for (const item of items) { if (allOnPage) next.delete(item.username); else next.add(item.username) } return next })}><span className="sr-only">Select</span></Checkbox></th>
              <th>SAP user</th><th>Full name</th><th>Department</th><th>Job title</th><th>Status</th><th>Last confirmed</th><th className="col-actions"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{items.map(member => (
              <tr key={member.username} data-selected={picked.has(member.username) ? '' : undefined}>
                <td className="col-select"><Checkbox aria-label={`Select ${member.username}`} checked={picked.has(member.username)} onChange={() => toggle(member.username)}><span className="sr-only">Select</span></Checkbox></td>
                <td><SAPUserLink username={member.username} copyLabel="username" /></td>
                <td>{member.full_name || '—'}</td><td>{member.department || '—'}</td><td>{member.title || '—'}</td>
                <td><ClassificationPill status={member.status} />{member.identity !== 'matched' && <> <StatusBadge>{member.identity === 'not_in_import' ? 'Not in SAP import' : 'No Directory match'}</StatusBadge></>}</td>
                <td>{confirmationText(member.confirmed_at, member.confirmed_by, member.status === 'Confirmed') ?? '—'}</td>
                <td className="col-actions"><Button size="compact" variant="outline" aria-label={`Remove ${member.username} from ${group.name}`} onClick={() => { setRemoval([member]); setRationale('') }}><Trash2 size={14} aria-hidden="true" />Remove</Button></td></tr>))}</tbody>
          </DataTable>
        ) : <EmptyState>{search || status ? 'No member matches the filter.' : 'This group has no members yet.'}</EmptyState>}
        {data && <Pagination offset={offset} total={data.total} limit={PAGE} onChange={setOffset} label="Member pages" />}
      </div>
    </Dialog>
  )
}
