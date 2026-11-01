import { useCallback, useSyncExternalStore } from 'react'

/**
 * A per-browser convenience (for example an expanded or collapsed section). Never holds evidence, decisions or anything the backend owns; storage failures fall back to the default.
 * `session` keeps the choice for the current application session only (it is back to the default in a new window or after the application restarts); `local` keeps it until it is changed.
 */
const listeners = new Set<() => void>()
const store = (scope: 'local' | 'session') => (scope === 'session' ? sessionStorage : localStorage)
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export function useLocalPreference(key: string, fallback: string, scope: 'local' | 'session' = 'local'): [string, (value: string) => void] {
  const read = () => { try { return store(scope).getItem(key) } catch { return null } }
  const value = useSyncExternalStore(subscribe, () => read() ?? fallback)
  const set = useCallback((next: string) => {
    try { store(scope).setItem(key, next) } catch { /* optional convenience */ }
    listeners.forEach(listener => listener())
  }, [key, scope])
  return [value, set]
}
