import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { IdPill } from '@/components/Shared/IdPill'

interface Appearance { risks: Record<string, { name: string; color: string }>; activities: Record<string, { name: string; color: string }> }
const none: Appearance = { risks: {}, activities: {} }

/** Local display names and colors for risk and activity identifiers; failures fall back to plain pills. */
export function useSodAppearance(): Appearance {
  return useQuery({ queryKey: ['sod-appearance'], queryFn: () => apiRequest<Appearance>('/api/sod/appearance'), staleTime: 60_000, retry: false }).data || none
}

export function SodPill({ kind, value }: { kind: 'risk' | 'activity'; value: string }) {
  const appearance = useSodAppearance(),
    entry = (kind === 'risk' ? appearance.risks : appearance.activities)[value]
  return <IdPill kind={kind} value={value} color={entry?.color} title={entry?.name ? `${value}: ${entry.name}` : undefined} />
}
