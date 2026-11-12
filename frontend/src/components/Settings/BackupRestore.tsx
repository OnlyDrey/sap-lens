import {BackupHistory,BackupScheduling} from './BackupPlanning'
import {BackupEncryption,type KeyProvider} from './BackupEncryption'
import {StorageUpgrade} from './StorageUpgrade'
import {DataRetention} from './DataRetention'
import {useRef,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {DatabaseBackup,Download,RotateCcw,RefreshCw,FileUp} from 'lucide-react'
import {apiRequest,applicationToken,applicationHeaders} from '@/api/client'
import {formatTimestamp} from '@/lib/dateFormat'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {Card,ErrorState,LoadingState,StatusBadge,Toolbar} from '@/components/Shared/Presentation'

type Operation={id?:string;kind?:string;status:string;key_provider?:KeyProvider;recovery_required?:boolean;completed_at?:string;message?:string;archive_sha256?:string;preview?:{source_mode:string;source_version:string;created_at:string;files:number;snapshots:number;categories:string[];warning:string;encrypted?:boolean;accounts?:{accounts:number;administrators:number}|null}}
const encodedSecret=(value:string)=>btoa([...new TextEncoder().encode(value)].map(byte=>String.fromCharCode(byte)).join(''))
export function BackupRestore(){
 const client=useQueryClient(),status=useQuery({queryKey:['application-backups'],queryFn:()=>apiRequest<Operation>('/api/backups'),refetchOnMount:'always',refetchOnWindowFocus:'always'})
 const [preview,setPreview]=useState<Operation|null>(null),[confirmed,setConfirmed]=useState(false),[accountsConfirmed,setAccountsConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[filename,setFilename]=useState(''),[restoreFeedback,setRestoreFeedback]=useState('')
 const [passphrase,setPassphrase]=useState(''),[repeated,setRepeated]=useState(''),[secret,setSecret]=useState(''),[legacy,setLegacy]=useState(false)
 const uploadController=useRef<AbortController|null>(null)
 const run=async(action:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await action();await Promise.all([client.invalidateQueries({queryKey:['application-backups']}),client.invalidateQueries({queryKey:['backup-history']})])}catch(reason){setError(reason instanceof Error?reason.message:'Backup operation failed. Existing data is preserved.')}finally{setBusy(false)}}
 const current=status.data,pending=['pending','waiting_for_restart','preparing','creating'].includes(current?.status||'')||Boolean(current?.recovery_required)
 const labels:Record<string,string>={idle:'Idle',pending:'Waiting for restart',waiting_for_restart:'Waiting for restart',preparing:'Preparing',creating:'Creating',ready:'Ready',completed:'Completed',failed:'Failed',cancelled:'Cancelled'}
 const download=async(kind:string,identity=current?.id)=>{if(!identity)return
  if(window.pywebview){if(!window.pywebview.api.save_application_backup)throw Error('Update the desktop application for backup downloads.');await window.pywebview.api.save_application_backup(applicationToken(),identity,kind);return}
  const response=await fetch(`/api/backups/${identity}/download?kind=${kind}`,{headers:applicationHeaders(),cache:'no-store'})
  if(!response.ok)throw Error('Backup download is unavailable. Check the operation status.')
  const name=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]
  if(!name||!/^SAP-Lens-(backup|destination-before-restore)-[a-f0-9]{32}\.(slbak|tar\.gz)$/.test(name))throw Error('Invalid backup filename.')
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }
 const upload=async(file:File)=>{
  setPreview(null);setConfirmed(false);setAccountsConfirmed(false);setFilename('');setRestoreFeedback('')
  if(!/\.(slbak|tar\.gz)$/i.test(file.name)||!file.size)throw Error('Choose a non-empty SAP Lens .slbak backup or acknowledged legacy .tar.gz archive.')
  if(file.size>256*1024*1024)throw Error('Backup exceeds the 256 MiB Settings upload limit.')
  const controller=new AbortController();uploadController.current=controller;const timer=setTimeout(()=>controller.abort(),60000)
  try{
   const response=await fetch('/api/backups/upload',{method:'POST',signal:controller.signal,headers:{...applicationHeaders(),'Content-Type':'application/octet-stream','X-SAP-Lens-Backup-Secret':encodedSecret(secret),'X-SAP-Lens-Allow-Legacy':legacy?'1':'0'},body:file})
   const result=await response.json();if(!response.ok)throw Error(result.detail||'Archive validation failed. No data was replaced.')
   setPreview(result);setFilename(file.name);setSecret('')
  }catch(reason){if(controller.signal.aborted)throw Error('Archive validation was cancelled or timed out. No restore was confirmed.',{cause:reason});throw reason}finally{clearTimeout(timer);uploadController.current=null}
 }
 return <section aria-label="Application backup and restore" className="grid min-w-0 gap-4">
  <StorageUpgrade/><DataRetention/>
  {status.isLoading?<LoadingState/>:status.error?<ErrorState error={status.error} onRetry={()=>void status.refetch()}/>:<>
   <div className="space-y-2" aria-label="Backup operation status"><Toolbar><span className="text-xs text-muted">{current?.kind?`Last recorded ${current.kind} operation`:'Operation status'}</span><StatusBadge>{status.isFetching?'Checking status…':labels[current?.status||'idle']||'Unknown'}</StatusBadge><Button variant="ghost" disabled={busy} onClick={()=>void status.refetch()}><RefreshCw size={16} aria-hidden="true"/>Check status</Button></Toolbar>{current?.message&&<p role="status">{current.message}</p>}{current?.completed_at&&<p className="ui-description">Last operation: {formatTimestamp(current.completed_at)}</p>}
    {pending&&<><p className="ui-description">Editing and scheduled refresh are paused. Desktop: choose Exit SAP Lens from the tray, then launch again; closing a window may keep the backend running. Server: an administrator restarts the Windows service, systemd unit or Docker container. A browser cannot restart the host. Return here after reconnecting; Ready enables Download backup.</p><Button disabled={busy||Boolean(current?.recovery_required)||['preparing','creating'].includes(current?.status||'')} onClick={()=>void run(()=>apiRequest('/api/backups/cancel','POST'))}>Cancel pending operation</Button></>}
    {['ready','completed'].includes(current?.status||'')&&current?.kind==='backup'&&<Button disabled={busy||status.isFetching} onClick={()=>void run(()=>download('backup'))}><Download size={16} aria-hidden="true"/>Download backup</Button>}
    {current?.kind==='restore'&&['completed','failed'].includes(current.status)&&<Button disabled={busy} onClick={()=>void run(()=>download('destination-before-restore'))}><Download size={16} aria-hidden="true"/>Download destination recovery backup</Button>}
   </div>
   <BackupEncryption provider={current?.key_provider} onChanged={()=>Promise.all([status.refetch(),client.invalidateQueries({queryKey:['backup-schedule']})])}/>
   <Card><h3 className="ui-section-title flex items-center gap-2"><DatabaseBackup size={18} aria-hidden="true"/>Create application backup</h3><p className="ui-description">A stopped snapshot keeps file-based review history and database accounts consistent. Prepare, restart the host, then download the encrypted archive. Branding, settings and account verifiers are included; active sessions and host secrets are excluded.</p>
    <details><summary>Use a separate archive passphrase (optional)</summary><div className="grid gap-3 mt-3"><FormField label="Backup passphrase"><Input type="password" autoComplete="new-password" minLength={12} maxLength={1024} value={passphrase} onChange={event=>setPassphrase(event.target.value)}/></FormField><FormField label="Repeat backup passphrase"><Input type="password" autoComplete="new-password" maxLength={1024} value={repeated} onChange={event=>setRepeated(event.target.value)}/></FormField><p className="ui-description">Without a separate passphrase, the escrowed host recovery key decrypts this archive. Keep either secret separately; SAP Lens cannot recover a forgotten passphrase.</p></div></details>
    <Button disabled={busy||pending||!current?.key_provider?.configured||!!passphrase&&(passphrase.length<12||passphrase!==repeated)} onClick={()=>void run(async()=>{await apiRequest('/api/backups/create','POST',{passphrase});setPassphrase('');setRepeated('')})}><DatabaseBackup size={16} aria-hidden="true"/>Create backup (restart required)</Button>
   </Card>
   <BackupScheduling/>
   <Card><h3 className="ui-section-title flex items-center gap-2"><FileUp size={18} aria-hidden="true"/>Restore application data</h3><p className="ui-description">Upload an encrypted .slbak archive (up to 256 MiB). Validation and preview do not replace data. Confirmation schedules a restart handoff with an encrypted destination recovery backup.</p>
    <FormField label="Restore passphrase or exported recovery key" description="Leave empty only when this host's configured key matches the archive."><Input type="password" autoComplete="off" maxLength={1024} value={secret} onChange={event=>setSecret(event.target.value)}/></FormField>
    <Checkbox checked={legacy} onChange={event=>setLegacy(event.target.checked)}>Allow a legacy unencrypted archive import; destination accounts will remain unchanged.</Checkbox>
    <FormField label="Application backup archive"><Input type="file" accept=".slbak,.tar.gz,application/octet-stream,application/gzip" disabled={busy||pending} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)void run(()=>upload(file))}}/></FormField>
    {restoreFeedback&&<p role="status">{restoreFeedback}</p>}{filename&&<p className="ui-description break-words">Validated upload staged on server: {filename}</p>}
    {preview?.preview&&<div className="grid gap-3"><h4>Validated archive preview</h4><Button variant="ghost" disabled={busy||pending} onClick={()=>void run(async()=>{await apiRequest(`/api/backups/uploads/${preview.id}/cancel`,'POST');setPreview(null);setFilename('');setConfirmed(false);setRestoreFeedback('Restore preview cancelled. No application data was changed.')})}>Cancel restore preview</Button><dl className="grid grid-cols-1 gap-2 sm:grid-cols-2"><div><dt>Source</dt><dd>{preview.preview.source_mode} · {preview.preview.source_version}</dd></div><div><dt>Created</dt><dd>{formatTimestamp(preview.preview.created_at)}</dd></div><div><dt>Included data</dt><dd>{preview.preview.files} files · {preview.preview.snapshots} snapshots</dd></div><div><dt>Protection</dt><dd>{preview.preview.encrypted?'Authenticated encryption':'Legacy unencrypted import'}</dd></div>{preview.preview.accounts&&<div><dt>Accounts to restore</dt><dd>{preview.preview.accounts.accounts} accounts · {preview.preview.accounts.administrators} administrators</dd></div>}</dl><p className="ui-description break-words">{preview.preview.categories.join(', ')}</p><p className="ui-description">{preview.preview.warning}</p>
     <Checkbox checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}>I confirm full replacement after restart. I understand that these histories will not be merged.</Checkbox>
     {preview.preview.accounts&&<Checkbox checked={accountsConfirmed} onChange={event=>setAccountsConfirmed(event.target.checked)}>I acknowledge account/password rollback and sign-out of all active sessions.</Checkbox>}
     <Button disabled={!confirmed||!!preview.preview.accounts&&!accountsConfirmed||busy||pending} onClick={()=>void run(async()=>{await apiRequest('/api/backups/restore','POST',{id:preview.id,sha256:preview.archive_sha256,confirm:true,confirm_accounts:accountsConfirmed});setPreview(null);setFilename('');setConfirmed(false);setAccountsConfirmed(false)})}><RotateCcw size={16} aria-hidden="true"/>Confirm restore on restart</Button>
    </div>}
   </Card>
   <BackupHistory disabled={busy||pending} download={identity=>download('backup',identity)}/>
  </>}
  {busy&&<div role="status"><LoadingState>{uploadController.current?'Uploading and validating archive…':'Preparing operation…'}</LoadingState>{uploadController.current&&<Button variant="ghost" onClick={()=>uploadController.current?.abort()}>Cancel validation</Button>}</div>}{error&&<p role="alert">{error}</p>}
 </section>
}
