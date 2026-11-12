import {useState} from 'react'
import {useReviewerIdentity,useSaveLocalReviewer} from '@/hooks/useReviewerIdentity'
import {Dialog} from '@/components/Shared/Dialog'
import {FormField,Input} from '@/components/Shared/Controls'
import {Button} from '@/components/Shared/Button'
export function LocalReviewerProfile({onClose}:{onClose:()=>void}){
 const identity=useReviewerIdentity(),save=useSaveLocalReviewer(),[name,setName]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 return <Dialog title="Local reviewer profile" onClose={()=>{if(!busy)onClose()}} footer={null}><form className="grid gap-3" onSubmit={event=>{event.preventDefault();if(busy||!identity.local)return;setBusy(true);void save(name??identity.displayName,identity.local.revision).then(onClose).catch(error=>setError(error instanceof Error?error.message:'Profile could not be saved.')).finally(()=>setBusy(false))}}>
 <p className="ui-description">A stable, self-reported identity for this passwordless Desktop installation. This is not a verified server account. Changes apply to future actions; historical identity snapshots are retained.</p>
 <FormField label="Reviewer display name"><Input value={name??identity.displayName} maxLength={120} required onChange={event=>setName(event.target.value)}/></FormField><Button type="submit" variant="primary" disabled={!(name??identity.displayName).trim()||!identity.local} loading={busy}>Save reviewer profile</Button>{identity.error&&<div role="alert"><p>{identity.error instanceof Error?identity.error.message:'Reviewer profile could not be loaded.'}</p><Button onClick={()=>void identity.retry()}>Retry profile</Button></div>}{error&&<p role="alert">{error}</p>}
 </form></Dialog>
}
