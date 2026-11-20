import {useState} from 'react'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Card,StatusBadge} from '@/components/Shared/Presentation'
import {FormField,Input} from '@/components/Shared/Controls'
export interface KeyProvider {configured:boolean;fingerprint?:string;escrow_verified:boolean}
export function BackupEncryption({provider,onChanged,reauthenticationRequired=false}:{provider?:KeyProvider;onChanged:()=>Promise<unknown>;reauthenticationRequired?:boolean}){
 const [key,setKey]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 const [password,setPassword]=useState('')
 const run=async(action:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await action();await onChanged()}catch(error){setError(error instanceof Error?error.message:'Recovery-key operation failed.')}finally{setBusy(false)}}
 return <Card aria-label="Backup encryption" className="gap-2 p-3"><details onToggle={event=>{if(!event.currentTarget.open){setKey('');setPassword('')}}}><summary className="flex cursor-pointer flex-wrap items-center gap-2 rounded-sm text-sm font-semibold focus-visible:outline focus-visible:outline-[length:var(--focus-width)] focus-visible:outline-focus focus-visible:[outline-offset:var(--focus-offset)]"><span>Recovery key details</span><StatusBadge tone={provider?.escrow_verified?'success':'warning'}>{provider?.escrow_verified?'Recovery copy verified':provider?.configured?'Recovery copy not verified':'Not configured'}</StatusBadge></summary><div className="mt-3 grid gap-3">
 <p className="ui-description">Keep recovery material separately from encrypted archives. Private TLS keys, active sessions and one-use credentials are excluded from backups.</p>
 <p role="status">{provider?.configured?`Host key configured · Fingerprint ${provider.fingerprint}`:'No protected host key configured. Configure one locally before creating backups.'}</p>
 <details><summary>Provision or export a recovery key locally</summary><ol className="pl-5 text-xs text-muted"><li>On the Windows server, open the release’s Service-Manager.ps1 in an elevated PowerShell session.</li><li>Check the selected data directory. Create initial key is available only when no key is configured.</li><li>Choose Export recovery copy and save it outside the application data directory. Store a separate protected copy off the server.</li><li>Return here and verify that separately stored copy. A browser cannot export the host’s private key.</li></ol></details>
 <details><summary>Verify a separately stored recovery copy</summary><div className="grid gap-3 mt-3">
 <FormField label="Recovery key copy"><Input type="file" accept=".key,text/plain" disabled={busy||!provider?.configured} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;void run(async()=>{if(file.size>96)throw Error('Select a AuthLens recovery key file.');setKey(await file.text())})}}/></FormField>
 <FormField label="Recovery key"><Input type="password" autoComplete="off" maxLength={96} value={key} onChange={event=>setKey(event.target.value)}/></FormField>
 {reauthenticationRequired&&<FormField label="Current administrator password" description="Required for this verification only; never stored in the browser."><Input type="password" autoComplete="current-password" maxLength={1024} value={password} onChange={event=>setPassword(event.target.value)}/></FormField>}
 <Button disabled={busy||!key.trim()||!provider?.configured||reauthenticationRequired&&!password} onClick={()=>void run(async()=>{try{const proof=reauthenticationRequired?await apiRequest<{code:string}>('/api/auth/backup-reauth','POST',{current_password:password}):null;await apiRequest('/api/backups/key/verify','POST',{recovery_key:key,...(proof?{reauth_code:proof.code}:{})});setKey('');setMessage('Recovery copy verified. Automatic backups may now be enabled.')}finally{setPassword('')}})}>Verify recovery copy</Button>
 </div></details>{message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
 </div></details></Card>
}
