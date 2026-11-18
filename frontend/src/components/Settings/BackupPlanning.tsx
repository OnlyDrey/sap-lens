import {useEffect,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Clock,Download,Trash2,Save,ShieldCheck} from 'lucide-react'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {SettingsSelect} from './Controls'
import {Card,ErrorState,LoadingState,StatusBadge} from '@/components/Shared/Presentation'
import {formatTimestamp} from '@/lib/dateFormat'
import {TimeInput24} from '@/components/Shared/TimeInput24'
import {ActionMenu} from '@/components/Shared/ActionMenu'
import {Dialog} from '@/components/Shared/Dialog'

type Schedule={enabled:boolean;mode:'daily'|'weekly'|'cron';time:string;cron:string;timezone:string;keep:number;weekday?:number}
type Status={encryption_ready?:boolean;configuration_error?:string;requires_restart?:boolean;revision:number;schedule:Schedule;next_runs:string[];description:string;last_success:string|null;last_failure:string|null;last_outcome?:string;attempts?:{at:string;status:string}[]}
type History={items:{id:string;created_at:string;origin:string;status:string;size:number;verified:boolean}[];total:number;storage_bytes:number;destination:string}

export function BackupScheduling(){
 const client=useQueryClient(),query=useQuery({queryKey:['backup-schedule'],queryFn:()=>apiRequest<Status>('/api/backups/schedule'),refetchOnMount:'always'})
 const [draft,setDraft]=useState<Schedule|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 useEffect(()=>{if(query.data)setDraft(query.data.schedule)},[query.data])
 const patch=(value:Partial<Schedule>)=>{setMessage('');setDraft(previous=>previous?{...previous,...value}:previous)}
 return <Card aria-label="Automatic backup scheduling"><h3 className="ui-section-title flex items-center gap-2"><Clock size={18} aria-hidden="true"/>Automatic backup scheduling</h3>
  <p className="ui-description">Creates verified encrypted archives while the service runs. Database writes pause briefly for a consistent snapshot; no restart is required. Manual and migration backups are protected from automatic cleanup.</p>
  {query.isLoading?<LoadingState/>:query.error?<ErrorState error={query.error} onRetry={()=>void query.refetch()}/>:draft&&<>
   {query.data?.configuration_error&&<p role="alert">{query.data.configuration_error}</p>}
   <Checkbox disabled={!draft.enabled&&!query.data?.encryption_ready} checked={draft.enabled} onChange={event=>patch({enabled:event.target.checked})}>Enable automatic backups</Checkbox>
   <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
    <FormField label="Backup schedule type"><SettingsSelect value={draft.mode} onChange={event=>patch({mode:event.target.value as Schedule['mode'],weekday:event.target.value==='weekly'?(draft.weekday??1):undefined})}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="cron">Advanced cron</option></SettingsSelect></FormField>
    {draft.mode!=='cron'?<FormField label={draft.mode==='weekly'?'Backup weekly time':'Backup daily time'} description="24-hour time, HH:mm."><TimeInput24 label={draft.mode==='weekly'?'Backup weekly time':'Backup daily time'} value={draft.time} onChange={time=>patch({time})}/></FormField>:<FormField label="Backup cron expression"><Input value={draft.cron} onChange={event=>patch({cron:event.target.value})}/></FormField>}
    {draft.mode==='weekly'&&<FormField label="Backup day"><SettingsSelect value={draft.weekday??1} onChange={event=>patch({weekday:Number(event.target.value)})}>{['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'].map((day,index)=><option key={day} value={index}>{day}</option>)}</SettingsSelect></FormField>}
    <FormField label="Backup time zone" description="Local time, UTC or an installed IANA zone, for example Europe/Oslo."><Input value={draft.timezone} onChange={event=>patch({timezone:event.target.value})}/></FormField>

   </div>
   {!query.data?.encryption_ready&&<p className="ui-description">Verify a separately stored recovery copy above before enabling automatic backups.</p>}
   <p className="ui-description">Automatic backup retention defaults to 90 days and requires the existing retention approval. Manual and migration backups stay protected.</p>
   <Button disabled={busy} onClick={()=>{setBusy(true);setError('');setMessage('');void apiRequest<Status>('/api/backups/schedule','POST',{revision:query.data?.revision,schedule:draft}).then(async saved=>{await client.invalidateQueries({queryKey:['backup-schedule']});setMessage(saved.schedule.enabled?'Automatic backup schedule saved and enabled.':'Schedule saved. Automatic backups are disabled.')}).catch(reason=>setError(reason instanceof Error?reason.message:'Schedule could not be saved.')).finally(()=>setBusy(false))}}><Save size={16} aria-hidden="true"/>{busy?'Saving…':'Save backup schedule'}</Button>
   {message&&<p role="status">{message}</p>}
   <p className="ui-description">{query.data?.description}. Next execution (your device time): {query.data?.next_runs.length?query.data.next_runs.slice(0,3).map(value=>formatTimestamp(value)).join(' · '):'Disabled'}</p>
   <p className="ui-description">Last successful archive: {formatTimestamp(query.data?.last_success,'Never')} · Last failed archive: {formatTimestamp(query.data?.last_failure,'None')}{query.data?.last_outcome&&` · ${query.data.last_outcome}`}</p>
   {!!query.data?.attempts?.length&&<details><summary>Automatic backup history</summary><ul className="ui-description">{query.data.attempts.map((entry,index)=><li key={index}>{formatTimestamp(entry.at)} · {entry.status}</li>)}</ul></details>}
  </>}{error&&<p role="alert">{error}</p>}
 </Card>
}

export function BackupHistory({download,disabled}:{download:(id:string)=>Promise<void>;disabled:boolean}){
 const client=useQueryClient(),query=useQuery({queryKey:['backup-history'],queryFn:()=>apiRequest<History>('/api/backups/history'),refetchOnMount:'always'})
 const [busy,setBusy]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState(''),[secret,setSecret]=useState('')
 const [action,setAction]=useState<{kind:'verify'|'delete';id:string}|null>(null)
 const close=()=>{if(!busy){setAction(null);setSecret('');setError('')}}
 const run=async(id:string,work:()=>Promise<void>)=>{setBusy(id);setError('');setMessage('');try{await work()}catch(reason){setError(reason instanceof Error?reason.message:'The archive action failed.')}finally{setBusy('');setSecret('')}}
 return <Card aria-label="Backup history" className="gap-2 p-3"><h3 className="ui-section-title">Backup history</h3>
  {query.isLoading?<LoadingState/>:query.error?<ErrorState error={query.error} onRetry={()=>void query.refetch()}/>:<>
   <p className="ui-description">{query.data?.total||0} archives · {((query.data?.storage_bytes||0)/1024/1024).toFixed(1)} MiB · Latest 200 shown</p>
   {!query.data?.items.length?<p className="ui-description">No retained archives. Create a backup from Overview.</p>:<div className="min-w-0 overflow-x-auto"><table className="data-table"><thead><tr>{['Created','Type','Status','Size','Verification','Actions'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{query.data.items.map(row=><tr key={row.id}><td className="whitespace-nowrap">{formatTimestamp(row.created_at)}</td><td>{row.origin==='scheduled'?'Automatic':row.origin==='migration'?'Migration':'Manual'}</td><td><StatusBadge tone={row.verified?'success':row.status==='failed'?'error':'neutral'}>{row.status.replace(/_/g,' ')}</StatusBadge></td><td className="whitespace-nowrap">{(row.size/1024/1024).toFixed(1)} MiB</td><td>{row.verified?'Verified':'Unavailable'}</td><td>
    <ActionMenu label={`Actions for backup ${formatTimestamp(row.created_at)}`} disabled={disabled||query.isFetching||!!busy} items={[{id:'download',label:'Download',icon:<Download size={16} aria-hidden="true"/>,disabled:!row.verified},{id:'verify',label:'Verify archive',icon:<ShieldCheck size={16} aria-hidden="true"/>,disabled:!row.verified},{id:'delete',label:'Delete archive',icon:<Trash2 size={16} aria-hidden="true"/>,tone:'destructive',disabled:!['manual','scheduled'].includes(row.origin)||!['ready','failed','cancelled'].includes(row.status)}]} onSelect={kind=>{setError('');setMessage('');if(kind==='download')void run(row.id,()=>download(row.id));else setAction({kind:kind as 'verify'|'delete',id:row.id})}}/>
   </td></tr>)}</tbody></table></div>}
  </>}{message&&<p role="status">{message}</p>}{error&&!action&&<p role="alert">{error}</p>}
  {action&&<Dialog title={action.kind==='verify'?'Verify backup archive':'Delete backup archive'} size="narrow" onClose={close} footer={<><Button disabled={!!busy} onClick={close}>Cancel</Button><Button variant={action.kind==='delete'?'destructive':'primary'} loading={!!busy} onClick={()=>void run(action.id,async()=>{if(action.kind==='verify'){await apiRequest(`/api/backups/${encodeURIComponent(action.id)}/verify`,'POST',{secret});setMessage('Archive verified. Encryption, file hashes and SQLite integrity passed.')}else{await apiRequest(`/api/backups/${encodeURIComponent(action.id)}/delete`,'POST',{confirm:true});await Promise.all([client.invalidateQueries({queryKey:['backup-history']}),client.invalidateQueries({queryKey:['application-backups']})]);setMessage('Backup archive deleted. Application data and other archives were preserved.')}setAction(null)})}>{action.kind==='verify'?'Verify archive':'Delete archive'}</Button></>}>
   {action.kind==='verify'?<><p className="ui-description">Checks this archive without restoring or replacing data.</p><FormField label="Archive passphrase or recovery copy" description="Leave empty to use this host’s protected key."><Input type="password" autoComplete="off" maxLength={1024} value={secret} onChange={event=>setSecret(event.target.value)}/></FormField></>:<p className="ui-description">Permanently delete this archive? This cannot be undone. Application data and other backups are preserved.</p>}
   {error&&<p role="alert">{error}</p>}
  </Dialog>}
 </Card>
}
