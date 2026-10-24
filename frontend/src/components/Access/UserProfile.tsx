import {
  AccountStatus,
  accountValidity,
  userTypeLabel,
} from '@/components/Shared/AccountStatus'
import { UserRound, ShieldCheck, Building2 } from 'lucide-react'
import type { UserDetail } from '@/api/access'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
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
      <header className="profile-identity-header">
        <h2>{sapName || 'SAP name not provided'}</h2>
        <p>{user.emails.join(', ') || 'SAP email not provided'}</p>
      </header>
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
                ? userTypeLabel(user.accounts[0]?.user_type || '')
                : 'See account evidence'}
            </dd>
          </div>
        </dl>
      </section>
      <section aria-label="Account Status" className="profile-group">
        <h2>
          <ShieldCheck size={18} aria-hidden="true" />
          Account Status
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
              <AccountStatus value={user.account_status} />
            </dd>
          </div>
          <div>
            <dt>Lock status</dt>
            <dd>
              <AccountStatus value={user.lock_status} kind="lock" />
            </dd>
          </div>
          <div>
            <dt>AD account status</dt>
            <dd>
              <AccountStatus
                value={employee?.account_status || 'Unknown'}
                kind="ad"
              />
            </dd>
          </div>
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
              <div>
                <dt>Job title</dt>
                <dd>{employee.title || 'Not provided'}</dd>
              </div>
              <div>
                <dt>Department</dt>
                <dd>{employee.department || 'Not provided'}</dd>
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
      {employee?.account_status === 'Disabled' &&
        accountValidity(user.account_status) === 'Valid' &&
        user.lock_status === 'Unlocked' && (
          <p role="status" className="profile-account-warning">
            Account mismatch detected — AD is disabled while the SAP account
            remains valid and unlocked.
          </p>
        )}
    </section>
  )
}
