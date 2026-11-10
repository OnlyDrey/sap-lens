import { useSyncExternalStore } from 'react'
import { initialSession, nextSession, type SessionEvent, type SessionSnapshot } from '@/lib/sessionState'

let snapshot: SessionSnapshot = initialSession()
const listeners = new Set<() => void>()
export const sessionSnapshot = () => snapshot
export function recordSession(event: SessionEvent) {
  const next = nextSession(snapshot, event)
  if (next === snapshot) return
  snapshot = next
  listeners.forEach((listener) => listener())
}
/** The single shared view of the local session; never reads or exposes the capability itself. */
export const useSession = () => useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener) } }, sessionSnapshot)
