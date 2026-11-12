import {useEffect,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Clock,Download,Trash2,Save} from 'lucide-react'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {SettingsSelect} from './Controls'
import {Card,ErrorState,LoadingState,StatusBadge} from '@/components/Shared/Presentation'
import {formatTimestamp} from '@/lib/dateFormat'
import {TimeInput24} from '@/components/Shared/TimeInput24'

type Schedule={enabled:boolean;mode:'daily'|'cron';time:string;cron:string;timezone:string;keep:number}
type Status={encryption_ready?:boolean;revision:number;schedule:Schedule;next_runs:string[];description:string;last_success:string|null;last_failure:string|null;last_outcome?:string;attempts?:{at:string;status:string}[]}
type History={items:{id:string;created_at:string;origin:string;status:string;size:number;verified:boolean}[];total:number;storage_bytes:number;destination:string}

export function BackupScheduling(){
 const client=useQueryClient(),query=useQuery({queryKey:['backup-schedule'],queryFn:()=>apiRequest<Status>('/api/backups/schedule'),refetchOnMount:'always'})
 const [draft,setDraft]=useState<Schedule|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 useEffect(()=>{if(query.data)setDraft(query.data.schedule)},[query.data])
 const patch=(value:Partial<Schedule>)=>setDraft(previous=>previous?{...previous,...value}:previous)
 return <Card aria-label="Automatic backup scheduling"><h3 className="ui-section-title flex items-center gap-2"><Clock size={18} aria-hidden="true"/>Automatic backup scheduling</h3>
  <p className="ui-description">Queues a consistent backup for the next host restart. Editing and scheduled refresh pause until restart or cancellation. This does not restart the host or create an unattended online archive. Manual backups are preserved; retention applies only to successful scheduled archives.</p>
  {query.isLoading?<LoadingState/>:query.error?<ErrorState error={query.error} onRetry={()=>void query.refetch()}/>:draft&&<>
   <Checkbox disabled={!draft.enabled&&!query.data?.encryption_ready} checked={draft.enabled} onChange={event=>patch({enabled:event.target.checked})}>Enable scheduled backup requests (restart required)</Checkbox>
   <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
    <FormField label="Backup schedule type"><SettingsSelect value={draft.mode} onChange={event=>patch({mode:event.target.value as Schedule['mode']})}><option value="daily">Daily</option><option value="cron">Advanced cron</option></SettingsSelect></FormField>
    {draft.mode==='daily'?<FormField label="Backup daily time" description="24-hour time, HH:mm."><TimeInput24 label="Backup daily time" value={draft.time} onChange={time=>patch({time})}/></FormField>:<FormField label="Backup cron expression"><Input value={draft.cron} onChange={event=>patch({cron:event.target.value})}/></FormField>}
    <FormField label="Backup time zone" description="Local time, UTC or an installed IANA zone, for example Europe/Oslo."><Input value={draft.timezone} onChange={event=>patch({timezone:event.target.value})}/></FormField>

   </div>
   {!query.data?.encryption_ready&&<p className="ui-description">Verify a separately stored recovery copy above before enabling automatic backups.</p>}
   <p className="ui-description">Automatic backup retention defaults to 90 days and requires the existing retention approval. Manual and migration backups stay protected.</p>
   <Button disabled={busy} onClick={()=>{setBusy(true);setError('');void apiRequest('/api/backups/schedule','POST',{revision:query.data?.revision,schedule:draft}).then(()=>client.invalidateQueries({queryKey:['backup-schedule']})).catch(reason=>setError(reason instanceof Error?reason.message:'Schedule could not be saved.')).finally(()=>setBusy(false))}}><Save size={16} aria-hidden="true"/>{busy?'Saving…':'Save backup schedule'}</Button>
   <p className="ui-description">{query.data?.description}. Next requests: {query.data?.next_runs.length?query.data.next_runs.slice(0,3).map(value=>formatTimestamp(value)).join(' · '):'Disabled'}</p>
   <p className="ui-description">Last successful archive: {formatTimestamp(query.data?.last_success,'Never')} · Last failed archive: {formatTimestamp(query.data?.last_failure,'None')}{query.data?.last_outcome&&` · ${query.data.last_outcome}`}</p>
   {!!query.data?.attempts?.length&&<details><summary>Scheduled request history</summary><ul className="ui-description">{query.data.attempts.map((entry,index)=><li key={index}>{formatTimestamp(entry.at)} · {entry.status}</li>)}</ul></details>}
  </>}{error&&<p role="alert">{error}</p>}
 </Card>
}

export function BackupHistory({download,disabled}:{download:(id:string)=>Promise<void>;disabled:boolean}){
 const client=useQueryClient(),query=useQuery({queryKey:['backup-history'],queryFn:()=>apiRequest<History>('/api/backups/history'),refetchOnMount:'always'})
 const [busy,setBusy]=useState(''),[error,setError]=useState('')
 return <Card aria-label="Backup history"><h3 className="ui-section-title">Backup history</h3>
  {query.isLoading?<LoadingState/>:query.error?<ErrorState error={query.error} onRetry={()=>void query.refetch()}/>:<>
   <p className="ui-description">{query.data?.destination} · {((query.data?.storage_bytes||0)/1024/1024).toFixed(1)} MiB · {query.data?.total||0} operations. Showing the latest 200.</p>
   {!query.data?.items.length?<p className="ui-description">No retained backup operations yet.</p>:<div className="overflow-x-auto"><table className="data-table"><thead><tr>{['Created','Source','Status','Size','Verification','Actions'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{query.data.items.map(row=><tr key={row.id}><td>{formatTimestamp(row.created_at)}</td><td>{row.origin==='scheduled'?'Scheduled':'Manual'}</td><td><StatusBadge tone={row.verified?'success':row.status==='failed'?'error':'neutral'}>{row.status.replace(/_/g,' ')}</StatusBadge></td><td>{(row.size/1024/1024).toFixed(1)} MiB</td><td>{row.verified?'Verified':'Not available'}</td><td><div className="flex gap-2">
    <Button variant="ghost" disabled={disabled||query.isFetching||!!busy||!row.verified} onClick={()=>{setBusy(row.id);setError('');void download(row.id).catch(reason=>setError(reason instanceof Error?reason.message:'Download failed.')).finally(()=>setBusy(''))}}><Download size={16} aria-hidden="true"/>Download</Button>
    <Button variant="ghost" disabled={disabled||query.isFetching||!!busy||!['ready','failed','cancelled'].includes(row.status)} onClick={()=>{if(!window.confirm('Delete this backup archive? Application data and other backups are preserved.'))return;setBusy(row.id);setError('');void apiRequest(`/api/backups/${row.id}/delete`,'POST',{confirm:true}).then(()=>Promise.all([client.invalidateQueries({queryKey:['backup-history']}),client.invalidateQueries({queryKey:['application-backups']})])).catch(reason=>setError(reason instanceof Error?reason.message:'Backup could not be deleted.')).finally(()=>setBusy(''))}}><Trash2 size={16} aria-hidden="true"/>Delete</Button>
   </div></td></tr>)}</tbody></table></div>}
  </>}{error&&<p role="alert">{error}</p>}
 </Card>
}
