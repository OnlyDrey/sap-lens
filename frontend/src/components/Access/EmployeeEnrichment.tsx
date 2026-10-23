import { useQuery } from '@tanstack/react-query'
import { UserRound, ArrowUpRight } from 'lucide-react'
import { apiRequest } from '@/api/client'
import type { Employee } from '@/components/Shared/EmployeeInformation'
import { useViewHistory } from '@/hooks/useViewHistory'

export function EmployeeEnrichment({ username }: { username: string }) {
  const { change } = useViewHistory()
  const query = useQuery({
    queryKey: ['employee-match', username],
    queryFn: () =>
      apiRequest<{
        status: string
        employee: Employee | null
        manager_sap?: { status: string; username: string | null }
      }>(`/api/employees/match/${encodeURIComponent(username)}`),
  })
  if (query.isError)
    return <p role="alert">Employee information could not be checked.</p>
  if (!query.data || query.data.status === 'directory_unavailable') return null
  const employee = query.data.employee,
    manager = query.data.manager_sap
  const states: Record<string, string> = {
    missing_email: 'SAP email is missing.',
    duplicate_email: 'Duplicate directory email; no employee selected.',
    ambiguous_sap_email: 'Multiple SAP email values; no employee selected.',
    unmatched: 'No exact directory email match.',
    mapping_unavailable:
      'Identity enrichment unavailable: enable User–Role Mapping and load SAP email data.',
  }
  return (
    <section
      className="information-card employee-profile space-y-3"
      aria-label="Employee Directory enrichment"
    >
      <header className="flex flex-wrap justify-between gap-2">
        <h2>Employee information</h2>
        <span className="text-xs text-[var(--muted)]">
          {employee ? 'Exact email match' : 'Not matched'}
        </span>
      </header>
      {employee ? (
        <>
          <div className="employee-profile-heading">
            <span className="employee-avatar" aria-hidden="true">
              <UserRound size={25} />
            </span>
            <div>
              <h3>{employee.name || 'Unknown employee'}</h3>
              <p>{employee.title || 'Job title not provided'}</p>
              <p className="text-sm text-[var(--muted)]">
                {employee.email || 'Email not provided'}
              </p>
            </div>
          </div>
          <dl className="employee-profile-fields">
            {[
              ['Department', employee.department],
              ['Site', employee.site],
              ['AD username', employee.username],
              ['AD account status', employee.account_status],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || 'Unknown'}</dd>
              </div>
            ))}
          </dl>
          <section className="employee-manager" aria-label="Reports to">
            <div>
              <h3 className="text-xs text-[var(--muted)]">Reports to</h3>
              <p>{employee.manager.name || 'Manager not provided'}</p>
              {employee.manager.title && (
                <p className="text-sm text-[var(--muted)]">
                  {employee.manager.title}
                </p>
              )}
            </div>
            {manager?.status === 'matched' && manager.username ? (
              <button
                className="settings-secondary-button"
                onClick={() =>
                  change({
                    page: 'users',
                    user: manager.username!,
                    userContext: {},
                  })
                }
              >
                <ArrowUpRight size={15} aria-hidden="true" />
                View SAP user
              </button>
            ) : (
              <p className="text-xs text-[var(--muted)]">
                {(
                  {
                    ambiguous: 'Multiple SAP users found',
                    unmatched: 'SAP user not found',
                    missing_email: 'Manager email not provided',
                    mapping_unavailable: 'SAP identity source unavailable',
                  } as Record<string, string>
                )[manager?.status || 'missing_email'] ||
                  'SAP identity unavailable'}
              </p>
            )}
          </section>
          <p className="text-xs text-[var(--muted)]">
            AD employee enrichment; SAP identity, validity and account status
            remain unchanged.
          </p>
        </>
      ) : (
        <p>
          {states[query.data.status] || 'Employee information unavailable.'}
        </p>
      )}
    </section>
  )
}
