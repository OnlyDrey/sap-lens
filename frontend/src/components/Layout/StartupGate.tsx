import { ApiError, recoverTrustedSession } from '@/api/client'
import { Component, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle } from 'lucide-react'
import { fetchConfiguration } from '@/api/configuration'
import { BackupRestore } from '@/components/Settings/BackupRestore'
import { Button } from '@/components/Shared/Button'
import { classifyFailure, mayRestoreAutomatically, recordRestoreAttempt, retryDelay, shouldRetry, STARTUP_LABELS, type StartupFailure } from '@/lib/startupRecovery'

const storage = (): Storage | null => { try { return window.sessionStorage } catch { return null } }

/** Shown only after automatic restoring did not help. One explanation, one primary action, technical details on demand. */
const FAILURES: Record<StartupFailure, { title: string; text: string }> = {
  unavailable: { title: 'SAP Lens cannot reach its local service', text: 'The local service did not answer after several attempts. Your saved data is retained. Retry, or close all SAP Lens windows and start it again.' },
  session: { title: 'SAP Lens could not restore your local session', text: 'The local session ended and could not be re-established automatically. Retry; if this keeps happening, close all SAP Lens windows and start SAP Lens again.' },
  rejected: { title: 'Access was not accepted', text: 'The local service refused this request. Retry; if it persists, check that you are using the SAP Lens address you were given.' },
  failed: { title: 'SAP Lens could not load its configuration', text: 'The service is running, but its configuration or storage could not be loaded. Your saved data is retained. Retry, or use Backup & Restore to recover.' },
}

export function StartupGate({ children }: { children: ReactNode }) {
  const [backup, setBackup] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const started = useRef(false)
  const configuration = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
    // The service may still be starting: wait for it with a bounded back-off. Session, authentication and configuration failures are never retried by this rule.
    retry: (count, error) => error instanceof ApiError && shouldRetry(count, error),
    retryDelay,
  })
  const error = configuration.error instanceof ApiError ? configuration.error : null
  const failure = error ? classifyFailure(error) : configuration.isError ? 'failed' : null
  // The previous local session is gone (the service restarted). Obtain a fresh one through the guarded desktop document, once, then load again.
  useEffect(() => {
    if (failure !== 'session' || started.current) return
    const now = Date.now()
    if (!mayRestoreAutomatically(storage(), now)) return
    started.current = true
    recordRestoreAttempt(storage(), now)
    setRestoring(true)
    recoverTrustedSession()
  }, [failure])
  if (configuration.data) return children
  const label = restoring ? STARTUP_LABELS.restoring : configuration.failureCount > 0 ? STARTUP_LABELS.connecting : STARTUP_LABELS.starting
  const showRecovery = configuration.isError && !restoring
  const copy = failure ? FAILURES[failure] : null
  const retry = () => {
    if (failure === 'session') { recordRestoreAttempt(storage(), Date.now()); recoverTrustedSession(); return }
    void configuration.refetch()
  }
  return (
    <div className="startup-screen">
      <div className="startup-card">
        <img src="/sap-lens.png" alt="SAP Lens" className="w-24 h-24 object-contain mx-auto" />
        <h1 className="text-3xl font-semibold mt-3">SAP Lens</h1>
        <p className="text-sm text-[var(--muted)] mt-2">Your local SAP role workspace</p>
        {showRecovery && copy ? (
          <>
            <AlertTriangle size={25} className="mx-auto mt-5 text-[var(--error)]" />
            <h2 className="font-semibold mt-2">{copy.title}</h2>
            <p role="alert" className="text-sm mt-2">{copy.text}</p>
            <div className="startup-actions" role="group" aria-label="Recovery actions">
              <Button variant="primary" onClick={retry} disabled={configuration.isFetching}>Retry connection</Button>
            </div>
            <details className="text-left text-xs mt-4">
              <summary className="cursor-pointer">Technical details</summary>
              <dl className="mt-2 grid gap-1">
                <div><dt className="inline font-semibold">Problem: </dt><dd className="inline">{failure}</dd></div>
                <div><dt className="inline font-semibold">Status: </dt><dd className="inline">{error?.status || 'no response'}</dd></div>
                <div><dt className="inline font-semibold">Message: </dt><dd className="inline">{configuration.error instanceof Error ? configuration.error.message : 'unknown'}</dd></div>
              </dl>
              <p className="mt-2 text-[var(--muted)]">No credentials or session tokens are shown here or written to logs.</p>
            </details>
            {failure === 'failed' && <>
              <div className="startup-actions startup-actions-tertiary">
                <Button variant="ghost" aria-expanded={backup} onClick={() => setBackup((value) => !value)}>Open Backup &amp; Restore</Button>
              </div>
              {backup && <div className="mt-4 text-left"><BackupRestore /></div>}
            </>}
          </>
        ) : (
          <>
            <Loader2 className="animate-spin mx-auto mt-8 text-[var(--accent2)]" />
            <p role="status" className="mt-4">{label}</p>
          </>
        )}
      </div>
    </div>
  )
}

const OPTIONAL_CHUNKS = /\/Icon(?:Catalog|Picker)-[\w-]+\.js/

/** Rebuilt lazy assets can disappear while an old tab remains open. Never auto-reload drafts or writes. */
export class FrontendRecoveryBoundary extends Component<{children:ReactNode},{failed:boolean}>{
 state={failed:false}
 static getDerivedStateFromError(){return {failed:true}}
 // Optional chunks (the icon catalog) fall back locally, so their failure must not replace the whole application. The event is left alone
 // (not default-prevented) so the import still rejects into the local fallback; every other failed chunk means the build changed.
 private assetFailure=(event:Event)=>{if(OPTIONAL_CHUNKS.test(String((event as Event&{payload?:{message?:string}}).payload?.message??'')))return;event.preventDefault();this.setState({failed:true})}
 componentDidMount(){window.addEventListener('vite:preloadError',this.assetFailure)}
 componentWillUnmount(){window.removeEventListener('vite:preloadError',this.assetFailure)}
 render(){return this.state.failed?<section role="alert" className="ui-card m-4 grid gap-3"><h1>Application recovery</h1><p>The application could not render or its built assets changed. Reload to obtain the current application. Saved filters are retained; unsaved form input may be lost.</p><Button onClick={recoverTrustedSession}>Reload application</Button></section>:this.props.children}
}
