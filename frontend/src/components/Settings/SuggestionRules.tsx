import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eraser, Pencil, Plus, Trash2, Users } from 'lucide-react'
import { addRule, createGroup, deleteRule, fetchRuleMatches, fetchRuleSelection, fetchRules, rulesKey, updateRule, type FunctionalGroup, type Rule } from '@/api/functionalGroups'
import { BulkAssignDialog } from '@/components/Access/BulkAssignDialog'
import { Pagination } from '@/components/Access/Shared'
import { Button, IconButton } from '@/components/Shared/Button'
import { Checkbox, FormField, SearchInput, controlClass } from '@/components/Shared/Controls'
import { Dialog } from '@/components/Shared/Dialog'
import { DataTable, EmptyState, EvidenceDisclosure, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
import { GroupCount } from './GroupCount'
import { SAPUserLink } from '@/components/Shared/SAPUserLink'

const message = (error: unknown) => (error instanceof Error ? error.message : 'The request failed.')
const PAGE = 25

/** New or edited rule. Department matching is "contains"; a rule created before multiple memberships keeps its exact (equals) meaning until converted here. */
function RuleDialog({ rule, groups, onClose }: { rule: Rule | null; groups: FunctionalGroup[]; onClose: () => void }) {
  const client = useQueryClient()
  const [groupId, setGroupId] = useState(rule?.group_id ?? ''), [department, setDepartment] = useState(rule?.department ?? ''), [title, setTitle] = useState(rule?.title_contains ?? '')
  const [mode, setMode] = useState<'contains' | 'equals'>(rule?.department_mode ?? 'contains')
  // A group created here is selected at once and stays in the list while the catalogue refetches.
  const [created, setCreated] = useState<FunctionalGroup[]>([]), [adding, setAdding] = useState(false), [newName, setNewName] = useState('')
  const active = [...groups.filter(group => group.status === 'active' || group.id === rule?.group_id), ...created.filter(group => !groups.some(known => known.id === group.id))]
  const create = useMutation({
    mutationFn: () => createGroup(newName, ''),
    onSuccess: async group => { setCreated(previous => [...previous, group]); setGroupId(group.id); setAdding(false); setNewName(''); await client.invalidateQueries({ queryKey: ['functional-groups'] }) },
  })
  const duplicate = Boolean(newName.trim()) && groups.some(group => group.name.trim().toLowerCase() === newName.trim().toLowerCase())
  const save = useMutation({
    mutationFn: () => { const body = { group_id: groupId, department, title_contains: title, department_mode: mode }; return rule ? updateRule(rule.id, body) : addRule(body) },
    onSuccess: async () => { await client.invalidateQueries({ queryKey: rulesKey }); onClose() },
  })
  const valid = Boolean(groupId && (department.trim() || title.trim()))
  return (
    <Dialog title={rule ? 'Edit suggestion rule' : 'New suggestion rule'} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>{rule ? 'Save rule' : 'Create rule'}</Button></>}>
      <form className="grid gap-3" onSubmit={event => { event.preventDefault(); if (valid) save.mutate() }}>
        <p className="ui-description">Advisory only; groups are never assigned automatically. Both conditions must match when both are given; at least one is required. Matching ignores case.</p>
        <FormField label="Directory Department contains"><input className={controlClass} value={department} maxLength={200} onChange={event => setDepartment(event.target.value)} autoFocus /></FormField>
        {rule?.department_mode === 'equals' && (
          <FormField label="Department matching" description="This rule was created with exact matching. Converting it to contains can match more users; check View matches first.">
            <Select value={mode} onChange={event => setMode(event.target.value as 'contains' | 'equals')}><option value="equals">Equals the whole value (existing rule)</option><option value="contains">Contains the text</option></Select></FormField>)}
        <FormField label="Job Title contains"><input className={controlClass} value={title} maxLength={200} onChange={event => setTitle(event.target.value)} /></FormField>
        <FormField label="Suggested Functional Group"><Select value={groupId} onChange={event => setGroupId(event.target.value)}><option value="">Select a group…</option>{active.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</Select></FormField>
        {adding ? (
          <div className="grid gap-2" role="group" aria-label="Create a Functional Group">
            <FormField label="New Functional Group name" description="Created as an active group without members. The rule fields above are kept.">
              <input className={controlClass} value={newName} maxLength={80} onChange={event => { setNewName(event.target.value); create.reset() }}
                onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); if (newName.trim() && !duplicate && !create.isPending) create.mutate() } }} autoFocus /></FormField>
            {duplicate && <p role="alert">A Functional Group with this name already exists. Select it in the list above.</p>}
            {create.isError && <p role="alert">{message(create.error)}</p>}
            <div className="flex flex-wrap gap-2"><Button variant="primary" disabled={!newName.trim() || duplicate || create.isPending} onClick={() => create.mutate()}>Create group</Button><Button onClick={() => { setAdding(false); create.reset() }}>Cancel</Button></div>
          </div>
        ) : <div><Button onClick={() => setAdding(true)}><Plus size={14} aria-hidden="true" />New group</Button></div>}
        {save.isError && <p role="alert">{message(save.error)}</p>}
      </form>
    </Dialog>
  )
}

/** Users a rule applies to, from imported Directory data and SAP identities that map to exactly one Directory employee. Select some and add the suggested group. */
function MatchesDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const client = useQueryClient()
  const [search, setSearch] = useState(''), [onlyNew, setOnlyNew] = useState(false), [offset, setOffset] = useState(0), [picked, setPicked] = useState<Set<string>>(new Set())
  const [assigning, setAssigning] = useState(false), [busy, setBusy] = useState(false), [note, setNote] = useState('')
  const query = useQuery({ queryKey: ['functional-group-rule-matches', rule.id, search, onlyNew, offset], queryFn: () => fetchRuleMatches(rule.id, { search, only_new: onlyNew, offset, limit: PAGE }), placeholderData: previous => previous })
  const data = query.data, items = data?.items ?? []
  const selectable = items.filter(item => !item.already_member)
  const allOnPage = selectable.length > 0 && selectable.every(item => picked.has(item.username))
  const selectAll = async () => {
    setBusy(true); setNote('')
    try {
      const all = await fetchRuleSelection(rule.id, { search, only_new: true })
      setPicked(new Set(all.usernames)); setNote(all.truncated ? `Only the first ${all.limit.toLocaleString()} of ${all.total.toLocaleString()} users were selected.` : `${all.total.toLocaleString()} users selected (those not yet in the group).`)
    } catch (error) { setNote(message(error)) } finally { setBusy(false) }
  }
  const change = (fn: () => void) => { fn(); setOffset(0) }
  if (assigning) return <BulkAssignDialog usernames={[...picked].sort()} lockedGroupIds={[rule.group_id]} onClose={() => { setAssigning(false); setPicked(new Set()) }}
    onChanged={() => void Promise.all([['functional-group-rule-matches'], ['functional-group-rules'], ['functional-groups'], ['functional-group-members']].map(queryKey => client.invalidateQueries({ queryKey })))} />
  return (
    <Dialog title={`Users matching · ${rule.group_name}`} onClose={onClose} footer={null}>
      <div className="grid min-w-0 gap-3">
        <p className="ui-description">{rule.department ? `Directory Department ${rule.department_mode === 'equals' ? 'equals' : 'contains'} “${rule.department}”` : ''}{rule.department && rule.title_contains ? ' and ' : ''}{rule.title_contains ? `Job Title contains “${rule.title_contains}”` : ''}. Only SAP users linked to exactly one Directory employee can be assigned.</p>
        <div className="ui-toolbar">
          <SearchInput aria-label="Search matching users" placeholder="Search users" value={search} onChange={event => change(() => setSearch(event.target.value))} onClear={() => change(() => setSearch(''))} />
          <Checkbox checked={onlyNew} onChange={event => change(() => setOnlyNew(event.target.checked))}>Hide users already in the group</Checkbox>
          <Button disabled={busy || !data?.total} onClick={() => void selectAll()}>Select all not yet in the group</Button>
          {picked.size > 0 && <><Button variant="outline" onClick={() => { setPicked(new Set()); setNote('') }}><Eraser size={16} aria-hidden="true" />Clear selection</Button>
            <Button variant="primary" onClick={() => setAssigning(true)}><Plus size={16} aria-hidden="true" />Add {rule.group_name} to {picked.size.toLocaleString()} selected</Button></>}
        </div>
        {note && <p role="status" className="ui-description">{note}</p>}
        {query.isError ? <p role="alert">{message(query.error)}</p> : !data ? <LoadingState /> : (
          <>
            <p role="status">{data.total.toLocaleString()} matching SAP-linked {data.total === 1 ? 'user' : 'users'}{picked.size > 0 ? ` · ${picked.size.toLocaleString()} selected` : ''}</p>
            {items.length ? (
              <DataTable caption="Users matching the rule" density="compact">
                <thead><tr><th className="col-select"><Checkbox aria-label="Select all selectable users on this page" checked={allOnPage} disabled={!selectable.length} onChange={() => setPicked(previous => { const next = new Set(previous); for (const item of selectable) { if (allOnPage) next.delete(item.username); else next.add(item.username) } return next })}><span className="sr-only">Select</span></Checkbox></th>
                  <th>SAP user</th><th>Full name</th><th>Directory Department</th><th>Job title</th><th>Current groups</th><th>Suggested group</th></tr></thead>
                <tbody>{items.map(item => (
                  <tr key={item.username}>
                    <td className="col-select"><Checkbox aria-label={`Select ${item.username}`} checked={picked.has(item.username)} disabled={item.already_member} onChange={() => setPicked(previous => { const next = new Set(previous); if (next.has(item.username)) next.delete(item.username); else next.add(item.username); return next })}><span className="sr-only">Select</span></Checkbox></td>
                    <td><SAPUserLink username={item.username} copyLabel="username" /></td><td>{item.full_name || '—'}</td><td>{item.department || '—'}</td><td>{item.title || '—'}</td>
                    <td>{item.groups.map(group => group.name).join('; ') || 'Unassigned'}</td>
                    <td>{item.already_member ? <StatusBadge tone="success">Already a member</StatusBadge> : <StatusBadge>Not yet</StatusBadge>}</td></tr>))}</tbody>
              </DataTable>
            ) : <EmptyState>{search || onlyNew ? 'No matching user for this filter.' : 'No SAP-linked user matches this rule.'}</EmptyState>}
            <Pagination offset={offset} total={data.total} limit={PAGE} onChange={setOffset} label="Matching user pages" />
            {data.not_linked_total > 0 && (
              <EvidenceDisclosure title={`${data.not_linked_total.toLocaleString()} Directory ${data.not_linked_total === 1 ? 'identity matches' : 'identities match'} but cannot be assigned`}>
                <p className="ui-description">These Directory employees have no unique SAP user (unmatched, ambiguous or duplicate e-mail). Nothing is assigned to them and no SAP user is created.</p>
                <ul>{data.not_linked.map((row, index) => <li key={index}>{row.full_name || 'Unnamed'} · {row.department || '—'} · {row.title || '—'}</li>)}</ul>
              </EvidenceDisclosure>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}

export function SuggestionRules({ groups }: { groups: FunctionalGroup[] }) {
  const client = useQueryClient(), rules = useQuery({ queryKey: [...rulesKey, 'counts'], queryFn: () => fetchRules(true) })
  const [editing, setEditing] = useState<Rule | 'new' | null>(null), [matching, setMatching] = useState<Rule | null>(null), [deleting, setDeleting] = useState<Rule | null>(null)
  const remove = useMutation({ mutationFn: (rule: Rule) => deleteRule(rule.id), onSuccess: async () => { setDeleting(null); await client.invalidateQueries({ queryKey: rulesKey }) } })
  return (
    <section className="grid min-w-0 gap-3" aria-label="Suggestion rules">
      <div className="ui-toolbar"><h3>Suggestion rules</h3><Button variant="primary" onClick={() => setEditing('new')}><Plus size={14} aria-hidden="true" />New rule</Button></div>
      <p className="ui-description">Advisory only. A rule matches when Directory Department contains the text and Job Title contains the text (case-insensitive); both are optional but one is required. A user can match several rules and belong to several groups. Groups are never assigned automatically.</p>
      {remove.isError && <p role="alert">{message(remove.error)}</p>}
      {rules.isError ? <p role="alert">{message(rules.error)}</p> : !rules.data ? <LoadingState /> : rules.data.items.length ? (
        <DataTable caption="Functional Group suggestion rules" density="compact">
          <thead><tr><th>Directory Department contains</th><th>Job Title contains</th><th>Suggested Functional Group</th><th>Matching users</th><th className="col-actions">Actions</th></tr></thead>
          <tbody>{rules.data.items.map(rule => (
            <tr key={rule.id}>
              <td>{rule.department || 'Any'}{rule.department && rule.department_mode === 'equals' && <> <StatusBadge>Exact match (existing rule)</StatusBadge></>}</td>
              <td>{rule.title_contains || 'Any'}</td>
              <td>{rule.group_name}{rule.group_status === 'archived' && <> <StatusBadge>Archived</StatusBadge></>}</td>
              <td><GroupCount count={rule.match_count} label={`View ${rule.match_count} users matching the rule for ${rule.group_name}`} onOpen={() => setMatching(rule)} /></td>
              <td className="col-actions"><span className="inline-flex items-center gap-1">
                <IconButton label={`View matches for the rule suggesting ${rule.group_name}`} tooltip="View matching users" size="icon" onClick={() => setMatching(rule)}><Users size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Edit rule suggesting ${rule.group_name}`} tooltip="Edit rule" size="icon" onClick={() => setEditing(rule)}><Pencil size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Delete rule suggesting ${rule.group_name}`} tooltip="Delete rule" size="icon" onClick={() => setDeleting(rule)}><Trash2 size={14} aria-hidden="true" /></IconButton></span></td></tr>))}</tbody>
        </DataTable>
      ) : <EmptyState>No suggestion rules. Use New rule to add one.</EmptyState>}
      {editing && <RuleDialog rule={editing === 'new' ? null : editing} groups={groups} onClose={() => setEditing(null)} />}
      {matching && <MatchesDialog rule={matching} onClose={() => setMatching(null)} />}
      {deleting && (
        <Dialog title="Delete suggestion rule" onClose={() => setDeleting(null)}
          footer={<><Button onClick={() => setDeleting(null)}>Cancel</Button><Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(deleting)}>Delete rule</Button></>}>
          <p>Delete the rule that suggests <strong>{deleting.group_name}</strong>? Existing memberships are not affected.</p>
        </Dialog>
      )}
    </section>
  )
}
