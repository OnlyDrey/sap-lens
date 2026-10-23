import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookUser } from 'lucide-react'
import { apiRequest } from '@/api/client'
import {
  EmployeeInformation,
  type Employee,
} from '@/components/Shared/EmployeeInformation'

export function EmployeeEnrichment({ username }: { username: string }) {
  const [managerId, setManagerId] = useState<{
    id: string
    generation: string
  } | null>(null)
  useEffect(() => setManagerId(null), [username])
  const query = useQuery({
    queryKey: ['employee-match', username],
    queryFn: () =>
      apiRequest<{
        status: string
        employee: Employee | null
        generation?: string
      }>(`/api/employees/match/${encodeURIComponent(username)}`),
  })
  const manager = useQuery({
    queryKey: ['employee-manager', managerId?.id, managerId?.generation],
    enabled: managerId != null,
    queryFn: () =>
      apiRequest<Employee>(
        `/api/employees/record/${managerId!.id}?generation=${managerId!.generation}`,
      ),
  })
  if (!query.data || query.data.status === 'directory_unavailable') return null
  const employee = query.data.employee
  return (
    <section
      className="information-card space-y-3"
      aria-label="Employee Directory enrichment"
    >
      <h2 className="flex items-center gap-2">
        <BookUser size={18} aria-hidden="true" />
        Employee Directory
      </h2>
      {employee ? (
        <>
          <p className="text-sm">
            Exact email match · SAP source data unchanged
          </p>
          <EmployeeInformation
            employee={employee}
            onManager={(id) =>
              setManagerId({ id, generation: query.data!.generation! })
            }
          />
        </>
      ) : (
        <p>
          {(
            {
              missing_email: 'SAP email is missing.',
              duplicate_email:
                'Duplicate directory email; no employee selected.',
              ambiguous_sap_email:
                'Multiple SAP email values; no employee selected.',
              unmatched: 'No exact directory email match.',
            } as Record<string, string>
          )[query.data.status] || 'Employee information unavailable.'}
        </p>
      )}
      {manager.isError && (
        <p role="alert">Manager unavailable; the directory may have changed.</p>
      )}
      {manager.data && managerId?.generation === query.data.generation && (
        <section aria-label="Manager employee details">
          <h3>Manager employee details</h3>
          <EmployeeInformation
            employee={manager.data}
            onManager={(id) =>
              setManagerId({ id, generation: managerId!.generation })
            }
          />
        </section>
      )}
    </section>
  )
}
