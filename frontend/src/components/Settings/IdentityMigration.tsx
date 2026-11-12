import {useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {ConfirmDialog} from '@/components/Shared/ConfirmDialog'
import {ErrorState,StatusBadge} from '@/components/Shared/Presentation'
import {formatTimestamp} from '@/lib/dateFormat'
type Migration={id:string;status:string;created:string;source:string;backup_available:boolean}
export function IdentityMigration(){
 const client=useQueryClient(),query=useQuery({queryKey:['identity-migration'],queryFn:()=>apiRequest<{items:Migration[]}>('/api/auth/migration')})
 const [action,setAction]=useState<{id:string;kind:'confirm'|'delete'}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 if(query.error)return <ErrorState error={query.error} onRetry={()=>void query.refetch()}/>
 if(!query.data?.items.length)return null
 const apply=async()=>{if(!action||busy)return;setBusy(true);setError('');try{await apiRequest(`/api/auth/migration/${action.id}/${action.kind}`,'POST',{confirm:true});await client.invalidateQueries({queryKey:['identity-migration']});setAction(null)}catch(e){setError(e instanceof Error?e.message:'Migration acknowledgement failed. Backup retained.')}finally{setBusy(false)}}
 return <section aria-label="Account migration backups" className="grid gap-2 rounded border border-line p-3"><h3 className="ui-section-title">Account migration backups</h3><p className="ui-description">Encrypted recovery snapshots retain the migrated account mapping and application evidence. Confirmation keeps the archive; deletion is a separate explicit action. Host recovery keys remain separate.</p>{query.data.items.map(row=><div key={row.id} className="flex flex-wrap items-center gap-2 text-xs"><span>{formatTimestamp(row.created)} · {row.source}</span><StatusBadge>{row.status}</StatusBadge>{row.status==='migrated'&&row.backup_available&&<Button disabled={busy} onClick={()=>setAction({id:row.id,kind:'confirm'})}>Confirm account migration</Button>}{row.status==='confirmed'&&row.backup_available&&<Button disabled={busy} onClick={()=>setAction({id:row.id,kind:'delete'})}>Delete account migration backup</Button>}</div>)}{error&&<p role="alert">{error}</p>}{action&&<ConfirmDialog title={action.kind==='confirm'?'Confirm account migration?':'Delete account migration backup?'} confirmLabel={busy?'Saving…':'Confirm'} onCancel={()=>{if(!busy)setAction(null)}} onConfirm={()=>void apply()}><p>{action.kind==='confirm'?'Confirm that accounts, permissions, branding and review history work after upgrading. The encrypted recovery archive stays retained.':'Permanently delete this confirmed migration archive. Current accounts and review history are preserved. Keep an independent verified recovery copy first.'}</p></ConfirmDialog>}</section>
}
