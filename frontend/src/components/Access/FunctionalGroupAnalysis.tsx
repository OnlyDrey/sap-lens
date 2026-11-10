import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Eraser } from 'lucide-react'
import { fetchAnalysis, type Analysis } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { Kpi } from '@/components/Shared/Kpi'
import { DataTable, EmptyState, EvidenceDisclosure, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { SAPUserLink } from '@/components/Shared/SAPUserLink'
import { Input } from '@/components/Shared/Controls'
import { patternLabel, patternTone } from '@/lib/functionalGroupText'
import { textMatches } from '@/lib/searchMatching'
import { userAccessHref } from '@/hooks/useViewHistory'

const pct = (value: number) => `${Math.round(value * 100)}%`
type Filter = 'all' | 'common' | 'uncommon' | 'deviations'
type Panel = 'roles' | 'compared'
const FILTER_LABEL: Record<Filter, string> = { all: 'All roles', common: 'Common roles', uncommon: 'Uncommon roles', deviations: 'Potential deviations' }

/** Who holds a role: exactly the compared members, split into Has role and Missing role. Same population and active-role rule as the frequency calculation. */
function RoleMembers({ role, data }: { role: Analysis['roles'][number]; data: Analysis }) {
  const [search, setSearch] = useState('')
  const holders = new Set(role.holders)
  const rows = data.compared.filter(user => !search.trim() || textMatches(`${user.username} ${user.full_name}`, search))
    .map(user => ({ ...user, has: holders.has(user.username) })).sort((a, b) => Number(b.has) - Number(a.has) || a.username.localeCompare(b.username))
  return (
    <div className="grid gap-2 analysis-drilldown" role="group" aria-label={`Members for ${role.role}`}>
      <p className="ui-description">{role.users} of {role.eligible} compared members hold this role (active assignments only).</p>
      <Input aria-label={`Search members for ${role.role}`} placeholder="Search members" value={search} onChange={event => setSearch(event.target.value)} />
      {rows.length ? (
        <table className="ui-data-table" aria-label={`Members compared for ${role.role}`}>
          <thead><tr><th>SAP user</th><th>Full name</th><th>Role</th><th>SAP account</th></tr></thead>
          <tbody>{rows.map(user => (
            <tr key={user.username}><td><SAPUserLink username={user.username} copyLabel="username" /></td><td>{user.full_name || '—'}</td>
              <td><StatusBadge tone={user.has ? 'success' : 'neutral'}>{user.has ? 'Has role' : 'Missing role'}</StatusBadge></td><td>{user.account_status || '—'}</td></tr>))}</tbody>
        </table>
      ) : <EmptyState>No compared member matches the search.</EmptyState>}
    </div>
  )
}

/** Advisory access comparison inside one Functional Group. Read-only: it never grants, removes or approves access. */
export function FunctionalGroupAnalysis({ id, name, onClose, onViewMembers }: { id: string; name: string; onClose: () => void; onViewMembers?: () => void }) {
  const query = useQuery({ queryKey: ['functional-group-analysis', id], queryFn: () => fetchAnalysis(id) })
  const data = query.data
  const [filter, setFilter] = useState<Filter>('all'), [panel, setPanel] = useState<Panel>('roles'), [search, setSearch] = useState(''), [open, setOpen] = useState<string | null>(null)
  const reset = () => { setFilter('all'); setPanel('roles'); setSearch(''); setOpen(null) }
  const roles = (data?.roles ?? []).filter(role => (filter === 'all' || filter === 'deviations' ? true : role.kind === filter) && (filter !== 'deviations' || role.kind === 'uncommon') && (!search.trim() || textMatches(role.role, search)))
  const users = (data?.users ?? []).filter(user => filter !== 'deviations' || user.additional_roles.length || user.missing_common_roles.length)
  const compared = (data?.compared ?? []).filter(user => !search.trim() || textMatches(`${user.username} ${user.full_name}`, search))
  const filtered = filter !== 'all' || panel !== 'roles' || search.trim() !== ''
  return (
    <Dialog title={`Access analysis · ${name}`} onClose={onClose} footer={null}>
      <div className="grid min-w-0 gap-3">
        {query.isError ? <p role="alert">{query.error instanceof Error ? query.error.message : 'The analysis is unavailable.'}</p> : !data ? <LoadingState /> : (
          <>
            <div className="analysis-kpis" role="group" aria-label="Group summary">
              <Kpi label="Members" value={data.members} layout="expanded" onClick={onViewMembers} navigates title={onViewMembers ? 'Open the member list' : undefined} />
              <Kpi label="Compared" value={data.eligible} layout="expanded" onClick={() => { setPanel('compared'); setFilter('all'); setSearch('') }} active={panel === 'compared'} title="Show the members included in the analysis" />
              <Kpi label="Distinct roles" value={data.distinct_roles} layout="expanded" onClick={() => { setPanel('roles'); setFilter('all') }} active={panel === 'roles' && filter === 'all'} title="Show all analyzed roles" />
              <Kpi label="Common roles" value={data.common_roles} layout="expanded" tone="success" onClick={() => { setPanel('roles'); setFilter('common') }} active={filter === 'common'} title="Filter to common roles" />
              <Kpi label="Potential deviations" value={data.deviations} layout="expanded" tone={data.deviations ? 'warning' : 'neutral'} onClick={() => { setPanel('roles'); setFilter('deviations') }} active={filter === 'deviations'}
                title="Filter to potential deviations (a prompt to investigate, not a finding)" />
            </div>
            <EvidenceDisclosure title="About this analysis">
              <p className="ui-description">{data.method.note} Common means at least {pct(data.method.common_at)} of compared members hold the role; uncommon at most {pct(data.method.uncommon_at)}.</p>
            </EvidenceDisclosure>
            {data.limitations.map(text => <p key={text} role="note" className="evidence-badge evidence-warning">{text}</p>)}
            <div className="ui-toolbar">
              <Input aria-label="Search roles or members" placeholder={panel === 'roles' ? 'Search roles' : 'Search compared members'} value={search} onChange={event => setSearch(event.target.value)} />
              {filtered && <><StatusBadge>{panel === 'compared' ? 'Compared members' : FILTER_LABEL[filter]}</StatusBadge><Button variant="outline" onClick={reset}><Eraser size={16} aria-hidden="true" />Reset filters</Button></>}
            </div>
            {panel === 'compared' ? (
              compared.length ? (
                <DataTable caption="Members included in the analysis" density="compact">
                  <thead><tr><th>SAP user</th><th>Full name</th><th>Active roles</th><th>SAP account</th></tr></thead>
                  <tbody>{compared.map(user => <tr key={user.username}><td><SAPUserLink username={user.username} copyLabel="username" /></td><td>{user.full_name || '—'}</td><td>{user.roles}</td><td>{user.account_status || '—'}</td></tr>)}</tbody>
                </DataTable>
              ) : <EmptyState>No compared member matches.</EmptyState>
            ) : roles.length ? (
              <DataTable caption="Role frequency" density="compact" sticky>
                <thead><tr><th>Role</th><th>Members</th><th>Frequency</th><th>Pattern</th></tr></thead>
                <tbody>{roles.map(role => (
                  <Fragment key={role.role}>
                    <tr><td><code>{role.role}</code></td>
                      <td><button type="button" className="role-count-button" aria-expanded={open === role.role} aria-label={`${role.users} of ${role.eligible} members hold ${role.role}: show members`} onClick={() => setOpen(open === role.role ? null : role.role)}>{role.users} of {role.eligible}</button></td>
                      <td>{pct(role.frequency)}</td>
                      <td><StatusBadge tone={patternTone(role.kind)}>{patternLabel(role.kind)}</StatusBadge></td></tr>
                    {open === role.role && <tr><td colSpan={4}><RoleMembers role={role} data={data} /></td></tr>}
                  </Fragment>))}</tbody>
              </DataTable>
            ) : <EmptyState>{data.roles.length ? 'No role matches the current filter.' : 'No active role assignments among the compared members.'}</EmptyState>}
            {panel === 'roles' && users.length > 0 && (
              <DataTable caption="User-level access differences" density="compact">
                <thead><tr><th>SAP user</th><th>Roles</th><th>Additional uncommon roles</th><th>Missing common roles</th></tr></thead>
                <tbody>{users.map(user => (
                  <tr key={user.username}><td><SAPUserLink username={user.username} copyLabel="username" /></td><td>{user.roles}</td>
                    <td>{user.additional_roles.join(', ') || '—'}</td><td>{user.missing_common_roles.join(', ') || '—'}</td></tr>))}</tbody>
              </DataTable>
            )}
            <p className="ui-description">Investigate a difference in <a href={userAccessHref('compare')}>Compare users</a> or the user's details; any change goes through the existing review workflow.</p>
          </>
        )}
      </div>
    </Dialog>
  )
}
