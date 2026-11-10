/** Pure, dependency-free state machine for the local trusted session. The API client is the only writer; the UI only reads it. */
export type SessionPhase = 'connecting' | 'connected' | 'reconnecting' | 'manual' | 'disconnected' | 'failed'
export type SessionCategory = '' | 'stale_session' | 'network' | 'reconnect_failed'
export interface SessionSnapshot { phase: SessionPhase; category: SessionCategory; failures: number; since: number }
export type SessionEvent = 'success' | 'stale' | 'network' | 'reconnect' | 'reconnect_failed'

export const initialSession = (now = Date.now()): SessionSnapshot => ({ phase: 'connecting', category: '', failures: 0, since: now })

/** Deterministic transitions. A stale session is never cleared by a later success: only an explicit reconnect (a reload that obtains a fresh capability) leaves `manual`. */
export function nextSession(state: SessionSnapshot, event: SessionEvent, now = Date.now()): SessionSnapshot {
  const to = (phase: SessionPhase, category: SessionCategory, failures = state.failures): SessionSnapshot => (phase === state.phase && category === state.category && failures === state.failures ? state : { phase, category, failures, since: phase === state.phase ? state.since : now })
  switch (event) {
    case 'stale': return to('manual', 'stale_session')
    case 'success': return state.phase === 'manual' || state.phase === 'failed' ? state : to('connected', '', 0)
    case 'network': return state.phase === 'manual' || state.phase === 'failed' ? state : to('disconnected', 'network', state.failures + 1)
    case 'reconnect': return state.phase === 'manual' || state.phase === 'disconnected' || state.phase === 'failed' ? to('reconnecting', state.category) : state
    case 'reconnect_failed': return to('failed', 'reconnect_failed')
  }
}

/** Requests that need a valid session are refused locally while it is known to be invalid, so a stale page cannot create a storm of failing calls or queue writes for later. */
export const blocksRequests = (state: SessionSnapshot) => state.phase === 'manual' || state.phase === 'failed' || state.phase === 'reconnecting'
