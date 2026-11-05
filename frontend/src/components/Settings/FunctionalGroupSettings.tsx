import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, BarChart3, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { FunctionalGroupAnalysis } from '@/components/Access/FunctionalGroupAnalysis'
import { addRule, createGroup, deleteRule, fetchGroups, fetchRules, groupsKey, setGroupArchived, updateGroup, type FunctionalGroup } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, SearchInput, controlClass } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { DataTable, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'

const message = (error: unknown) => (error instanceof Error ? error.message : 'The request failed.')

function GroupDialog({ group, onClose }: { group: FunctionalGroup | null; onClose: () => void }) {
  const client = useQueryClient(), [name, setName] = useState(group?.name ?? ''), [description, setDescription] = useState(group?.description ?? '')
  const save = useMutation({
    mutationFn: () => (group ? updateGroup(group.id, { name, description }) : createGroup(name, description)),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['functional-groups'] }); onClose() },
  })
  return (
    <Dialog title={group ? 'Edit Functional Group' : 'New Functional Group'} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>{group ? 'Save' : 'Create'}</Button></>}>
      <form className="grid gap-3" onSubmit={event => { event.preventDefault(); if (name.trim()) save.mutate() }}>
        <FormField label="Name"><input className={controlClass} value={name} maxLength={80} onChange={event => setName(event.target.value)} autoFocus /></FormField>
        <FormField label="Description"><textarea className={controlClass} rows={3} maxLength={500} value={description} onChange={event => setDescription(event.target.value)} /></FormField>
        {save.isError && <p role="alert">{message(save.error)}</p>}
      </form>
    </Dialog>
  )
}

function Rules({ groups }: { groups: FunctionalGroup[] }) {
  const client = useQueryClient(), rules = useQuery({ queryKey: ['functional-group-rules'], queryFn: fetchRules })
  const [groupId, setGroupId] = useState(''), [department, setDepartment] = useState(''), [title, setTitle] = useState('')
  const refresh = () => client.invalidateQueries({ queryKey: ['functional-group-rules'] })
  const add = useMutation({ mutationFn: () => addRule(groupId, department, title), onSuccess: async () => { setDepartment(''); setTitle(''); await refresh() } })
  const remove = useMutation({ mutationFn: deleteRule, onSuccess: refresh })
  const active = groups.filter(group => group.status === 'active')
  return (
    <section className="grid min-w-0 gap-3" aria-label="Suggestion rules">
      <h3>Suggestion rules</h3>
      <p className="ui-description">Advisory only. A rule matches when Directory Department equals the value and Job Title contains the text; both are optional but one is required. Groups are never assigned automatically.</p>
      <form className="ui-toolbar" onSubmit={event => { event.preventDefault(); if (groupId) add.mutate() }}>
        <input className={controlClass} aria-label="Rule Directory Department" placeholder="Directory Department equals" value={department} maxLength={200} onChange={event => setDepartment(event.target.value)} />
        <input className={controlClass} aria-label="Rule Job Title text" placeholder="Job Title contains" value={title} maxLength={200} onChange={event => setTitle(event.target.value)} />
        <Select aria-label="Rule target Functional Group" value={groupId} onChange={event => setGroupId(event.target.value)}>
          <option value="">Suggest group…</option>{active.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </Select>
        <Button type="submit" disabled={!groupId || (!department.trim() && !title.trim()) || add.isPending}>Add rule</Button>
      </form>
      {(add.isError || remove.isError) && <p role="alert">{message(add.error ?? remove.error)}</p>}
      {rules.data?.items.length ? (
        <DataTable caption="Functional Group suggestion rules" density="compact">
          <thead><tr><th>Directory Department</th><th>Job Title contains</th><th>Suggests</th><th>Actions</th></tr></thead>
          <tbody>{rules.data.items.map(rule => (
            <tr key={rule.id}><td>{rule.department || 'Any'}</td><td>{rule.title_contains || 'Any'}</td>
              <td>{rule.group_name}{rule.group_status === 'archived' && <> <StatusBadge>Archived</StatusBadge></>}</td>
              <td><Button aria-label={`Delete rule suggesting ${rule.group_name}`} onClick={() => remove.mutate(rule.id)}><Trash2 size={14} aria-hidden="true" /></Button></td></tr>))}</tbody>
        </DataTable>
      ) : rules.isSuccess ? <EmptyState>No suggestion rules.</EmptyState> : null}
    </section>
  )
}

export function FunctionalGroupSettings() {
  const client = useQueryClient(), query = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const [search, setSearch] = useState(''), [editing, setEditing] = useState<FunctionalGroup | 'new' | null>(null), [analysing, setAnalysing] = useState<FunctionalGroup | null>(null)
  const archive = useMutation({ mutationFn: (group: FunctionalGroup) => setGroupArchived(group.id, group.status === 'active'), onSuccess: () => client.invalidateQueries({ queryKey: ['functional-groups'] }) })
  const items = (query.data?.items ?? []).filter(group => !search.trim() || `${group.name} ${group.description}`.toLowerCase().includes(search.trim().toLowerCase()))
  return (
    <section className="grid min-w-0 gap-4" aria-label="Functional Groups">
      <p className="ui-description">Business functions maintained by reviewers. Independent of Directory Department and SAP User Group; they never change SAP access.</p>
      <Toolbar>
        <SearchInput aria-label="Search Functional Groups" placeholder="Search Functional Groups" value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} />
        <Button variant="primary" onClick={() => setEditing('new')}><Plus size={14} aria-hidden="true" /> New group</Button>
      </Toolbar>
      {archive.isError && <p role="alert">{message(archive.error)}</p>}
      {query.isError ? <p role="alert">{message(query.error)}</p> : !query.data ? <LoadingState /> : items.length ? (
        <DataTable caption="Functional Groups" density="compact">
          <thead><tr><th>Name</th><th>Description</th><th>Users</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{items.map(group => (
            <tr key={group.id}><td>{group.name}</td><td>{group.description || '—'}</td><td>{group.user_count}</td>
              <td><StatusBadge tone={group.status === 'active' ? 'success' : 'neutral'}>{group.status === 'active' ? 'Active' : 'Archived'}</StatusBadge></td>
              <td><span className="inline-flex gap-1">
                <Button aria-label={`Analyze access of ${group.name}`} disabled={!group.user_count} title={group.user_count ? 'Compare SAP access within the group (advisory)' : 'No classified users'} onClick={() => setAnalysing(group)}><BarChart3 size={14} aria-hidden="true" /></Button>
                <Button aria-label={`Edit ${group.name}`} onClick={() => setEditing(group)}><Pencil size={14} aria-hidden="true" /></Button>
                <Button aria-label={`${group.status === 'active' ? 'Archive' : 'Restore'} ${group.name}`} onClick={() => archive.mutate(group)}>
                  {group.status === 'active' ? <Archive size={14} aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}</Button></span></td></tr>))}</tbody>
        </DataTable>
      ) : <EmptyState>{query.data.items.length ? 'No Functional Groups match the search.' : 'No Functional Groups yet. Create one to start classifying users.'}</EmptyState>}
      {query.data && <Rules groups={query.data.items} />}
      {analysing && <FunctionalGroupAnalysis id={analysing.id} name={analysing.name} onClose={() => setAnalysing(null)} />}
      {editing && <GroupDialog group={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </section>
  )
}
