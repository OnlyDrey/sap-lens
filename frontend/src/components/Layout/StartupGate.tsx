import {ApiError,recoverTrustedSession} from '@/api/client'
import {Component,useState,type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle } from 'lucide-react'
import { fetchConfiguration } from '@/api/configuration'
import {BackupRestore} from '@/components/Settings/BackupRestore'
import {Button} from '@/components/Shared/Button'
export function StartupGate({ children }: { children: ReactNode }) {
  const [recovery,setRecovery]=useState(false)
  const configuration = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
    retry: false
  })
  const stale = configuration.error instanceof ApiError && configuration.error.kind === 'session'
  if (configuration.data) return children
  return (
    <div className="startup-screen">
      <div className="startup-card">
        <img
          src="/sap-lens.png"
          alt="SAP Lens"
          className="w-24 h-24 object-contain mx-auto"
        />
        <h1 className="text-3xl font-semibold mt-3">SAP Lens</h1>
        <p className="text-sm text-[var(--muted)] mt-2">
          Your local SAP role workspace
        </p>
        {configuration.isError ? (
          <>
            <AlertTriangle
              size={25}
              className="mx-auto mt-5 text-[var(--error)]"
            />
            <h2 className="font-semibold mt-2">
              Unable to load application configuration
            </h2>
            <p role="alert" className="text-sm mt-2">
              {configuration.error instanceof Error?configuration.error.message:'Retry configuration loading or open Backup & Restore for recovery. Your saved data is retained.'}
            </p>
            <div className="startup-actions" role="group" aria-label="Recovery actions">
              {stale && <Button variant="primary" onClick={recoverTrustedSession}>Reload trusted session</Button>}
              <Button variant={stale ? 'secondary' : 'primary'} onClick={() => void configuration.refetch()}>Retry connection</Button>
            </div>
            <div className="startup-actions startup-actions-tertiary">
              <Button variant="ghost" aria-expanded={recovery} onClick={()=>setRecovery(value=>!value)}>Open Backup &amp; Restore</Button>
            </div>
            {recovery&&<div className="mt-4 text-left"><BackupRestore/></div>}
          </>
        ) : (
          <>
            <Loader2 className="animate-spin mx-auto mt-8 text-[var(--accent2)]" />
            <p role="status" className="mt-4">
              Loading configuration…
            </p>
            <p className="text-xs mt-3 text-[var(--muted)]">
              Waiting for configuration from the local service.
            </p>
          </>
        )}
      </div>
    </div>
  )
}


/** Rebuilt lazy assets can disappear while an old tab remains open. Never auto-reload drafts or writes. */
export class FrontendRecoveryBoundary extends Component<{children:ReactNode},{failed:boolean}>{
 state={failed:false}
 static getDerivedStateFromError(){return {failed:true}}
 private assetFailure=(event:Event)=>{event.preventDefault();this.setState({failed:true})}
 componentDidMount(){window.addEventListener('vite:preloadError',this.assetFailure)}
 componentWillUnmount(){window.removeEventListener('vite:preloadError',this.assetFailure)}
 render(){return this.state.failed?<section role="alert" className="ui-card m-4 grid gap-3"><h1>Application recovery</h1><p>The application could not render or its built assets changed. Reload to obtain the current application. Saved filters are retained; unsaved form input may be lost.</p><Button onClick={recoverTrustedSession}>Reload application</Button></section>:this.props.children}
}
