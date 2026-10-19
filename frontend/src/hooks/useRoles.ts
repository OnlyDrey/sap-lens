import { useQuery } from '@tanstack/react-query'
import { fetchRoles } from '@/api/client'
import type { RoleSummary } from '@/api/types'
export function useRoles(module?: string | null, search?: string) {
  return useQuery<RoleSummary[], Error>({
    queryKey: ['roles', module ?? null, search ?? ''],
    queryFn: () => fetchRoles(module ?? undefined, search ?? undefined),
    staleTime: 5 * 60 * 1000, retry: 2,
  })
}