import {BackupHistory,BackupScheduling} from './BackupPlanning'
import {BackupEncryption,type KeyProvider} from './BackupEncryption'
import {StorageUpgrade} from './StorageUpgrade'
import {DataRetention} from './DataRetention'
import {useRef,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Archive,CalendarClock,DatabaseBackup,Download,History,RotateCcw,RefreshCw} from 'lucide-react'
import {ContentTabs} from '@/components/Shared/Navigation'
import {apiRequest,applicationHeaders} from '@/api/client'
import {formatTimestamp} from '@/lib/dateFormat'
import {backupDownloadFilename} from '@/lib/backupDownload'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {Card,ErrorState,LoadingState,StatusBadge,Toolbar} from '@/components/Shared/Presentation'

type Operation={id?:string;kind?:string;status:string;key_provider?:KeyProvider;reauthentication_required?:boolean;recovery_required?:boolean;completed_at?:string;message?:string;archive_sha256?:string;preview?:{source_mode:string;source_version:string;created_at:string;files:number;snapshots:number;categories:string[];warning:string;encrypted?:boolean;accounts?:{accounts:number;administrators:number}|null}}
const encodedSecret=(value:string)=>btoa([...new TextEncoder().encode(value)].map(byte=>String.fromCharCode(byte)).join(''))
const cancelledUpload=(cause:unknown)=>Object.assign(new Error('Archive validation was cancelled or timed out. No restore was confirmed.'),{cause})
export function BackupRestore(){
 const client=useQueryClient(),status=useQuery({queryKey:['application-backups'],queryFn:()=>apiRequest<Operation>('/api/backups'),refetchOnMount:'always',refetchOnWindowFocus:'always'})
 const [preview,setPreview]=useState<Operation|null>(null),[confirmed,setConfirmed]=useState(false),[accountsConfirmed,setAccountsConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[filename,setFilename]=useState(''),[restoreFeedback,setRestoreFeedback]=useState('')
 const [passphrase,setPassphrase]=useState(''),[repeated,setRepeated]=useState(''),[secret,setSecret]=useState('')
 const uploadController=useRef<AbortController|null>(null)
 // Preserve non-secret restore previews across tabs; clear entered secrets when leaving the tab.
 const [tab,setTab]=useState('overview')
 const [creating,setCreating]=useState(false)
 const history=useQuery({queryKey:['backup-history'],queryFn:()=>apiRequest<{items:{status:string;verified:boolean;created_at:string}[]}>('/api/backups/history'),enabled:tab==='overview'})
 const schedule=useQuery({queryKey:['backup-schedule'],queryFn:()=>apiRequest<{schedule:{enabled:boolean};configuration_error?:string;last_success?:string;last_failure?:string}>('/api/backups/schedule'),enabled:tab==='overview'})
 const [errorTab,setErrorTab]=useState('overview')
 const run=async(action:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await action();await Promise.all([client.invalidateQueries({queryKey:['application-backups']}),client.invalidateQueries({queryKey:['backup-history']})])}catch(reason){setErrorTab(tab);setError(reason instanceof Error?reason.message:'Backup operation failed. Existing data is preserved.')}finally{setBusy(false)}}
 const current=status.data,pending=['pending','waiting_for_restart','preparing','creating'].includes(current?.status||'')||Boolean(current?.recovery_required)
 const labels:Record<string,string>={idle:'Idle',pending:'Waiting for restart',waiting_for_restart:'Waiting for restart',preparing:'Preparing',creating:'Creating',ready:'Ready',completed:'Completed',failed:'Failed',cancelled:'Cancelled'}
 const lastBackup=history.data?.items.find(item=>item.verified)?.created_at||(current?.kind==='backup'&&current.archive_sha256?current.completed_at:undefined)
 const download=async(kind:string,identity=current?.id)=>{if(!identity)return
  const response=await fetch(`/api/backups/${encodeURIComponent(identity)}/download?kind=${encodeURIComponent(kind)}`,{headers:applicationHeaders(),cache:'no-store'})
  if(!response.ok){const problem=await response.json().catch(()=>null);throw Error(typeof problem?.detail==='string'?problem.detail:'Backup download is unavailable. Check the operation status.')}
  const name=backupDownloadFilename(response.headers.get('Content-Disposition'),kind,identity)
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }
 const upload=async(file:File)=>{
  setPreview(null);setConfirmed(false);setAccountsConfirmed(false);setFilename('');setRestoreFeedback('')
  if(!/\.slbak$/i.test(file.name)||!file.size)throw Error('Choose a non-empty encrypted AuthLens .slbak backup.')
  if(file.size>256*1024*1024)throw Error('Backup exceeds the 256 MiB Settings upload limit.')
  const controller=new AbortController();uploadController.current=controller;const timer=setTimeout(()=>controller.abort(),60000)
  try{
   const response=await fetch('/api/backups/upload',{method:'POST',signal:controller.signal,headers:{...applicationHeaders(),'Content-Type':'application/octet-stream','X-SAP-Lens-Backup-Secret':encodedSecret(secret)},body:file})
   const result=await response.json();if(!response.ok)throw Error(result.detail||'Archive validation failed. No data was replaced.')
   setPreview(result);setFilename(file.name);setSecret('')
  }catch(reason){if(controller.signal.aborted)throw cancelledUpload(reason);throw reason}finally{clearTimeout(timer);uploadController.current=null}
 }
 return <section aria-label="Application backup and restore" className="grid min-w-0 gap-4">
  {status.isLoading?<LoadingState/>:status.error?<ErrorState error={status.error} onRetry={()=>void status.refetch()}/>:<>
   <div className="space-y-2" aria-label="Backup operation status"><Toolbar><span className="text-xs text-muted">{current?.kind?`Last recorded ${current.kind} operation`:'Operation status'}</span><StatusBadge>{status.isFetching?'Checking status…':labels[current?.status||'idle']||'Unknown'}</StatusBadge><Button variant="ghost" disabled={busy} onClick={()=>void status.refetch()}><RefreshCw size={16} aria-hidden="true"/>Check status</Button></Toolbar>{current?.message&&<p role="status">{current.message}</p>}{current?.completed_at&&<p className="ui-description">Last operation: {formatTimestamp(current.completed_at)}</p>}
    {pending&&<><p className="ui-description">Editing and scheduled refresh are paused. Desktop: choose Exit AuthLens from the tray, then launch again; closing a window may keep the backend running. Server: an administrator restarts the Windows service or systemd unit. A browser cannot restart the host. Return here after reconnecting; Ready enables Download backup.</p><Button disabled={busy||Boolean(current?.recovery_required)||['preparing','creating'].includes(current?.status||'')} onClick={()=>void run(()=>apiRequest('/api/backups/cancel','POST'))}>Cancel pending operation</Button></>}
    {tab==='overview'&&['ready','completed'].includes(current?.status||'')&&current?.kind==='backup'&&<Button disabled={busy||status.isFetching} onClick={()=>void run(()=>download('backup'))}><Download size={16} aria-hidden="true"/>Download backup</Button>}
    {tab==='overview'&&current?.kind==='restore'&&['completed','failed'].includes(current.status)&&<Button disabled={busy} onClick={()=>void run(()=>download('destination-before-restore'))}><Download size={16} aria-hidden="true"/>Download destination recovery backup</Button>}
   </div>
   <ContentTabs label="Backup and restore sections" value={tab} onChange={next=>{setTab(next);setPassphrase('');setRepeated('');setSecret('');setError('')}} items={[{value:'overview',label:'Overview',icon:<DatabaseBackup size={16} aria-hidden="true"/>},{value:'history',label:'Backup History',icon:<History size={16} aria-hidden="true"/>},{value:'scheduling',label:'Scheduling',icon:<CalendarClock size={16} aria-hidden="true"/>},{value:'retention',label:'Retention',icon:<Archive size={16} aria-hidden="true"/>}]}>
   {tab==='overview'&&<>
   <dl aria-label="Backup overview" className="grid gap-3 rounded-md border border-line bg-surface p-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
    <div><dt className="text-muted">Last successful backup</dt><dd className="m-0 mt-1 font-medium">{history.isLoading?'Checking…':history.error?'Unavailable':formatTimestamp(lastBackup,'None yet')}</dd></div>
    <div><dt className="text-muted">Backup health</dt><dd className="m-0 mt-1"><StatusBadge tone={history.data?.items[0]?.verified?'success':'warning'}>{history.error?'History unavailable':history.data?.items[0]?.verified?'Verified archive':history.data?.items.length?'Latest archive unavailable':'No verified archive yet'}</StatusBadge></dd></div>
    <div><dt className="text-muted">Recovery key</dt><dd className="m-0 mt-1 font-medium">{current?.key_provider?.escrow_verified?'Recovery copy verified':current?.key_provider?.configured?'Recovery copy needed':'Not configured'}</dd></div>
    <div><dt className="text-muted">Scheduling</dt><dd className="m-0 mt-1 font-medium">{schedule.isLoading?'Checking…':schedule.error?'Unavailable':schedule.data?.configuration_error?'Needs attention':schedule.data?.schedule.enabled?'Enabled':'Disabled'}</dd></div>
   </dl>
   <Card className="gap-2 p-3"><h3 className="ui-section-title flex items-center gap-2"><DatabaseBackup size={18} aria-hidden="true"/>Create application backup</h3><p className="ui-description">Create a verified encrypted archive while AuthLens keeps running. No restart is needed.</p>
    <details><summary>Use a separate archive passphrase (optional)</summary><div className="grid gap-3 mt-3"><FormField label="Backup passphrase"><Input type="password" autoComplete="new-password" minLength={12} maxLength={1024} value={passphrase} onChange={event=>setPassphrase(event.target.value)}/></FormField><FormField label="Repeat backup passphrase"><Input type="password" autoComplete="new-password" maxLength={1024} value={repeated} onChange={event=>setRepeated(event.target.value)}/></FormField><p className="ui-description">Without a separate passphrase, the escrowed host recovery key decrypts this archive. Keep either secret separately; AuthLens cannot recover a forgotten passphrase.</p></div></details>
    <Button variant="primary" className="justify-self-start" loading={creating} disabled={busy||pending||!current?.key_provider?.configured||!!passphrase&&(passphrase.length<12||passphrase!==repeated)} onClick={()=>{setCreating(true);void run(async()=>{await apiRequest('/api/backups/create','POST',{passphrase});setPassphrase('');setRepeated('')}).finally(()=>setCreating(false))}}><DatabaseBackup size={16} aria-hidden="true"/>Create backup</Button>
   </Card>
   <BackupEncryption provider={current?.key_provider} reauthenticationRequired={current?.reauthentication_required} onChanged={()=>Promise.all([status.refetch(),client.invalidateQueries({queryKey:['backup-schedule']})])}/>
   <Card className="gap-2 p-3"><details><summary className="flex cursor-pointer items-center gap-2 rounded-sm text-sm font-semibold focus-visible:outline focus-visible:outline-[length:var(--focus-width)] focus-visible:outline-focus focus-visible:[outline-offset:var(--focus-offset)]">Restore application data</summary><div className="mt-3 grid gap-3"><p className="ui-description">Validate an encrypted archive (up to 256 MiB) before confirming full replacement on restart. Confirmation first creates a protected destination recovery backup.</p>
    <FormField label="Restore passphrase or exported recovery key" description="Leave empty only when this host's configured key matches the archive."><Input type="password" autoComplete="off" maxLength={1024} value={secret} onChange={event=>setSecret(event.target.value)}/></FormField>
    <FormField label="Application backup archive"><Input type="file" accept=".slbak,application/octet-stream" disabled={busy||pending} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)void run(()=>upload(file))}}/></FormField>
    {restoreFeedback&&<p role="status">{restoreFeedback}</p>}{filename&&<p className="ui-description break-words">Validated upload staged on server: {filename}</p>}
    {preview?.preview&&<div className="grid gap-3"><h4>Validated archive preview</h4><Button variant="ghost" disabled={busy||pending} onClick={()=>void run(async()=>{await apiRequest(`/api/backups/uploads/${preview.id}/cancel`,'POST');setPreview(null);setFilename('');setConfirmed(false);setRestoreFeedback('Restore preview cancelled. No application data was changed.')})}>Cancel restore preview</Button><dl className="grid grid-cols-1 gap-2 sm:grid-cols-2"><div><dt>Source</dt><dd>{preview.preview.source_mode} · {preview.preview.source_version}</dd></div><div><dt>Created</dt><dd>{formatTimestamp(preview.preview.created_at)}</dd></div><div><dt>Included data</dt><dd>{preview.preview.files} files · {preview.preview.snapshots} snapshots</dd></div><div><dt>Protection</dt><dd>{preview.preview.encrypted?'Authenticated encryption':'Legacy unencrypted import'}</dd></div>{preview.preview.accounts&&<div><dt>Accounts to restore</dt><dd>{preview.preview.accounts.accounts} accounts · {preview.preview.accounts.administrators} administrators</dd></div>}</dl><p className="ui-description break-words">{preview.preview.categories.join(', ')}</p><p className="ui-description">{preview.preview.warning}</p>
     <Checkbox checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}>I confirm full replacement after restart. I understand that these histories will not be merged.</Checkbox>
     {preview.preview.accounts&&<Checkbox checked={accountsConfirmed} onChange={event=>setAccountsConfirmed(event.target.checked)}>I acknowledge account/password rollback and sign-out of all active sessions.</Checkbox>}
     <Button disabled={!confirmed||!!preview.preview.accounts&&!accountsConfirmed||busy||pending} onClick={()=>void run(async()=>{await apiRequest('/api/backups/restore','POST',{id:preview.id,sha256:preview.archive_sha256,confirm:true,confirm_accounts:accountsConfirmed});setPreview(null);setFilename('');setConfirmed(false);setAccountsConfirmed(false)})}><RotateCcw size={16} aria-hidden="true"/>Confirm restore on restart</Button>
    </div>}
   </div></details></Card>
   <StorageUpgrade/>
   </>}
   {tab==='history'&&<BackupHistory disabled={busy||pending} download={identity=>download('backup',identity)}/>}
   {tab==='scheduling'&&<BackupScheduling/>}
   {tab==='retention'&&<DataRetention/>}
   </ContentTabs>
  </>}
  {busy&&<div role="status"><LoadingState>{uploadController.current?'Uploading and validating archive…':'Preparing operation…'}</LoadingState>{uploadController.current&&<Button variant="ghost" onClick={()=>uploadController.current?.abort()}>Cancel validation</Button>}</div>}{error&&errorTab===tab&&<p role="alert">{error}</p>}
 </section>
}
