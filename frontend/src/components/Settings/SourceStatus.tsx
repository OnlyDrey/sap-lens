import { formatTimestamp } from '@/lib/dateFormat'
import { SourceBadge } from '@/components/Shared/SourceBadge'
import { StatusBadge } from '@/components/Shared/Presentation'
import { PreviewStatus } from '@/components/Shared/InvestigationPatterns'
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
export interface SourceEvidence {id:string;name?:string;configured?:boolean;enabled?:boolean;mode?:string;loaded_path?:string;last_successful_load:string|null;last_checked?:string|null;snapshot_available?:boolean;records?:number;error:string|null;loaded:boolean;loading:boolean}
/** Configuration, dataset activation and refresh/check evidence are not interchangeable. */
export function SourceHealthSummary({source}:{source:SourceEvidence}) {
 return <div className="source-health-summary"><div className="ui-toolbar"><StatusBadge>{source.mode||'dynamic'}</StatusBadge>{source.enabled===false?<StatusBadge>Disabled · retained data</StatusBadge>:<SourceBadge loaded={source.loaded} loading={source.loading} error={source.error}/>}</div><dl className="source-health-facts">{source.records!==undefined&&<div><dt>Records</dt><dd>{source.records.toLocaleString()}</dd></div>}<div><dt>Last import / dataset activation</dt><dd>{formatTimestamp(source.last_successful_load,'Not yet loaded')}</dd></div><div><dt>Snapshot</dt><dd>{source.snapshot_available===undefined?'Not checked':source.snapshot_available?'Durable snapshot available':'No durable snapshot'}</dd></div>{source.mode==='dynamic'&&<div><dt>Last validated source check</dt><dd>{formatTimestamp(source.last_checked,'Not yet checked')}</dd></div>}</dl>{source.error&&source.enabled!==false&&<p className="text-sm text-[var(--warning)]">Last load attempt: {source.error.replace(/_/g,' ')}. {source.loaded?'Previously validated data is retained.':'No prior valid data is available.'}</p>}</div>
}
export function SourceStatus({savedPath,draftPath,validated,inspecting=false,source='roles'}:{savedPath:string;draftPath?:string;validated:boolean;inspecting?:boolean;source?:'roles'|'users'}) {
 const {data}=useQuery({queryKey:['diagnostics'],queryFn:()=>apiRequest<{sources:SourceEvidence[]}>('/api/diagnostics')})
 const loaded=data?.sources.find(item=>item.id===source)
 return <div className="source-status text-sm space-y-2"><PreviewStatus validated={validated} inspecting={inspecting}/>{validated&&<p>Preview validated. Loaded data is unchanged.</p>}{draftPath!==undefined&&draftPath!==savedPath&&<p>Selected file differs from the saved location. Apply settings to save it.</p>}{loaded&&<SourceHealthSummary source={loaded}/>}<details><summary>Source location and activation</summary><p>Saved file location: {savedPath||'Not configured'}</p><p>Loaded source: {loaded?.loaded_path||(loaded?.loaded?'Validated snapshot (location unavailable or redacted)':'No successful load')}.</p><p>Save and load CSV applies both sources together. An edited or saved path may differ from the data currently loaded.</p></details></div>
}
