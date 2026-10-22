import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'

/** Saved configuration, preview validation and loaded dataset are separate evidence. */
export function SourceStatus({ savedPath, draftPath, validated, inspecting = false, source = 'roles' }: { savedPath: string; draftPath?: string; validated: boolean; inspecting?: boolean; source?: 'roles' | 'users' }) {
  const { data } = useQuery({ queryKey: ['diagnostics'], queryFn: () => apiRequest<{ sources: {id:string;loaded_path?:string;last_successful_load:string|null;error:string|null}[] }>('/api/diagnostics') })
  const loaded = data?.sources.find(item => item.id === source)
  return <div className="source-status text-sm text-[var(--muted)] space-y-1 break-all">
    <p className="source-state">{inspecting ? 'Inspecting selected file…' : validated ? 'Preview validated. Loaded data is unchanged.' : 'Not yet validated'}</p>
    {draftPath !== undefined && draftPath !== savedPath && <p>Selected file differs from the saved location. Apply settings to save it.</p>}
    <p>Saved file location: {savedPath || 'Not configured'}</p>
    <p>Loaded source: {loaded?.loaded_path || 'No successful load'}.</p>
    <p>Last successful data load: {loaded?.last_successful_load ? new Date(loaded.last_successful_load).toLocaleString('en-GB') : 'Not available'}.</p>
    {loaded?.error && <p className="text-[var(--warning)]">Last load attempt: {loaded.error.replace(/_/g, ' ')}. Previous data is retained.</p>}
    <p>Save and load CSV applies both sources together. An edited or saved path may differ from the data currently loaded.</p>
  </div>
}
