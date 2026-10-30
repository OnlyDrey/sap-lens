import { useCallback, useSyncExternalStore } from 'react'

/** A per-browser convenience (for example an expanded or collapsed section). Never holds evidence, decisions or anything the backend owns; storage failures fall back to the default. */
const listeners = new Set<() => void>()
const read = (key: string) => { try { return localStorage.getItem(key) } catch { return null } }
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export function useLocalPreference(key: string, fallback: string): [string, (value: string) => void] {
  const value = useSyncExternalStore(subscribe, () => read(key) ?? fallback)
  const set = useCallback((next: string) => {
    try { localStorage.setItem(key, next) } catch { /* optional convenience */ }
    listeners.forEach(listener => listener())
  }, [key])
  return [value, set]
}
