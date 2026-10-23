import { useQuery } from '@tanstack/react-query'
import { accessQuery } from '@/api/access'

export interface RecordNavigation {
  index: number | null
  total: number
  previous: string | null
  next: string | null
}
export type InvestigationFilters = Record<string, string | string[] | number | boolean>

/** Never infer neighbours from a partial page or from a differently sorted list. */
export function useRecordNavigation(path: 'users' | 'releases', filters: InvestigationFilters, selected: string, onSelect: (key: string) => void) {
  const result = useQuery({
    queryKey: ['record-navigation', path, filters, selected],
    queryFn: () => accessQuery<{ navigation: RecordNavigation }>(path, { ...filters, anchor: selected, offset: 0, limit: 1 }),
    enabled: Boolean(selected),
    gcTime: 0, // Do not retain a growing navigation response per visited identity.
  })
  const navigation = result.data?.navigation
  const ready = !result.isFetching && !result.error && navigation?.index != null
  return {
    index: ready ? navigation.index! : -1,
    total: navigation?.total || 0,
    onPrevious: ready && navigation.previous ? () => onSelect(navigation.previous!) : undefined,
    onNext: ready && navigation.next ? () => onSelect(navigation.next!) : undefined,
    loading: Boolean(selected) && result.isFetching,
    error: result.error,
    missing: Boolean(selected) && !result.isFetching && !result.error && navigation?.index === null,
  }
}
export type RecordNavigationState = ReturnType<typeof useRecordNavigation>
