import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, BarChart3, Pencil, Plus, RotateCcw, Users } from 'lucide-react'
import { FunctionalGroupAnalysis } from '@/components/Access/FunctionalGroupAnalysis'
import { createGroup, fetchGroups, groupsKey, setGroupArchived, updateGroup, type FunctionalGroup } from '@/api/functionalGroups'
import { GroupMembersDialog } from './GroupMembersDialog'
import { SuggestionRules } from './SuggestionRules'
import { Button, IconButton } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, SearchInput, controlClass } from '@/components/Shared/Controls'
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

export function FunctionalGroupSettings() {
  const client = useQueryClient(), query = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const [search, setSearch] = useState(''), [editing, setEditing] = useState<FunctionalGroup | 'new' | null>(null), [analysing, setAnalysing] = useState<FunctionalGroup | null>(null), [viewing, setViewing] = useState<FunctionalGroup | null>(null)
  const archive = useMutation({ mutationFn: (group: FunctionalGroup) => setGroupArchived(group.id, group.status === 'active'), onSuccess: () => client.invalidateQueries({ queryKey: ['functional-groups'] }) })
  const items = (query.data?.items ?? []).filter(group => !search.trim() || `${group.name} ${group.description}`.toLowerCase().includes(search.trim().toLowerCase()))
  return (
    <section className="grid min-w-0 gap-4" aria-label="Functional Groups">
      <p className="ui-description">Business functions maintained by reviewers. A user can belong to several groups. Independent of Directory Department and SAP User Group; they never change SAP access. The Users count is the number of distinct users in the group.</p>
      <Toolbar>
        <SearchInput aria-label="Search Functional Groups" placeholder="Search Functional Groups" value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} />
        <Button variant="primary" onClick={() => setEditing('new')}><Plus size={14} aria-hidden="true" /> New group</Button>
      </Toolbar>
      {archive.isError && <p role="alert">{message(archive.error)}</p>}
      {query.isError ? <p role="alert">{message(query.error)}</p> : !query.data ? <LoadingState /> : items.length ? (
        <DataTable caption="Functional Groups" density="compact">
          <thead><tr><th>Name</th><th>Description</th><th>Users</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{items.map(group => (
            <tr key={group.id}><td>{group.name}</td><td>{group.description || '—'}</td><td>{group.user_count > 0 ? <button type="button" className="role-count-button" aria-label={`View ${group.user_count} members of ${group.name}`} onClick={() => setViewing(group)}>{group.user_count.toLocaleString()}</button> : '0'}</td>
              <td><StatusBadge tone={group.status === 'active' ? 'success' : 'neutral'}>{group.status === 'active' ? 'Active' : 'Archived'}</StatusBadge></td>
              <td className="col-actions"><span className="inline-flex items-center gap-1">
                <IconButton label={`View members of ${group.name}`} tooltip="View members" size="icon" onClick={() => setViewing(group)}><Users size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Analyze access of ${group.name}`} tooltip={group.user_count ? 'Access analysis: compare SAP access within the group (advisory)' : 'No members to compare'} size="icon" disabled={!group.user_count} onClick={() => setAnalysing(group)}><BarChart3 size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Edit ${group.name}`} tooltip="Edit" size="icon" onClick={() => setEditing(group)}><Pencil size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`${group.status === 'active' ? 'Archive' : 'Restore'} ${group.name}`} tooltip={group.status === 'active' ? 'Archive' : 'Restore'} size="icon" onClick={() => archive.mutate(group)}>
                  {group.status === 'active' ? <Archive size={14} aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}</IconButton></span></td></tr>))}</tbody>
        </DataTable>
      ) : <EmptyState>{query.data.items.length ? 'No Functional Groups match the search.' : 'No Functional Groups yet. Create one to start classifying users.'}</EmptyState>}
      {query.data && <SuggestionRules groups={query.data.items} />}
      {analysing && <FunctionalGroupAnalysis id={analysing.id} name={analysing.name} onClose={() => setAnalysing(null)} onViewMembers={() => { setViewing(analysing); setAnalysing(null) }} />}
      {viewing && <GroupMembersDialog group={viewing} onClose={() => setViewing(null)} />}
      {editing && <GroupDialog group={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </section>
  )
}
