import { useMutation } from '@tanstack/react-query'
import { compareRoles } from '@/api/client'
import type { ComparisonResult } from '@/api/types'
export function useComparison() {
  return useMutation<ComparisonResult, Error, string[]>({ mutationFn: compareRoles, retry: 1 })
}