/** Pure rules for starting SAP Lens: which failures are transient, how long to wait, and when a lost local session may be restored automatically.
 *  No DOM access except through the injected storage, so every rule is unit-tested. */

export type StartupFailure = 'unavailable' | 'session' | 'rejected' | 'failed'

export const RECOVERY_KEY = 'sap-lens-session-recovery'
/** One automatic restore per window. A second stale answer inside it means restoring does not help, and the person is told instead of looped. */
export const RECOVERY_WINDOW_MS = 60_000
/** Transient start-up conditions (the service is still starting or briefly unreachable) are retried this many times, about 15 seconds in total. */
export const MAX_TRANSIENT_RETRIES = 6

export interface ErrorShape { kind: string; status: number; detail?: unknown }
export interface Store { getItem(key: string): string | null; setItem(key: string, value: string): void }

/** No answer at all, or a gateway answer while the service starts. A 500 is a real failure (for example configuration or storage) and is not retried automatically. */
const answeredByApplication = (detail: unknown) => (typeof detail === 'string' && detail.trim() !== '') || (Array.isArray(detail) && detail.length > 0)
/** A 502/503/504 that carries the application's own problem detail was produced by SAP Lens (a real failure), not by a gateway while the service starts. */
export const isTransient = ({ kind, status, detail }: ErrorShape) => kind === 'network' || ((status === 502 || status === 503 || status === 504) && !answeredByApplication(detail))

export function classifyFailure(error: ErrorShape): StartupFailure {
  if (isTransient(error)) return 'unavailable'
  if (error.kind === 'session') return 'session'
  if (error.kind === 'authentication' || error.kind === 'permission') return 'rejected'
  return 'failed'
}

/** 0.5 s, 1 s, 2 s, 3 s, 4 s, then 5 s. */
export const retryDelay = (attempt: number) => Math.min(5000, [500, 1000, 2000, 3000, 4000][attempt] ?? 5000)

export const shouldRetry = (failureCount: number, error: ErrorShape) => isTransient(error) && failureCount < MAX_TRANSIENT_RETRIES

function lastAttempt(store: Store): number {
  try {
    const value = JSON.parse(store.getItem(RECOVERY_KEY) || 'null') as { at?: unknown } | null
    return typeof value?.at === 'number' ? value.at : -Infinity
  } catch { return -Infinity }
}

/** True when no automatic restore ran within the window. Unreadable storage counts as "may not": without a record the guard cannot bound the loop. */
export function mayRestoreAutomatically(store: Store | null, now: number): boolean {
  if (!store) return false
  try { store.getItem(RECOVERY_KEY) } catch { return false }
  return now - lastAttempt(store) > RECOVERY_WINDOW_MS
}

export function recordRestoreAttempt(store: Store | null, now: number): void {
  try { store?.setItem(RECOVERY_KEY, JSON.stringify({ at: now })) } catch { /* handled by mayRestoreAutomatically on the next start */ }
}

/** The labels of the normal start, in order. A recovery screen replaces them only when automatic restoring has failed. */
export const STARTUP_LABELS = { starting: 'Starting SAP Lens…', connecting: 'Connecting to local service…', restoring: 'Restoring workspace…' } as const
