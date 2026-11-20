import { Github } from 'lucide-react'

/** One unobtrusive footer for application pages and the Settings scroll area. */
export function ApplicationFooter({ version, mode, note }: { version?:string; mode?:string; note?:string }) {
 return <footer className="border-t border-line px-4 py-3 text-xs text-muted">
  <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-2">
   <span aria-label="Application version">AuthLens{version?` v${version}`:''}{mode==='local-build'?' · Local build':mode==='local'||mode==='build'?' · Development build':''}</span>
   <a className="inline-flex min-h-8 items-center gap-1 rounded-control underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus" href="https://github.com/OnlyDrey/sap-lens" target="_blank" rel="noopener noreferrer"><Github size={15} aria-hidden="true"/>GitHub repository</a>
  </div>
  {note&&<p className="mx-auto mt-1 max-w-screen-2xl">{note}</p>}
 </footer>
}
