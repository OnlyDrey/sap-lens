import { directoryDisplayName } from '@/lib/directoryDisplayName'
import { UserRound, ShieldCheck, Building2 } from 'lucide-react'
import type { UserDetail } from '@/api/access'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import {
  EvidenceBadge,
  LockStatus,
} from '@/components/Shared/InvestigationNavigation'
import { StatusPill } from '@/components/Shared/StatusPill'
import { formatDate } from '@/lib/dateFormat'
import { useEmployeeMatch, ManagerSummary } from './EmployeeEnrichment'
export function UserProfile({ user }: { user: UserDetail }) {
  const match = useEmployeeMatch(user.username),
    employee = match.data?.employee
  const sapName = user.names
    .map((n) => n.join(' ').trim())
    .filter(Boolean)
    .join(' / ')
  return (
    <section className="user-profile" aria-label="User profile">
      <section aria-label="SAP Identity" className="profile-group">
        <h2>
          <UserRound size={18} aria-hidden="true" />
          SAP Identity
        </h2>
        <dl className="profile-fields">
          <div>
            <dt>Username</dt>
            <dd>
              <RoleIdentifier value={user.username} label="username" />
            </dd>
          </div>
          <div>
            <dt>Full name</dt>
            <dd>{sapName || 'Unknown'}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user.emails.join(', ') || 'Unknown'}</dd>
          </div>
          <div>
            <dt>SAP User Group</dt>
            <dd>
              {user.groups
                .map((group) => group || 'Unknown group')
                .join(', ') || 'Unknown'}
            </dd>
          </div>
          <div>
            <dt>User type</dt>
            <dd>
              {user.account_total === 1
                ? user.accounts[0]?.user_type || 'Unknown'
                : 'See account evidence'}
            </dd>
          </div>
        </dl>
      </section>
      <section aria-label="Account & Validity" className="profile-group">
        <h2>
          <ShieldCheck size={18} aria-hidden="true" />
          Account &amp; Validity
        </h2>
        <dl className="profile-fields">
          <div>
            <dt>Valid from</dt>
            <dd>
              {user.account_total === 1
                ? formatDate(user.accounts[0]?.valid_from)
                : 'Multiple source records'}
            </dd>
          </div>
          <div>
            <dt>Valid until</dt>
            <dd>
              {user.account_total === 1
                ? formatDate(user.accounts[0]?.valid_to)
                : 'See account evidence'}
            </dd>
          </div>
          <div>
            <dt>SAP account status</dt>
            <dd>
              {user.account_status.split('/').map((value) => (
                <EvidenceBadge key={value} value={value} />
              ))}
            </dd>
          </div>
          <div>
            <dt>Lock status</dt>
            <dd>
              <LockStatus value={user.lock_status} />
            </dd>
          </div>
          {employee && (
            <div>
              <dt>AD account status</dt>
              <dd>
                {employee.account_status === 'Unknown' ? (
                  <EvidenceBadge value="Unknown" />
                ) : (
                  <StatusPill enabled={employee.account_status === 'Enabled'} />
                )}
              </dd>
            </div>
          )}
        </dl>
      </section>
      <section aria-label="Organization" className="profile-group">
        <h2>
          <Building2 size={18} aria-hidden="true" />
          Organization
        </h2>
        {employee ? (
          <>
            <dl className="profile-fields">
              {!sapName && employee.name && (
                <div>
                  <dt>Directory display name</dt>
                  <dd>{directoryDisplayName(employee.name)}</dd>
                </div>
              )}
              <div>
                <dt>Job title</dt>
                <dd>{employee.title || 'Not provided'}</dd>
              </div>
              <div>
                <dt>Department</dt>
                <dd>{employee.department || 'Not provided'}</dd>
              </div>
              <div>
                <dt>AD username</dt>
                <dd>{employee.username || 'Not provided'}</dd>
              </div>
            </dl>
            <ManagerSummary
              employee={employee}
              manager={match.data?.manager_sap}
            />
          </>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            {match.isLoading
              ? 'Loading directory enrichment…'
              : match.isError
                ? 'Directory enrichment could not be checked. SAP information is retained.'
                : match.data?.status === 'directory_unavailable'
                  ? 'Employee Directory disabled or unavailable.'
                  : match.data?.status === 'mapping_unavailable'
                    ? 'SAP email source unavailable.'
                    : 'No uniquely matched directory organization information. Review Data Sources for matching diagnostics.'}
          </p>
        )}
      </section>
    </section>
  )
}
