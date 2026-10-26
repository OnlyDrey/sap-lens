import { useState, type ReactNode } from 'react'
import { Info } from 'lucide-react'
import { formatTimestamp } from '@/lib/dateFormat'
import { SourceBadge } from '@/components/Shared/SourceBadge'
import { StatusBadge, MetadataList } from '@/components/Shared/Presentation'
import { PreviewStatus } from '@/components/Shared/InvestigationPatterns'
import { Dialog } from '@/components/Shared/Dialog'
import { Button } from '@/components/Shared/Button'
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
export interface SourceEvidence {
 id:string;name?:string;configured?:boolean;enabled?:boolean;mode?:string;configured_path?:string;loaded_path?:string;attempted_path?:string;availability?:string;assignments?:number
 last_successful_load:string|null;last_checked?:string|null;snapshot_available?:boolean;records?:number;error:string|null;loaded:boolean;loading:boolean
}
export function SourceDetailsDialog({source,onClose,children}:{source:SourceEvidence;onClose:()=>void;children?:ReactNode}) {
 return <Dialog title={`${source.name||'CSV source'} technical details`} onClose={onClose}><SourceHealthSummary source={source}/><MetadataList items={[
  {label:'Configured file',value:source.configured_path||(source.configured?'Configured (location redacted)':'Not configured')},
  {label:'Loaded source',value:source.loaded_path||(source.loaded?'Validated snapshot (location unavailable or redacted)':'No successful load')},
  {label:'Availability',value:sourceAvailability(source.availability)},
  {label:'Assignment records',value:source.assignments?.toLocaleString()||'Not available'},
  ...(source.error?[{label:'Last attempt',value:source.attempted_path||'Location unavailable'}]:[]),
 ]}/><p className="ui-description">A selected or configured location is not proof of successful validation. Failed replacement attempts retain previously validated data.</p>{children}</Dialog>
}
/** Configuration, dataset activation and refresh/check evidence are not interchangeable. */
export function SourceHealthSummary({source}:{source:SourceEvidence}) {
 return <div className="source-health-summary"><div className="ui-toolbar"><StatusBadge tone={source.mode==='static'?'neutral':'info'}>{source.mode==='static'?'Static':'Dynamic'}</StatusBadge>{source.enabled===false?<StatusBadge>Disabled · retained data</StatusBadge>:<SourceBadge loaded={source.loaded} loading={source.loading} error={source.error}/>}</div><MetadataList items={[
 {label:'Records',value:source.records===undefined?'Not available':source.records.toLocaleString()},
 {label:'Last import / dataset activation',value:formatTimestamp(source.last_successful_load,'Not yet loaded')},
 {label:'Snapshot',value:source.snapshot_available===undefined?'Not checked':source.snapshot_available?'Durable snapshot available':'No durable snapshot'},
 {label:'Last validated source check',value:formatTimestamp(source.last_checked,source.mode==='static'?'Not checked · Static source':'Not yet checked')},
 ]}/>{source.availability&&<p className="ui-description">{sourceAvailability(source.availability)}</p>}{source.error&&source.enabled!==false&&<StatusBadge tone={source.loaded?'warning':'error'}>{source.loaded?'Warning':'Error'}</StatusBadge>}{source.error&&source.enabled!==false&&<p className="text-sm text-[var(--warning)]">Last load attempt: {source.error.replace(/_/g,' ')}. {source.loaded?'Previously validated data is retained.':'No prior valid data is available.'}</p>}</div>
}
export function useSourceEvidence(source:string) {
 const query=useQuery({queryKey:['diagnostics'],queryFn:()=>apiRequest<{sources:SourceEvidence[]}>('/api/diagnostics')})
 return {...query,source:query.data?.sources.find(item=>item.id===source)}
}
export function SourceStatusSummary({source}:{source:string}) {
 const result=useSourceEvidence(source)
 return result.source?<SourceHealthSummary source={result.source}/>:<p role={result.isError?'alert':'status'}>{result.isError?'Source status could not be checked.':'Checking source status…'}</p>
}
export function SourceStatus({savedPath,draftPath,validated,inspecting=false,source='roles'}:{savedPath:string;draftPath?:string;validated:boolean;inspecting?:boolean;source?:'roles'|'users'}) {
 const {source:loaded}=useSourceEvidence(source),[open,setOpen]=useState(false)
 return <div className="source-status text-sm space-y-2"><PreviewStatus validated={validated} inspecting={inspecting}/>{validated&&<p>Preview validated. Loaded data is unchanged.</p>}{draftPath!==undefined&&draftPath!==savedPath&&<p>Selected file differs from the saved location. Apply settings to save it.</p>}{loaded&&<SourceHealthSummary source={loaded}/>}<Button onClick={()=>setOpen(true)}><Info size={16} aria-hidden="true"/>Technical source details</Button>{open&&<SourceDetailsDialog source={{id:source,loaded:false,loading:false,error:null,last_successful_load:null,...loaded,configured_path:savedPath}} onClose={()=>setOpen(false)}/>}</div>
}

function sourceAvailability(value?:string) {
 return ({available_at_last_load:'Available at last successful load; current access not checked',not_checked:'Not checked',missing:'File missing on last attempt',file_missing:'File missing on last attempt',access_denied:'Access denied on last attempt',invalid:'Validation failed on last attempt',snapshot:'Durable snapshot unavailable'} as Record<string,string>)[value||'']||value?.replace(/_/g,' ')||'Not checked'
}
