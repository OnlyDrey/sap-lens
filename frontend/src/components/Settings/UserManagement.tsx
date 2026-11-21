import {IdentityMigration} from './IdentityMigration'
import {useMemo,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {KeyRound,LogOut,Pencil,Plus,RotateCw,ShieldCheck,Trash2,UserCheck,UserX,UsersRound} from 'lucide-react'
import {apiRequest} from '@/api/client'
import {authMessage,formatAccountTime,PASSWORD_MAX,PASSWORD_MIN,RoleBadge,useAuthentication,type Account} from '@/components/Auth/Authentication'
import {ActionMenu} from '@/components/Shared/ActionMenu'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input,PasswordInput,SearchInput} from '@/components/Shared/Controls'
import {ClearFilterButton} from '@/components/Shared/ClearFilterButton'
import {ConfirmDialog} from '@/components/Shared/ConfirmDialog'
import {Dialog} from '@/components/Shared/Dialog'
import {Select} from '@/components/Shared/Select'
import {EnabledBadge} from '@/components/Shared/StatusBadges'
import {DataTable,EmptyState,ErrorState,LoadingState,StatusBadge} from '@/components/Shared/Presentation'

interface AuditEvent {id:string;at:number;actor:string;operation:string;target:string}
type Pending={title:string;body:string;confirmLabel:string;action:()=>Promise<void>}
const ROLES:Account['role'][]=['administrator','reviewer','viewer']
const roleName=(role:string)=>role.charAt(0).toUpperCase()+role.slice(1)

/** Settings → User Management: application accounts, their actions and the security audit. Every change is authorized and audited by the server;
 *  the page only filters what the server returned. */
export function UserManagement(){
 const qc=useQueryClient(),me=useAuthentication().user
 const users=useQuery({queryKey:['auth-users'],queryFn:()=>apiRequest<{items:Account[]}>('/api/auth/users')})
 const audit=useQuery({queryKey:['auth-audit'],queryFn:()=>apiRequest<{items:AuditEvent[]}>('/api/auth/audit')})
 const [search,setSearch]=useState(''),[role,setRole]=useState(''),[status,setStatus]=useState(''),[editing,setEditing]=useState<Account|'new'|null>(null)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[pending,setPending]=useState<Pending|null>(null),[code,setCode]=useState<{username:string;code:string}|null>(null)
 const refresh=async()=>{await Promise.all([qc.invalidateQueries({queryKey:['auth-users']}),qc.invalidateQueries({queryKey:['auth-audit']})])}
 const run=async(action:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await action();await refresh()}catch(e){setError(authMessage(e))}finally{setBusy(false);setPending(null)}}
 const all=useMemo(()=>users.data?.items||[],[users.data])
 const rows=useMemo(()=>{
  const needle=search.trim().toLowerCase()
  return all.filter(user=>(!role||user.role===role)&&(!status||String(user.enabled)===status)&&(!needle||`${user.username}\n${user.display_name}`.toLowerCase().includes(needle)))
   .sort((a,b)=>a.username.localeCompare(b.username,undefined,{sensitivity:'base'}))
 },[all,search,role,status])
 const filtered=!!(search||role||status)
 const clear=()=>{setSearch('');setRole('');setStatus('')}
 const act=(user:Account,id:string)=>{
  if(id==='edit'){setEditing(user);return}
  if(id==='delete')setPending({title:`Permanently delete ${user.username}?`,confirmLabel:'Delete account',body:'The account, credentials, sessions and one-time codes will be permanently removed from this installation. Security audit keeps opaque identity links without the deleted account’s names. Historical review evidence and existing backups are preserved. This cannot be undone except by restoring a backup.',
   action:async()=>{await apiRequest(`/api/auth/users/${user.id}`,'DELETE',{expected_revision:user.revision,confirm_username:user.username,confirm:true});setMessage(`Account ${user.username} permanently deleted.`)}})
  if(id==='revoke')setPending({title:`Revoke sessions for ${user.username}?`,confirmLabel:'Revoke sessions',body:`Every signed-in session of ${user.display_name||user.username} ends immediately. The account stays enabled. The action is recorded in the security audit.`,
   action:async()=>{await apiRequest(`/api/auth/users/${user.id}/revoke`,'POST');setMessage(`Sessions of ${user.username} revoked.`)}})
  if(id==='reset')setPending({title:`Reset password for ${user.username}?`,confirmLabel:'Create reset code',body:'A one-time reset code is created and the current password stops working. Existing sessions end. The action is recorded in the security audit.',
   action:async()=>{const result=await apiRequest<{code:string}>(`/api/auth/users/${user.id}/reset`,'POST',{expected_revision:user.revision,confirm:true});setCode({username:user.username,code:result.code})}})
  if(id==='toggle')setPending({title:`${user.enabled?'Disable':'Enable'} ${user.username}?`,confirmLabel:user.enabled?'Disable account':'Enable account',
   body:user.enabled?'The account can no longer sign in and its sessions end immediately. Its review history is kept. The action is recorded in the security audit.':'The account can sign in again with its current password. The action is recorded in the security audit.',
   action:async()=>{await apiRequest(`/api/auth/users/${user.id}`,'POST',{expected_revision:user.revision,display_name:user.display_name,role:user.role,enabled:!user.enabled});setMessage(`${user.username} ${user.enabled?'disabled':'enabled'}.`)}})
 }
 return <div className="grid grid-cols-[minmax(0,1fr)] gap-5 min-w-0">
 <section className="grid grid-cols-[minmax(0,1fr)] gap-3 min-w-0" aria-labelledby="user-management-title">
  <header className="ui-section-header"><div className="grid gap-1"><h2 id="user-management-title"><UsersRound size={18} aria-hidden="true"/>User Management</h2><p className="ui-description">Application accounts, roles and sign-in access. Administrators manage accounts; reviewers decide; viewers read.</p></div>
   <Button variant="primary" disabled={busy} onClick={()=>setEditing('new')}><Plus size={16} aria-hidden="true"/>Create user</Button></header>
  <IdentityMigration/>
  <div className="user-admin-toolbar" role="search" aria-label="Filter application accounts">
   <SearchInput aria-label="Search application accounts" placeholder="Search username or display name" value={search} onChange={e=>setSearch(e.target.value)} onClear={()=>setSearch('')}/>
   <FormField label="Role"><Select value={role} onChange={e=>setRole(e.target.value)}><option value="">All roles</option>{ROLES.map(value=><option key={value} value={value}>{roleName(value)}</option>)}</Select></FormField>
   <FormField label="Account status"><Select value={status} onChange={e=>setStatus(e.target.value)}><option value="">All accounts</option><option value="true">Enabled</option><option value="false">Disabled</option></Select></FormField>
   {filtered&&<ClearFilterButton onClick={clear}>Clear filters</ClearFilterButton>}
  </div>
  {error&&<p role="alert" className="account-feedback">{error}</p>}{message&&<p role="status" className="account-feedback">{message}</p>}
  {users.isLoading?<LoadingState/>:users.error?<ErrorState error={users.error} onRetry={()=>void users.refetch()}/>:<>
   <p className="user-admin-count" aria-live="polite">{filtered?`${rows.length} of ${all.length} accounts`:`${all.length} ${all.length===1?'account':'accounts'}`}</p>
   {rows.length?<DataTable caption="Application accounts" tableClassName="w-full user-admin-table"><thead><tr><th scope="col">Username</th><th scope="col">Display name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Last login</th><th scope="col" className="col-actions">Actions</th></tr></thead>
    <tbody>{rows.map(user=><tr key={user.id}><td className="font-mono">{user.username}</td><td className="user-admin-name">{user.display_name}{me?.id===user.id&&<> <StatusBadge tone="info">You</StatusBadge></>}</td><td><RoleBadge role={user.role}/></td><td><EnabledBadge enabled={user.enabled}/></td><td>{formatAccountTime(user.last_login)}</td>
     <td className="col-actions"><ActionMenu label={`Actions for ${user.username}`} disabled={busy} onSelect={id=>act(user,id)} items={[
      {id:'edit',label:'Edit user',description:'Display name, role and status',icon:<Pencil size={16} aria-hidden="true"/>},
      {id:'reset',label:'Reset password',description:'Create a one-time reset code',icon:<KeyRound size={16} aria-hidden="true"/>},
      {id:'revoke',label:'Revoke sessions',description:'Sign out everywhere',icon:<LogOut size={16} aria-hidden="true"/>},
      {id:'toggle',label:user.enabled?'Disable account':'Enable account',description:user.enabled?'Block sign-in and end sessions':'Allow sign-in again',tone:user.enabled?'destructive':'default',icon:user.enabled?<UserX size={16} aria-hidden="true"/>:<UserCheck size={16} aria-hidden="true"/>},
      {id:'delete',label:'Delete account',description:me?.id===user.id?'You cannot delete your own account':user.enabled&&user.role==='administrator'&&all.filter(item=>item.enabled&&item.role==='administrator').length<=1?'Keep at least one active administrator':'Permanently remove account and sign-in secrets',disabled:me?.id===user.id||user.enabled&&user.role==='administrator'&&all.filter(item=>item.enabled&&item.role==='administrator').length<=1,tone:'destructive',icon:<Trash2 size={16} aria-hidden="true"/>},
     ]}/></td></tr>)}</tbody></DataTable>
   :<EmptyState>{filtered?<>No accounts match these filters. <Button variant="ghost" size="compact" onClick={clear}>Clear filters</Button></>:'No application accounts yet.'}</EmptyState>}
  </>}
 </section>
 <SecurityAudit query={audit} accounts={all}/>
 {editing&&<EditAccount account={editing} onClose={()=>setEditing(null)} onSave={async body=>{await apiRequest('/api/auth/users'+(editing==='new'?'':'/'+editing.id),'POST',body);await refresh();setEditing(null);setMessage(editing==='new'?'Account created.':'Account saved.')}}/>}
 {pending&&<ConfirmDialog title={pending.title} confirmLabel={busy?'Saving…':pending.confirmLabel} onCancel={()=>{if(!busy)setPending(null)}} onConfirm={()=>{if(!busy)void run(pending.action)}}><p>{pending.body}</p></ConfirmDialog>}
 {code&&<Dialog size="narrow" title="One-time password reset code" onClose={()=>setCode(null)}><p>Give this code to {code.username} through a secure channel. It expires after 15 minutes and is shown only once; do not store it.</p><p className="font-mono break-all mt-3 text-base" aria-label="Password reset code">{code.code}</p></Dialog>}
 </div>
}

/** Audit actor as recorded by the server: a JSON identity ({id, username, display_name, provenance}) or a fixed word such as "local-bootstrap". */
export function describeActor(actor:string){
 try{const deleted=JSON.parse(actor) as {id?:unknown;provenance?:unknown};if(deleted?.provenance==='deleted-account'&&typeof deleted.id==='string')return `Deleted account (${deleted.id})`}catch{/* fixed legacy actor */}
 try{const value=JSON.parse(actor) as {username?:unknown;display_name?:unknown};if(value&&typeof value.username==='string')return typeof value.display_name==='string'&&value.display_name&&value.display_name!==value.username?`${value.display_name} (${value.username})`:value.username}catch{/* not JSON: shown as recorded */}
 return actor||'—'
}

/** The server's latest security events (newest first; the server returns at most 100 by default). Account ids are shown by username when the
 *  account still exists; filtering is local to what was returned. */
function SecurityAudit({query,accounts}:{query:ReturnType<typeof useQuery<{items:AuditEvent[]}>>;accounts:Account[]}){
 const [filter,setFilter]=useState('')
 const names=useMemo(()=>new Map(accounts.map(account=>[account.id,account.username])),[accounts])
 const items=useMemo(()=>(query.data?.items||[]).map(event=>({...event,account:event.target?names.get(event.target)??event.target:'—',who:describeActor(event.actor)})),[query.data,names])
 const needle=filter.trim().toLowerCase()
 const rows=needle?items.filter(event=>`${event.operation}\n${event.account}\n${event.who}`.toLowerCase().includes(needle)):items
 return <section className="grid grid-cols-[minmax(0,1fr)] gap-3 min-w-0 security-audit" aria-labelledby="security-audit-title">
  <header className="ui-section-header"><div className="grid gap-1"><h2 id="security-audit-title"><ShieldCheck size={18} aria-hidden="true"/>Security audit</h2><p className="ui-description">Sign-ins, account changes, password resets and session revocations, newest first. Recorded by the server; it cannot be edited here.</p></div>
   <Button size="compact" loading={query.isFetching} onClick={()=>void query.refetch()}><RotateCw size={14} aria-hidden="true"/>Refresh</Button></header>
  {query.isLoading?<LoadingState/>:query.error?<ErrorState error={query.error} title="The security audit could not be loaded" onRetry={()=>void query.refetch()}/>:<>
   <div className="user-admin-toolbar"><SearchInput aria-label="Search security audit" placeholder="Search operation, account or actor" value={filter} onChange={e=>setFilter(e.target.value)} onClear={()=>setFilter('')}/><span className="user-admin-count" aria-live="polite">{needle?`${rows.length} of ${items.length} events`:`Latest ${items.length} ${items.length===1?'event':'events'}`}</span></div>
   {rows.length?<DataTable caption="Security audit events" density="compact" sticky tableClassName="w-full"><thead><tr><th scope="col">Time</th><th scope="col">Operation</th><th scope="col">Account</th><th scope="col">Actor</th></tr></thead>
    <tbody>{rows.map(event=><tr key={event.id}><td className="whitespace-nowrap">{formatAccountTime(event.at)}</td><td><code>{event.operation}</code></td><td className={event.account===event.target?'font-mono break-all':'font-mono'}>{event.account}</td><td>{event.who}</td></tr>)}</tbody></DataTable>
   :<EmptyState>{needle?'No events match this search.':'No security events recorded yet.'}</EmptyState>}
  </>}
 </section>
}

function EditAccount({account,onClose,onSave}:{account:Account|'new';onClose:()=>void;onSave:(body:Record<string,unknown>)=>Promise<void>}){
 const creating=account==='new'
 const [username,setUsername]=useState(creating?'':account.username),[display,setDisplay]=useState(creating?'':account.display_name),[role,setRole]=useState<Account['role']>(creating?'viewer':account.role),[enabled,setEnabled]=useState(creating||account.enabled),[password,setPassword]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[confirm,setConfirm]=useState(false)
 const unchanged=!creating&&display.trim()===account.display_name&&role===account.role&&enabled===account.enabled
 const save=async()=>{if(busy)return;setBusy(true);setError('');try{await onSave(creating?{username:username.trim(),display_name:display.trim(),role,password}:{expected_revision:account.revision,display_name:display.trim(),role,enabled});setPassword('')}catch(e){setError(authMessage(e))}finally{setBusy(false);setConfirm(false)}}
 const submit=()=>{if(!creating&&(role!==account.role||enabled!==account.enabled)){setConfirm(true);return}void save()}
 return <Dialog size="medium" title={creating?'Create application user':`Edit ${account.username}`} description={creating?'The user signs in with this username and initial password and should change the password afterwards.':'Role and status changes end the account\'s sessions.'} onClose={()=>{if(!busy)onClose()}} footer={null}>
 <form className="account-form-grid" onSubmit={e=>{e.preventDefault();submit()}}>
  <FormField label="Username" description={creating?'Letters, digits and . _ - @; cannot be changed later.':undefined}><Input disabled={!creating||busy} autoComplete="off" value={username} pattern="[A-Za-z0-9_.@\-]+" maxLength={100} required onChange={e=>setUsername(e.target.value)}/></FormField>
  <FormField label="Display name"><Input value={display} maxLength={120} required onChange={e=>setDisplay(e.target.value)}/></FormField>
  <FormField label="Role"><Select value={role} onChange={e=>setRole(e.target.value as Account['role'])}>{ROLES.map(value=><option key={value} value={value}>{roleName(value)}</option>)}</Select></FormField>
  {creating?<FormField label="Initial password" description={`${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`}><PasswordInput autoComplete="new-password" value={password} required minLength={PASSWORD_MIN} maxLength={PASSWORD_MAX} onChange={e=>setPassword(e.target.value)}/></FormField>
   :<div className="self-end pb-2"><Checkbox checked={enabled} onChange={e=>setEnabled(e.target.checked)}>Account enabled</Checkbox></div>}
  {error&&<p role="alert" className="account-feedback account-form-wide">{error}</p>}
  {confirm?<div role="alert" className="account-form-wide grid gap-2"><p>Confirm this role or status change? The account's existing sessions will be revoked.</p><div className="account-actions"><Button variant="primary" loading={busy} onClick={()=>void save()}>Confirm account change</Button><Button disabled={busy} onClick={()=>setConfirm(false)}>Cancel change</Button></div></div>
   :<div className="account-actions account-form-wide justify-end"><Button disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" loading={busy} disabled={unchanged}>Save user</Button></div>}
 </form></Dialog>
}
