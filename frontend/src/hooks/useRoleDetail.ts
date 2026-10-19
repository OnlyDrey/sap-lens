import { useQuery } from '@tanstack/react-query'
import { fetchRoleDetail } from '@/api/client'
import type { RoleDetail } from '@/api/types'
export function useRoleDetail(roleName: string | null) {
  return useQuery<RoleDetail, Error>({
    queryKey: ['role', roleName],
    queryFn: () => fetchRoleDetail(roleName!),
    enabled: !!roleName, staleTime: 5 * 60 * 1000, retry: 2,
  })
}