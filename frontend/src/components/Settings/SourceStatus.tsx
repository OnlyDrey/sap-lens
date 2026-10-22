import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'

/** Saved configuration, preview validation and loaded dataset are separate evidence. */
export function SourceStatus({ savedPath, validated }: { savedPath: string; validated: boolean }) {
  const { data } = useQuery({ queryKey: ['dataset-load-status'], queryFn: () => apiRequest<{ last_loaded: string | null }>('/health') })
  return <div className="text-sm text-[var(--muted)] space-y-1 break-all">
    <p>Saved file location: {savedPath || 'Not configured'}</p>
    <p>{validated ? 'Preview validated. Loaded data is unchanged.' : 'Validate this file before applying changes.'}</p>
    <p>Last successful data load: {data?.last_loaded ? new Date(data.last_loaded).toLocaleString('en-GB') : 'Not available'}.</p>
    <p>Save and load CSV applies both sources together. An edited or saved path may differ from the data currently loaded.</p>
  </div>
}
