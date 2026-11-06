import { AlertTriangle, RefreshCw, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { recoverTrustedSession } from '@/api/client'
import { useSession } from '@/api/session'
import { Button } from '@/components/Shared/Button'
import { mayRestoreAutomatically, recordRestoreAttempt } from '@/lib/startupRecovery'

/** Typed or edited text in an open dialog or form that a reload would discard. Read-only fields and untouched defaults do not count. */
export function hasUnsavedInput(root: ParentNode = document): boolean {
  return Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('[role="dialog"] input, [role="dialog"] textarea, form input, form textarea, aside input, aside textarea'))
    .some((field) => !field.readOnly && !field.disabled && !['checkbox', 'radio', 'button', 'submit', 'hidden', 'search'].includes((field as HTMLInputElement).type) && field.value.trim() !== '' && field.value !== field.defaultValue)
}

const COPY = {
  manual: { title: 'Session disconnected', text: 'SAP Lens restarted and your previous local session is no longer valid. Reconnect to continue.' },
  failed: { title: 'Reconnection failed', text: 'The local session could not be re-established. Retry, and use the technical details if it keeps failing.' },
  reconnecting: { title: 'Reconnecting…', text: 'Re-establishing the local session.' },
  disconnected: { title: 'Connection lost', text: 'SAP Lens cannot reach its local service right now. Data on screen may be out of date until it reconnects.' },
} as const

/** The one application-level session notification. Pages show a compact empty state and never repeat this message or its actions. */
export function SessionNotice({ onRetry, retrying }: { onRetry?: () => void; retrying?: boolean }) {
  const session = useSession()
  const [confirming, setConfirming] = useState(false)
  // The service restarted while this window stayed open. When nothing typed would be lost and no restore ran lately, re-establish the session through the guarded document at once.
  useEffect(() => {
    if (session.phase !== 'manual') return
    let store: Storage | null = null
    try { store = window.sessionStorage } catch { /* unusable storage: stay manual */ }
    const now = Date.now()
    if (hasUnsavedInput() || !mayRestoreAutomatically(store, now)) return
    recordRestoreAttempt(store, now)
    recoverTrustedSession()
  }, [session.phase])
  if (session.phase === 'connecting' || session.phase === 'connected') return null
  const copy = COPY[session.phase]
  const needsReconnect = session.phase === 'manual' || session.phase === 'failed'
  const reconnect = () => { if (!confirming && hasUnsavedInput()) { setConfirming(true); return } recoverTrustedSession() }
  const Icon = session.phase === 'disconnected' ? WifiOff : AlertTriangle
  return (
    <div role="alert" className="session-notice" data-phase={session.phase}>
      <Icon size={18} aria-hidden="true" className="session-notice-icon" />
      <div className="session-notice-body">
        <div className="session-notice-head">
          <strong>{copy.title}</strong>
          <div className="session-notice-actions">
            {needsReconnect && <Button variant="primary" size="compact" onClick={reconnect}><RefreshCw size={14} aria-hidden="true" />{confirming ? 'Reconnect anyway' : session.phase === 'failed' ? 'Retry reconnect' : 'Reconnect session'}</Button>}
            {confirming && <Button size="compact" onClick={() => setConfirming(false)}>Cancel</Button>}
            {session.phase === 'disconnected' && onRetry && <Button size="compact" onClick={onRetry} disabled={retrying}><RefreshCw size={14} aria-hidden="true" />Retry connection</Button>}
          </div>
        </div>
        <span>{confirming ? 'Reconnecting reloads SAP Lens: text typed into open forms will be lost. Nothing is saved or resubmitted automatically.' : copy.text}</span>
        <details className="session-notice-details">
          <summary>Technical details</summary>
          <dl>
            <div><dt>State</dt><dd>{session.phase}</dd></div>
            <div><dt>Category</dt><dd>{session.category || 'none'}</dd></div>
            <div><dt>Failed requests</dt><dd>{session.failures}</dd></div>
            <div><dt>Since</dt><dd>{new Date(session.since).toLocaleTimeString()}</dd></div>
          </dl>
          <p>Reconnecting reloads the trusted session through the guarded application document. If this repeats, restart SAP Lens from the tray or Start menu and close other SAP Lens windows. No credentials are shown here.</p>
        </details>
      </div>
    </div>
  )
}
