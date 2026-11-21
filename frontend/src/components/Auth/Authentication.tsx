import {createContext,useCallback,useContext,useEffect,useState,type ReactNode,type FormEvent} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {ApiError,apiRequest,setSessionRole} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {FormField,Input,PasswordInput} from '@/components/Shared/Controls'
import {ConfirmDialog} from '@/components/Shared/ConfirmDialog'
import {Check,Circle,LogOut} from 'lucide-react'
import {Dialog} from '@/components/Shared/Dialog'
import {DataTable,LoadingState,MetadataList,StatusBadge} from '@/components/Shared/Presentation'

export interface Account {id:string;username:string;display_name:string;role:'administrator'|'reviewer'|'viewer';enabled:boolean;revision:number;last_login:number|null}
interface Auth {user:Account|null;session:boolean;canAdmin:boolean;canReview:boolean;reload:()=>Promise<void>;logout:()=>Promise<void>}
const Context=createContext<Auth>({user:null,session:false,canAdmin:true,canReview:true,reload:async()=>{},logout:async()=>{}})
export const useAuthentication=()=>useContext(Context)
const messages:Record<string,string>={invalid_credentials:'Username or password was not accepted.',temporarily_throttled:'Too many attempts. Wait briefly before trying again.',invalid_activation:'The code is invalid, expired or exhausted. Request another code from the local administrator.',last_administrator:'Keep at least one enabled Administrator.',stale_user:'This account changed. Reload before saving.',password_length:'Use a passphrase of 12–1024 characters.'}
const deletionMessages:Record<string,string>={cannot_delete_self:'You cannot delete your own account.',username_mismatch:'The account no longer matches your confirmation. Reload before deleting.',confirmation_required:'Confirm this action before continuing.'}
export const authMessage=(error:unknown)=>error instanceof Error?(messages[error.message.split(' Reference:')[0]]||deletionMessages[error.message.split(' Reference:')[0]]||error.message):'The operation could not be completed.'

export function AuthenticationGate({children}:{children:ReactNode}) {
 const qc=useQueryClient(),[ready,setReady]=useState(false),[session,setSession]=useState(false),[setup,setSetup]=useState(false),[user,setUser]=useState<Account|null>(null),[error,setError]=useState('')
 const reload=async()=>{
  const next=await apiRequest<Account>('/api/auth/me');setSessionRole(next.role);setUser(next)
 }
 useEffect(()=>{
  let mounted=true
  void apiRequest<{provider:string;setup_required:boolean}>('/api/auth/state').then(async state=>{
   if(!mounted)return
   if(state.provider==='local-sessions'){
    setSession(true);setSetup(state.setup_required)
    if(!state.setup_required){try{await reload()}catch(error){if(!(error instanceof ApiError&&error.status===401))throw error}}
   }
   if(mounted)setReady(true)
  }).catch(error=>{
   if(!mounted)return
   // Desktop only: the launch capability of an earlier run was refused. That is not a sign-in question; the application shell
   // must mount so its guarded session recovery reloads the trusted document (no sign-in form, no error card that blocks it).
   if(error instanceof ApiError&&error.kind==='session'){setReady(true);return}
   setError(authMessage(error))
  })
  const expired=()=>{void qc.cancelQueries();qc.clear();setUser(null);setSessionRole(null)}
  window.addEventListener('authlens-sign-in-required',expired)
  return()=>{mounted=false;window.removeEventListener('authlens-sign-in-required',expired)}
 },[qc])
 const logout=async()=>{try{await apiRequest('/api/auth/logout','POST')}catch(error){if(!(error instanceof ApiError&&error.status===401))throw error}void qc.cancelQueries();qc.clear();setUser(null);setSessionRole(null)}
 if(!ready)return <div className="startup-screen"><div className="startup-card">{error?<><p role="alert">{error}</p><Button onClick={()=>location.reload()}>Retry connection</Button></>:<LoadingState/>}</div></div>
 if(session&&!user)return <Login setup={setup} onActivated={()=>setSetup(false)} onReady={async()=>{setSetup(false);await reload()}}/>
 return <Context.Provider value={{user,session,canAdmin:!session||user?.role==='administrator',canReview:!session||user?.role!=='viewer',reload,logout}}>{children}</Context.Provider>
}
function Login({setup,onActivated,onReady}:{setup:boolean;onActivated:()=>void;onReady:()=>Promise<void>}){
 const [mode,setMode]=useState<'login'|'reset'|'recover'>(setup?'recover':'login'),[username,setUsername]=useState(''),[display,setDisplay]=useState(''),[password,setPassword]=useState(''),[code,setCode]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 const submit=async(event:FormEvent)=>{
  event.preventDefault();if(busy)return;setBusy(true);setError('');setMessage('')
  try{
   if(setup){await apiRequest('/api/auth/activate','POST',{username,display_name:display,password,code});onActivated();setMode('login');await apiRequest('/api/auth/login','POST',{username,password});await onReady()}
   else if(mode==='login'){await apiRequest('/api/auth/login','POST',{username,password});await onReady()}
   else{await apiRequest('/api/auth/'+(mode==='reset'?'reset':'recover'),'POST',{code,password});setPassword('');setCode('');setMode('login');setMessage('Password updated. Sign in with your new password.')}
  }catch(error){setError(authMessage(error))}finally{setBusy(false)}
 }
 return <main id="main-content" className="startup-screen"><section className="startup-card"><img src="/sap-lens.png" alt="AuthLens" className="w-20 h-20 object-contain mx-auto"/><h1 className="text-2xl font-semibold">{setup?'Set up AuthLens':mode==='login'?'Sign in to AuthLens':'Reset password'}</h1>
 <form onSubmit={event=>void submit(event)} className="grid gap-4 text-left mt-4">
 {(setup||mode==='login')&&<FormField label="Username"><Input autoComplete="username" value={username} maxLength={100} required onChange={e=>setUsername(e.target.value)}/></FormField>}
 {setup&&<FormField label="Display name"><Input autoComplete="name" value={display} maxLength={120} required onChange={e=>setDisplay(e.target.value)}/></FormField>}
 {(setup||mode!=='login')&&<FormField label="One-time code" description={setup?'Generate a code in the local Service Manager or server administration command. Codes expire after 15 minutes.':'Use the code supplied by your administrator.'}><Input autoComplete="off" value={code} required onChange={e=>setCode(e.target.value)}/></FormField>}
 <FormField label={setup||mode!=='login'?'New password':'Password'}><PasswordInput autoComplete={setup||mode!=='login'?'new-password':'current-password'} minLength={setup||mode!=='login'?12:undefined} maxLength={1024} value={password} required onChange={e=>setPassword(e.target.value)}/></FormField>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 <Button type="submit" variant="primary" loading={busy}>{setup?'Create administrator':mode==='login'?'Sign in':'Set password'}</Button>
 {!setup&&<div className="flex flex-wrap gap-2"><Button disabled={busy} variant="ghost" onClick={()=>{setMode(mode==='login'?'reset':'login');setError('');setPassword('')}}>{mode==='login'?'Use password reset code':'Back to sign in'}</Button>{mode==='reset'&&<Button variant="ghost" disabled={busy} onClick={()=>setMode('recover')}>Local administrator recovery</Button>}</div>}
 </form></section></main>
}
interface AccountSession {id:string;created:number;seen:number;current:boolean}
const roleLabels:Record<Account['role'],string>={administrator:'Administrator',reviewer:'Reviewer',viewer:'Viewer'}
const roleTones:Record<Account['role'],'accent'|'info'|'neutral'>={administrator:'accent',reviewer:'info',viewer:'neutral'}
export const RoleBadge=({role}:{role:Account['role']})=><StatusBadge tone={roleTones[role]??'neutral'}>{roleLabels[role]??role}</StatusBadge>
/** Server timestamps (Unix seconds) in the viewer's locale; one format for profile, sessions and administration. */
export const formatAccountTime=(seconds:number|null|undefined)=>seconds?new Date(seconds*1000).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'Never'
/** The server's password policy (auth_store / AccountStore): 12 to 1024 characters. Shown as guidance; the server remains the authority. */
export const PASSWORD_MIN=12, PASSWORD_MAX=1024
type Feedback={kind:'status'|'alert';text:string}|null
const FeedbackText=({value}:{value:Feedback})=>value?<p role={value.kind} className="account-feedback">{value.text}</p>:null

export function MyProfile({onClose}:{onClose:()=>void}){
 const auth=useAuthentication(),user=auth.user
 const [name,setName]=useState(user?.display_name||''),[current,setCurrent]=useState(''),[password,setPassword]=useState(''),[confirmation,setConfirmation]=useState('')
 const [sessions,setSessions]=useState<AccountSession[]|null>(null),[busy,setBusy]=useState<''|'profile'|'password'|'sessions'|'logout'>(''),[confirmOthers,setConfirmOthers]=useState(false)
 const [profileFeedback,setProfileFeedback]=useState<Feedback>(null),[passwordFeedback,setPasswordFeedback]=useState<Feedback>(null),[sessionFeedback,setSessionFeedback]=useState<Feedback>(null)
 const load=useCallback(async()=>{const data=await apiRequest<{items:AccountSession[]}>('/api/auth/sessions');setSessions([...data.items].sort((a,b)=>Number(b.current)-Number(a.current)||b.seen-a.seen))},[])
 useEffect(()=>{void load().catch(e=>setSessionFeedback({kind:'alert',text:authMessage(e)}))},[load])
 const run=async(kind:Exclude<typeof busy,''>,feedback:(value:Feedback)=>void,action:()=>Promise<string|void>)=>{
  if(busy)return;setBusy(kind);feedback(null)
  try{const text=await action();if(text)feedback({kind:'status',text})}catch(error){feedback({kind:'alert',text:authMessage(error)})}finally{setBusy('')}
 }
 const trimmed=name.trim(),nameChanged=!!user&&trimmed!==user.display_name
 const lengthOk=password.length>=PASSWORD_MIN&&password.length<=PASSWORD_MAX,matches=password.length>0&&password===confirmation
 const passwordReady=!!current&&lengthOk&&matches
 const others=(sessions||[]).filter(session=>!session.current).length
 return <Dialog size="medium" title="My Profile" description="Your AuthLens account, password and signed-in sessions." onClose={()=>{if(!busy)onClose()}}
  footer={<><Button variant="ghost" loading={busy==='logout'} disabled={!!busy&&busy!=='logout'} onClick={()=>void run('logout',setSessionFeedback,auth.logout)}><LogOut size={16} aria-hidden="true"/>Sign out</Button><Button disabled={!!busy} onClick={onClose}>Close</Button></>}>
 <section className="account-section" aria-labelledby="profile-information">
  <header><h3 id="profile-information">Profile information</h3><p className="ui-description">Your display name appears in review history and audit records.</p></header>
  <MetadataList items={[{label:'Username',value:<span className="font-mono">{user?.username}</span>},{label:'Role',value:user?<RoleBadge role={user.role}/>:'—'},{label:'Last sign-in',value:formatAccountTime(user?.last_login)}]}/>
  <form className="grid gap-3" onSubmit={event=>{event.preventDefault();if(!nameChanged||!trimmed)return;void run('profile',setProfileFeedback,async()=>{await apiRequest('/api/auth/profile','POST',{display_name:trimmed,expected_revision:user?.revision});await auth.reload();setName(trimmed);return 'Profile saved.'})}}>
   <FormField label="Display name" description={!trimmed?'Enter a display name.':undefined}><Input value={name} maxLength={120} autoComplete="name" required aria-invalid={!trimmed||undefined} onChange={e=>{setName(e.target.value);setProfileFeedback(null)}}/></FormField>
   <div className="account-actions"><FeedbackText value={profileFeedback}/><Button type="submit" variant="primary" size="compact" loading={busy==='profile'} disabled={(!!busy&&busy!=='profile')||!nameChanged||!trimmed}>Save changes</Button></div>
  </form>
 </section>
 <section className="account-section" aria-labelledby="password-security">
  <header><h3 id="password-security">Password and security</h3><p className="ui-description">Changing your password signs you out of every session, including this one.</p></header>
  <form className="account-form-grid" onSubmit={event=>{event.preventDefault();if(!passwordReady)return;void run('password',setPasswordFeedback,async()=>{await apiRequest('/api/auth/password','POST',{current_password:current,new_password:password});setCurrent('');setPassword('');setConfirmation('');await auth.logout()})}}>
   <div className="account-form-wide"><FormField label="Current password"><PasswordInput autoComplete="current-password" value={current} maxLength={PASSWORD_MAX} onChange={e=>{setCurrent(e.target.value);setPasswordFeedback(null)}}/></FormField></div>
   <FormField label="New password"><PasswordInput autoComplete="new-password" value={password} maxLength={PASSWORD_MAX} aria-invalid={(password.length>0&&!lengthOk)||undefined} onChange={e=>{setPassword(e.target.value);setPasswordFeedback(null)}}/></FormField>
   <FormField label="Confirm new password"><PasswordInput autoComplete="new-password" value={confirmation} maxLength={PASSWORD_MAX} aria-invalid={(confirmation.length>0&&!matches)||undefined} onChange={e=>{setConfirmation(e.target.value);setPasswordFeedback(null)}}/></FormField>
   <ul className="password-rules account-form-wide" aria-label="Password requirements">
    <li data-met={lengthOk}>{lengthOk?<Check size={14} aria-hidden="true"/>:<Circle size={14} aria-hidden="true"/>}{PASSWORD_MIN} to {PASSWORD_MAX} characters{password.length>0&&!lengthOk?` (now ${password.length})`:''}</li>
    <li data-met={matches}>{matches?<Check size={14} aria-hidden="true"/>:<Circle size={14} aria-hidden="true"/>}Both new password fields match</li>
   </ul>
   <div className="account-actions account-form-wide"><FeedbackText value={passwordFeedback}/><Button type="submit" variant="primary" size="compact" loading={busy==='password'} disabled={(!!busy&&busy!=='password')||!passwordReady}>Change password and sign out</Button></div>
  </form>
 </section>
 <section className="account-section" aria-labelledby="active-sessions">
  <header><h3 id="active-sessions">Active sessions</h3><p className="ui-description">Browsers signed in to this account. Sessions end after inactivity or when signed out.</p></header>
  {sessions===null?(sessionFeedback?null:<LoadingState/>):<DataTable caption="Active sessions" density="compact" tableClassName="w-full"><thead><tr><th scope="col">Session</th><th scope="col">Signed in</th><th scope="col">Last activity</th></tr></thead><tbody>{sessions.map(session=><tr key={session.id}><td>{session.current?<StatusBadge tone="success">This session</StatusBadge>:'Other session'}</td><td>{formatAccountTime(session.created)}</td><td>{formatAccountTime(session.seen)}</td></tr>)}</tbody></DataTable>}
  <div className="account-actions"><FeedbackText value={sessionFeedback}/><Button size="compact" disabled={!!busy||!others} loading={busy==='sessions'} title={!others?'No other sessions are signed in.':undefined} onClick={()=>setConfirmOthers(true)}>Sign out other sessions</Button></div>
 </section>
 {confirmOthers&&<ConfirmDialog title="Sign out other sessions?" confirmLabel="Sign out other sessions" onCancel={()=>setConfirmOthers(false)} onConfirm={()=>{setConfirmOthers(false);void run('sessions',setSessionFeedback,async()=>{await apiRequest('/api/auth/logout-others','POST');await load();return 'Other sessions signed out.'})}}><p>{others===1?'1 other session':`${others} other sessions`} will be signed out immediately. This session stays signed in.</p></ConfirmDialog>}
 </Dialog>
}
