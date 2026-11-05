import { useState } from 'react'
import { Github } from 'lucide-react'
import { applicationToken } from '@/api/client'

/** One unobtrusive footer for application pages and the Settings scroll area. */
export function ApplicationFooter({ version, mode, note }: { version?:string; mode?:string; note?:string }) {
 const [error,setError]=useState('')
 return <footer className="border-t border-line px-4 py-3 text-xs text-muted">
  <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-2">
   <span aria-label="Application version">SAP Lens{version?` v${version}`:''}{mode==='local-build'?' · Local build':mode==='local'||mode==='build'?' · Development build':''}</span>
   <a className="inline-flex min-h-8 items-center gap-1 rounded-control underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus" href="https://github.com/OnlyDrey/sap-lens" target="_blank" rel="noopener noreferrer" onClick={event=>{
    if(!window.pywebview)return
    event.preventDefault();setError('')
    const open=window.pywebview.api.open_project_repository
    if(!open){setError('Update SAP Lens Desktop to open the repository externally.');return}
    void open(applicationToken()).then(ok=>{if(!ok)setError('The external browser could not open.')}).catch(()=>setError('The external browser could not open.'))
   }}><Github size={15} aria-hidden="true"/>GitHub repository</a>
  </div>
  {note&&<p className="mx-auto mt-1 max-w-screen-2xl">{note}</p>}
  {error&&<p role="alert">{error}</p>}
 </footer>
}
