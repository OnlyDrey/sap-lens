import {useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Archive,Download,RotateCcw} from 'lucide-react'
import {apiRequest,applicationToken} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {Card,ErrorState,LoadingState,StatusBadge,Toolbar} from '@/components/Shared/Presentation'

type Operation={id?:string;kind?:string;status:string;message?:string;archive_sha256?:string;preview?:{source_mode:string;source_version:string;created_at:string;files:number;snapshots:number;categories:string[];warning:string}}

export function BackupRestore(){
 const client=useQueryClient(),status=useQuery({queryKey:['application-backups'],queryFn:()=>apiRequest<Operation>('/api/backups')})
 const [preview,setPreview]=useState<Operation|null>(null),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const run=async(action:()=>Promise<unknown>)=>{setBusy(true);setError('');try{await action();await client.invalidateQueries({queryKey:['application-backups']})}catch(reason){setError(reason instanceof Error?reason.message:'Backup operation failed. Existing data is preserved.')}finally{setBusy(false)}}
 const current=status.data,pending=current?.status==='pending'
 const download=async(kind:string)=>{if(!current?.id)return
  if(window.pywebview){if(!window.pywebview.api.save_application_backup)throw Error('Update the desktop application for backup downloads.');await window.pywebview.api.save_application_backup(applicationToken(),current.id,kind);return}
  const response=await fetch(`/api/backups/${current.id}/download?kind=${kind}`,{headers:{'X-SAP-Lens':applicationToken()},cache:'no-store'})
  if(!response.ok)throw Error('Backup download is unavailable. Check the operation status.')
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`SAP-Lens-${kind}-${current.id}.tar.gz`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }
 return <section aria-label="Application backup and restore" className="grid min-w-0 gap-4">
  <p className="ui-description">Transfer application datasets, decisions, history, review periods and saved filters. Full replacement, not a merge. Archives contain sensitive personal and access data and are <strong>not encrypted</strong>. Store them securely.</p>
  {status.isLoading?<LoadingState/>:status.error?<ErrorState error={status.error} onRetry={()=>void status.refetch()}/>:<>
   <Card><Toolbar><StatusBadge>{current?.status==='idle'?'Ready':current?.status}</StatusBadge><Button variant="ghost" disabled={busy} onClick={()=>void status.refetch()}>Check status</Button></Toolbar>{current?.message&&<p role="status">{current.message}</p>}
    {pending&&<><p className="ui-description">Editing and scheduled refresh are paused. Desktop: explicitly Exit SAP Lens, then reopen it. Server: ask the administrator to restart the service/container. Closing to the tray does not restart the application.</p><Button variant="secondary" disabled={busy} onClick={()=>void run(()=>apiRequest('/api/backups/cancel','POST'))}>Cancel pending operation</Button></>}
    {current?.status==='completed'&&current.kind==='backup'&&<Button disabled={busy} onClick={()=>void run(()=>download('backup'))}><Download size={16}/>Download backup</Button>}
    {current?.kind==='restore'&&['completed','failed'].includes(current.status)&&<Button variant="secondary" disabled={busy} onClick={()=>void run(()=>download('destination-before-restore'))}><Download size={16}/>Download destination recovery backup</Button>}
   </Card>
   <Card><h3 className="ui-section-title">Create application backup</h3><p className="ui-description">A restart creates a consistent archive before imports or edits begin. Security credentials, certificates, logs and runtime tokens are excluded. No active data is changed.</p><Button disabled={busy||pending} onClick={()=>void run(()=>apiRequest('/api/backups/create','POST'))}><Archive size={16}/>Prepare backup on restart</Button></Card>
   <Card><h3 className="ui-section-title">Restore application data</h3><p className="ui-description">Upload a SAP Lens .tar.gz backup (up to 256 MiB compressed). Validation and preview do not replace data. Confirmation schedules a restart handoff with an automatic destination backup. Larger archives require stopped host maintenance.</p>
    <FormField label="Application backup archive"><Input type="file" accept=".tar.gz,application/gzip" disabled={busy||pending} onChange={event=>{const file=event.target.files?.[0];event.target.value='';setPreview(null);setConfirmed(false);if(!file)return;void run(async()=>{if(file.size>256*1024*1024)throw Error('Backup exceeds the 256 MiB Settings upload limit.');const response=await fetch('/api/backups/upload',{method:'POST',headers:{'X-SAP-Lens':applicationToken(),'Content-Type':'application/gzip'},body:file});const result=await response.json();if(!response.ok)throw Error(result.detail||'Archive validation failed.');setPreview(result)})}}/></FormField>
    {preview?.preview&&<div className="grid gap-3"><h4>Validated archive preview</h4><dl className="grid grid-cols-1 gap-2 sm:grid-cols-2"><div><dt>Source</dt><dd>{preview.preview.source_mode} · {preview.preview.source_version}</dd></div><div><dt>Created</dt><dd>{new Intl.DateTimeFormat('nb-NO',{dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(preview.preview.created_at))}</dd></div><div><dt>Included data</dt><dd>{preview.preview.files} files · {preview.preview.snapshots} snapshots</dd></div></dl><p className="ui-description break-words">{preview.preview.categories.join(', ')}</p><p className="ui-description">{preview.preview.warning}</p><Checkbox checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}>I confirm full replacement after restart. I understand that these histories will not be merged.</Checkbox><Button disabled={!confirmed||busy||pending} onClick={()=>void run(async()=>{await apiRequest('/api/backups/restore','POST',{id:preview.id,sha256:preview.archive_sha256,confirm:true});setPreview(null);setConfirmed(false)})}><RotateCcw size={16}/>Confirm restore on restart</Button></div>}
   </Card>
  </>}
  {busy&&<p role="status">Validating or preparing operation…</p>}{error&&<p role="alert">{error}</p>}
 </section>
}
