import {useState} from 'react'
import {apiRequest,applicationToken} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Card,Toolbar} from '@/components/Shared/Presentation'
import {FormField,Input} from '@/components/Shared/Controls'
export interface KeyProvider {configured:boolean;fingerprint?:string;escrow_verified:boolean}
export function BackupEncryption({provider,onChanged}:{provider?:KeyProvider;onChanged:()=>Promise<unknown>}){
 const [key,setKey]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 const run=async(action:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await action();await onChanged()}catch(error){setError(error instanceof Error?error.message:'Recovery-key operation failed.')}finally{setBusy(false)}}
 const native=window.pywebview?.api.configure_backup_key
 return <Card aria-label="Backup encryption"><h3 className="ui-section-title">Backup encryption &amp; recovery key</h3>
 <p className="ui-description">AES-256-GCM protects portable backups, including account password hashes and SAP data. Keep the recovery key or passphrase separately from archives. Active sessions, private TLS keys and service credentials are excluded.</p>
 <p role="status">{provider?.configured?`Protected host key configured · ${provider.fingerprint} · ${provider.escrow_verified?'Recovery copy verified':'Recovery copy not verified'}`:'No protected host key configured. Configure one locally before creating backups.'}</p>
 {native?<Toolbar>{(['create','select','export'] as const).map(action=><Button key={action} disabled={busy||action==='export'&&!provider?.configured} onClick={()=>void run(async()=>{if(await native(applicationToken(),action))setMessage('Local key operation completed. Verify your separately stored recovery copy below.')})}>{action==='create'?'Create recovery key':action==='select'?'Use existing key':'Export recovery copy'}</Button>)}</Toolbar>:<p className="ui-description">Server operator: use Service Manager → Export backup recovery key, or the documented local maintenance key commands. Browser users never select server filesystem paths.</p>}
 <details><summary>Verify a separately stored recovery copy</summary><div className="grid gap-3 mt-3">
 <FormField label="Recovery key copy"><Input type="file" accept=".key,text/plain" disabled={busy||!provider?.configured} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;void run(async()=>{if(file.size>96)throw Error('Select a SAP Lens recovery key file.');setKey(await file.text())})}}/></FormField>
 <FormField label="Recovery key"><Input type="password" autoComplete="off" maxLength={96} value={key} onChange={event=>setKey(event.target.value)}/></FormField><Button disabled={busy||!key.trim()||!provider?.configured} onClick={()=>void run(async()=>{await apiRequest('/api/backups/key/verify','POST',{recovery_key:key});setKey('');setMessage('Recovery copy verified. Automatic backups may now be enabled.')})}>Verify recovery copy</Button>
 </div></details>{message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
 </Card>
}
