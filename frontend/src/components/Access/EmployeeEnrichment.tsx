import { directoryDisplayName } from '@/lib/directoryDisplayName'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, UserRoundX } from 'lucide-react'
import { apiRequest } from '@/api/client'
import type { Employee } from '@/components/Shared/EmployeeInformation'
import { useViewHistory } from '@/hooks/useViewHistory'

export interface EmployeeMatch {
  status: string
  employee: Employee | null
  manager_sap?: { status: string; username: string | null }
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
  return (
    <section aria-label="Reports to" className="profile-manager">
      <h3>Reports to</h3>
      <p>
        {directoryDisplayName(employee.manager.name) || 'Manager not provided'}
      </p>
      {employee.manager.title && (
        <p className="text-sm text-[var(--muted)]">{employee.manager.title}</p>
      )}
      {manager?.status === 'matched' && manager.username ? (
        <button
          className="settings-secondary-button"
          onClick={() =>
            change({ page: 'users', user: manager.username!, userContext: {} })
          }
        >
          <ArrowUpRight size={15} aria-hidden="true" />
          View SAP user
        </button>
      ) : (
        <span className="evidence-badge evidence-neutral">
          <UserRoundX size={13} aria-hidden="true" />
          {status}
        </span>
      )}
    </section>
  )
}
