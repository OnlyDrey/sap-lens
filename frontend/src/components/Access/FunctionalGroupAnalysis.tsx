import { useQuery } from '@tanstack/react-query'
import { fetchAnalysis } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { DataTable, EmptyState, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { SAPUserLink } from '@/components/Shared/SAPUserLink'
import { userAccessHref } from '@/hooks/useViewHistory'

const pct = (value: number) => `${Math.round(value * 100)}%`

/** Advisory access comparison inside one Functional Group. Read-only: it never grants, removes or approves access. */
export function FunctionalGroupAnalysis({ id, name, onClose }: { id: string; name: string; onClose: () => void }) {
  const query = useQuery({ queryKey: ['functional-group-analysis', id], queryFn: () => fetchAnalysis(id) })
  const data = query.data
  return (
    <Dialog title={`Access analysis · ${name}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <div className="grid min-w-0 gap-3">
        {query.isError ? <p role="alert">{query.error instanceof Error ? query.error.message : 'The analysis is unavailable.'}</p> : !data ? <LoadingState /> : (
          <>
            <dl className="profile-fields" aria-label="Group summary">
              <div><dt>Members</dt><dd>{data.members}</dd></div>
              <div><dt>Compared</dt><dd>{data.eligible}</dd></div>
              <div><dt>Distinct roles</dt><dd>{data.distinct_roles}</dd></div>
              <div><dt>Common roles</dt><dd>{data.common_roles}</dd></div>
              <div><dt>Potential deviations</dt><dd>{data.deviations}</dd></div>
            </dl>
            <p className="ui-description">{data.method.note} Common means at least {pct(data.method.common_at)} of compared members hold the role; uncommon at most {pct(data.method.uncommon_at)}.</p>
            {data.limitations.map(text => <p key={text} role="note" className="evidence-badge evidence-warning">{text}</p>)}
            {data.roles.length ? (
              <DataTable caption="Role frequency" density="compact">
                <thead><tr><th>Role</th><th>Members</th><th>Frequency</th><th>Pattern</th></tr></thead>
                <tbody>{data.roles.map(role => (
                  <tr key={role.role}><td><code>{role.role}</code></td><td>{role.users} of {role.eligible}</td><td>{pct(role.frequency)}</td>
                    <td><StatusBadge tone={role.kind === 'uncommon' ? 'warning' : role.kind === 'common' ? 'success' : 'neutral'}>{role.kind}</StatusBadge></td></tr>))}</tbody>
              </DataTable>
            ) : <EmptyState>No active role assignments among the compared members.</EmptyState>}
            {data.users.length > 0 && (
              <DataTable caption="User-level access differences" density="compact">
                <thead><tr><th>SAP user</th><th>Roles</th><th>Additional uncommon roles</th><th>Missing common roles</th></tr></thead>
                <tbody>{data.users.map(user => (
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
