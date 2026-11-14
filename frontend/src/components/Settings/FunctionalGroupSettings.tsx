import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, BarChart3, ListChecks, Pencil, Plus, RotateCcw, Trash2, Users } from 'lucide-react'
import { FunctionalGroupAnalysis } from '@/components/Access/FunctionalGroupAnalysis'
import { createGroup, deleteGroup, fetchGroups, groupsKey, setGroupArchived, updateGroup, type FunctionalGroup } from '@/api/functionalGroups'
import { ContentTabs } from '@/components/Shared/Navigation'
import { Select } from '@/components/Shared/Select'
import { GroupCount } from './GroupCount'
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

/** Why an archived group cannot be deleted, in the words of the server rule. */
const blockers = (group: FunctionalGroup) => [group.references.members && `${group.references.members.toLocaleString()} ${group.references.members === 1 ? 'member' : 'members'}`,
  group.references.rules && `${group.references.rules.toLocaleString()} suggestion ${group.references.rules === 1 ? 'rule' : 'rules'}`,
  group.references.history && 'classification history'].filter(Boolean).join(', ') + '. It stays archived.'

export function FunctionalGroupSettings() {
  const client = useQueryClient(), query = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const [search, setSearch] = useState(''), [editing, setEditing] = useState<FunctionalGroup | 'new' | null>(null), [analysing, setAnalysing] = useState<FunctionalGroup | null>(null), [viewing, setViewing] = useState<FunctionalGroup | null>(null)
  const archive = useMutation({ mutationFn: (group: FunctionalGroup) => setGroupArchived(group.id, group.status === 'active'), onSuccess: () => client.invalidateQueries({ queryKey: ['functional-groups'] }) })
  const [tab, setTab] = useState('groups'), [status, setStatus] = useState<'all' | 'active' | 'archived'>('all'), [deleting, setDeleting] = useState<FunctionalGroup | null>(null)
  const remove = useMutation({ mutationFn: (group: FunctionalGroup) => deleteGroup(group.id), onSuccess: async () => { setDeleting(null); await client.invalidateQueries({ queryKey: ['functional-groups'] }) } })
  const items = (query.data?.items ?? []).filter(group => (status === 'all' || group.status === status) && (!search.trim() || `${group.name} ${group.description}`.toLowerCase().includes(search.trim().toLowerCase())))
  return (
    <section className="grid min-w-0 gap-4" aria-label="Functional Groups">
      <ContentTabs label="Functional Groups sections" value={tab} onChange={setTab} items={[{ value: 'groups', label: 'Groups', icon: <Users size={16} aria-hidden="true" /> }, { value: 'rules', label: 'Suggestion Rules', icon: <ListChecks size={16} aria-hidden="true" /> }]}>
      {tab === 'groups' && <div className="grid min-w-0 gap-4">
      <p className="ui-description">Business functions maintained by reviewers. A user can belong to several groups. Independent of Directory Department and SAP User Group; they never change SAP access. Users is the number of distinct users with a membership in the group, whatever its review status and whether or not the user is in the current SAP import; archived groups keep their members.</p>
      <Toolbar>
        <SearchInput aria-label="Search Functional Groups" placeholder="Search Functional Groups" value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} />
        <Select aria-label="Group status" value={status} onChange={event => setStatus(event.target.value as 'all' | 'active' | 'archived')}><option value="all">All groups</option><option value="active">Active</option><option value="archived">Archived</option></Select>
        <Button variant="primary" onClick={() => setEditing('new')}><Plus size={14} aria-hidden="true" /> New group</Button>
      </Toolbar>
      {archive.isError && <p role="alert">{message(archive.error)}</p>}
      {query.isError ? <p role="alert">{message(query.error)}</p> : !query.data ? <LoadingState /> : items.length ? (
        <DataTable caption="Functional Groups" density="compact">
          <thead><tr><th>Name</th><th>Description</th><th>Users</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{items.map(group => (
            <tr key={group.id}><td>{group.name}</td><td>{group.description || '—'}</td><td><GroupCount count={group.user_count} label={`View ${group.user_count} members of ${group.name}`} onOpen={() => setViewing(group)} /></td>
              <td><StatusBadge tone={group.status === 'active' ? 'success' : 'neutral'}>{group.status === 'active' ? 'Active' : 'Archived'}</StatusBadge></td>
              <td className="col-actions"><span className="inline-flex items-center gap-1">
                <IconButton label={`View members of ${group.name}`} tooltip="View members" size="icon" onClick={() => setViewing(group)}><Users size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Analyze access of ${group.name}`} tooltip={group.user_count ? 'Access analysis: compare SAP access within the group (advisory)' : 'No members to compare'} size="icon" disabled={!group.user_count} onClick={() => setAnalysing(group)}><BarChart3 size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`Edit ${group.name}`} tooltip="Edit" size="icon" onClick={() => setEditing(group)}><Pencil size={14} aria-hidden="true" /></IconButton>
                <IconButton label={`${group.status === 'active' ? 'Archive' : 'Restore'} ${group.name}`} tooltip={group.status === 'active' ? 'Archive' : 'Restore'} size="icon" onClick={() => archive.mutate(group)}>
                  {group.status === 'active' ? <Archive size={14} aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}</IconButton>
                {group.status === 'archived' && <IconButton label={`Delete ${group.name}`} tooltip={group.deletable ? 'Delete permanently' : `Cannot be deleted: ${blockers(group)}`} size="icon" disabled={!group.deletable} onClick={() => setDeleting(group)}><Trash2 size={14} aria-hidden="true" /></IconButton>}</span></td></tr>))}</tbody>
        </DataTable>
      ) : <EmptyState>{query.data.items.length ? 'No Functional Groups match the search and status filter.' : 'No Functional Groups yet. Create one to start classifying users.'}</EmptyState>}
      </div>}
      {tab === 'rules' && (query.isError ? <p role="alert">{message(query.error)}</p> : query.data ? <SuggestionRules groups={query.data.items} /> : <LoadingState />)}
      </ContentTabs>
      {deleting && (
        <Dialog title="Delete Functional Group" onClose={() => { setDeleting(null); remove.reset() }}
          footer={<><Button onClick={() => { setDeleting(null); remove.reset() }}>Cancel</Button><Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(deleting)}>Delete permanently</Button></>}>
          <p>Delete <strong>{deleting.name}</strong> permanently? It has no members, no suggestion rules and no classification history, so nothing else is removed. This cannot be undone.</p>
          {remove.isError && <p role="alert">{message(remove.error)}</p>}
        </Dialog>
      )}
      {analysing && <FunctionalGroupAnalysis id={analysing.id} name={analysing.name} onClose={() => setAnalysing(null)} onViewMembers={() => { setViewing(analysing); setAnalysing(null) }} />}
      {viewing && <GroupMembersDialog group={viewing} onClose={() => setViewing(null)} />}
      {editing && <GroupDialog group={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </section>
  )
}
