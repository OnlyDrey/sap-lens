import { directoryDisplayName } from '@/lib/directoryDisplayName'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, UserRoundX } from 'lucide-react'
import { apiRequest } from '@/api/client'
import type { Employee } from '@/components/Shared/EmployeeInformation'
import { useViewHistory } from '@/hooks/useViewHistory'

export interface EmployeeMatch {
  status: string
  employee: Employee | null
  manager_sap?: {
    status: string
    username: string | null
    display_name?: string
  }
}
export function useEmployeeMatch(username: string) {
  return useQuery({
    queryKey: ['employee-match', username],
    queryFn: () =>
      apiRequest<EmployeeMatch>(
        `/api/employees/match/${encodeURIComponent(username)}`,
      ),
  })
}
export function ManagerSummary({
  employee,
  manager,
}: {
  employee: Employee
  manager: EmployeeMatch['manager_sap']
}) {
  const { change } = useViewHistory()
  const status =
    (
      {
        ambiguous: 'Multiple SAP users found',
        unmatched: 'SAP user not found',
        missing_email: 'Manager email not provided',
        mapping_unavailable: 'SAP identity source unavailable',
      } as Record<string, string>
    )[manager?.status || 'missing_email'] || 'SAP identity unavailable'
  const name =
    manager?.display_name ||
    directoryDisplayName(employee.manager.name) ||
    'Manager not provided'
  const identity = (
    <>
      <strong>{name}</strong>
      {employee.manager.title && (
        <span className="text-sm text-[var(--muted)]">
          {employee.manager.title}
        </span>
      )}
    </>
  )
  return (
    <section aria-label="Reports to" className="profile-manager">
      <h3>Reports to</h3>
      {manager?.status === 'matched' && manager.username ? (
        <button
          className="manager-identity"
          aria-label="View SAP user"
          onClick={() => change({ page: 'users', user: manager.username! })}
        >
          {identity}
          <span className="text-xs">
            View SAP user{' '}
            <ArrowUpRight size={14} aria-hidden="true" className="inline" />
          </span>
        </button>
      ) : (
        <div className="manager-identity">
          {identity}
          <span className="evidence-badge evidence-neutral">
            <UserRoundX size={13} aria-hidden="true" />
            {status}
          </span>
        </div>
      )}
    </section>
  )
}
