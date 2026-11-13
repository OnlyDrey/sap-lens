import {createContext,useCallback,useContext,useEffect,useState,type ReactNode,type FormEvent} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {ApiError,apiRequest,setSessionRole} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {FormField,Input} from '@/components/Shared/Controls'
import {Dialog} from '@/components/Shared/Dialog'
import {LoadingState} from '@/components/Shared/Presentation'

export interface Account {id:string;username:string;display_name:string;role:'administrator'|'reviewer'|'viewer';enabled:boolean;revision:number;last_login:number|null}
interface Auth {user:Account|null;session:boolean;canAdmin:boolean;canReview:boolean;reload:()=>Promise<void>;logout:()=>Promise<void>}
const Context=createContext<Auth>({user:null,session:false,canAdmin:true,canReview:true,reload:async()=>{},logout:async()=>{}})
export const useAuthentication=()=>useContext(Context)
const messages:Record<string,string>={invalid_credentials:'Username or password was not accepted.',temporarily_throttled:'Too many attempts. Wait briefly before trying again.',invalid_activation:'The code is invalid, expired or exhausted. Request another code from the local administrator.',last_administrator:'Keep at least one enabled Administrator.',stale_user:'This account changed. Reload before saving.',password_length:'Use a passphrase of 12–1024 characters.'}
export const authMessage=(error:unknown)=>error instanceof Error?(messages[error.message.split(' Reference:')[0]]||error.message):'The operation could not be completed.'

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
  window.addEventListener('sap-lens-sign-in-required',expired)
  return()=>{mounted=false;window.removeEventListener('sap-lens-sign-in-required',expired)}
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
 return <main id="main-content" className="startup-screen"><section className="startup-card"><img src="/sap-lens.png" alt="SAP Lens" className="w-20 h-20 object-contain mx-auto"/><h1 className="text-2xl font-semibold">{setup?'Set up SAP Lens':mode==='login'?'Sign in to SAP Lens':'Reset password'}</h1>
 <form onSubmit={event=>void submit(event)} className="grid gap-4 text-left mt-4">
 {(setup||mode==='login')&&<FormField label="Username"><Input autoComplete="username" value={username} maxLength={100} required onChange={e=>setUsername(e.target.value)}/></FormField>}
 {setup&&<FormField label="Display name"><Input autoComplete="name" value={display} maxLength={120} required onChange={e=>setDisplay(e.target.value)}/></FormField>}
 {(setup||mode!=='login')&&<FormField label="One-time code" description={setup?'Generate a code in the local Service Manager or server administration command. Codes expire after 15 minutes.':'Use the code supplied by your administrator.'}><Input autoComplete="off" value={code} required onChange={e=>setCode(e.target.value)}/></FormField>}
 <FormField label={setup||mode!=='login'?'New password':'Password'}><Input type="password" autoComplete={setup||mode!=='login'?'new-password':'current-password'} minLength={setup||mode!=='login'?12:undefined} maxLength={1024} value={password} required onChange={e=>setPassword(e.target.value)}/></FormField>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 <Button type="submit" variant="primary" loading={busy}>{setup?'Create administrator':mode==='login'?'Sign in':'Set password'}</Button>
 {!setup&&<div className="flex flex-wrap gap-2"><Button disabled={busy} variant="ghost" onClick={()=>{setMode(mode==='login'?'reset':'login');setError('');setPassword('')}}>{mode==='login'?'Use password reset code':'Back to sign in'}</Button>{mode==='reset'&&<Button variant="ghost" disabled={busy} onClick={()=>setMode('recover')}>Local administrator recovery</Button>}</div>}
 </form></section></main>
}
export function MyProfile({onClose}:{onClose:()=>void}){
 const auth=useAuthentication(),user=auth.user
 const [name,setName]=useState(user?.display_name||''),[current,setCurrent]=useState(''),[password,setPassword]=useState(''),[sessions,setSessions]=useState<{id:string;created:number;seen:number;current:boolean}[]>([]),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('')
 const load=useCallback(async()=>{const data=await apiRequest<{items:{id:string;created:number;seen:number;current:boolean}[]}>('/api/auth/sessions');setSessions(data.items)},[])
 useEffect(()=>{void load().catch(e=>setError(authMessage(e)))},[load])
 const run=async(action:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await action()}catch(error){setError(authMessage(error))}finally{setBusy(false)}}
 return <Dialog title="My Profile" onClose={()=>{if(!busy)onClose()}} footer={null}><div className="grid gap-4">
 <p>{user?.username} · {user?.role}</p>
 <FormField label="Display name"><Input value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></FormField><Button disabled={busy||!name.trim()} onClick={()=>void run(async()=>{await apiRequest('/api/auth/profile','POST',{display_name:name,expected_revision:user?.revision});await auth.reload();setMessage('Profile saved.')})}>Save profile</Button>
 <h3>Change password</h3><FormField label="Current password"><Input type="password" autoComplete="current-password" value={current} onChange={e=>setCurrent(e.target.value)}/></FormField><FormField label="New password"><Input type="password" autoComplete="new-password" value={password} maxLength={1024} onChange={e=>setPassword(e.target.value)}/></FormField>
 <Button disabled={busy||!current||password.length<12} onClick={()=>void run(async()=>{await apiRequest('/api/auth/password','POST',{current_password:current,new_password:password});setCurrent('');setPassword('');await auth.logout()})}>Change password and sign out</Button>
 <h3>Active sessions</h3><ul>{sessions.map(s=><li key={s.id}>{s.current?'This session':'Other session'} · Last active {new Date(s.seen*1000).toLocaleString()}</li>)}</ul>
 <Button disabled={busy} onClick={()=>void run(async()=>{await apiRequest('/api/auth/logout-others','POST');await load();setMessage('Other sessions signed out.')})}>Sign out other sessions</Button>
 <Button disabled={busy} onClick={()=>void run(auth.logout)}>Sign out</Button>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 </div></Dialog>
}
