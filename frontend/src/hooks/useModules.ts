import { useQuery } from '@tanstack/react-query'
import { fetchModules } from '@/api/client'
import type { ModuleInfo } from '@/api/types'
export function useModules() {
  return useQuery<ModuleInfo[], Error>({ queryKey: ['modules'], queryFn: fetchModules, staleTime: 5 * 60 * 1000 })
}