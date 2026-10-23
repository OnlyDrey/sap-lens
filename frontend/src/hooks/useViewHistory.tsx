import { createContext, useContext, useEffect, useState, type ReactNode, type SetStateAction } from 'react'

export type ReleaseDrill = { status?: string; username?: string; role_search?: string; ungrouped?: boolean; role?: string; group?: string; document_type?: string; release_group?: string; strategy?: string }
type View = { kpiNavigation?: Partial<Record<'roles'|'users'|'releases',number>>; settingsTarget?: 'roles' | 'users' | 'employees' | 'diagnostics' | 'features'; page: 'dashboard' | 'roles' | 'users' | 'releases'; user: string; release: ReleaseDrill | null; detailRole: string | null; comparison: boolean; settings: boolean; releaseContext: string; userContext: { role?: string; tcode?: string } }
const paths = { dashboard: 'dashboard', roles: 'role-lookup', users: 'user-access', releases: 'release-roles' }
const defaults: View = { page: 'dashboard', user: '', release: null, detailRole: null, comparison: false, settings: false, releaseContext: '', userContext: {} }
function readView(): View {
  const stored = history.state?.sapLensView as View | undefined
  const path = location.hash.slice(2).split('?')[0]
  const page = Object.entries(paths).find(([, value]) => value === path)?.[0] as View['page'] | undefined
  return stored && ['dashboard', 'roles', 'users', 'releases'].includes(stored.page) ? { ...defaults, ...stored } : { ...defaults, page: page || 'dashboard' }
}
export function initializeViewHistory() {
    const current = readView()
    const url = `#/${paths[current.page]}`
    if (!history.state?.sapLensView) {
      // Boundary is the same meaningful view, never a bootstrap document. Back at
      // the app's first record stays here; normal Back/Forward is untouched.
      history.replaceState({ sapLensView: current, sapLensBoundary:true }, '', url)
      history.pushState({ sapLensView: current }, '', url)
    } else history.replaceState({ ...history.state, sapLensView: current }, '', url)
}
const Context = createContext<{ view: View; change: (patch: Partial<View>, replace?: boolean) => void } | null>(null)
/** Only navigation identities live in session history; CSV contents and credentials never do. */
export function ViewHistory({ children }: { children: ReactNode }) {
  const [view, setView] = useState(readView)
  useEffect(() => {
    const pop = (event: PopStateEvent) => {
      if (event.state?.sapLensBoundary) { history.forward(); return }
      setView(readView())
    }
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [])
  const change = (patch: Partial<View>, replace = false) => {
    const next = { ...readView(), ...patch }
    if (JSON.stringify(next) === JSON.stringify(readView())) return
    history[replace ? 'replaceState' : 'pushState']({ sapLensView: next }, '', `#/${paths[next.page]}`)
    setView(next)
  }
  return <Context.Provider value={{ view, change }}>{children}</Context.Provider>
}
export function useViewHistory() {
  const context = useContext(Context)
  if (!context) throw new Error('View history provider is missing')
  return context
}
export function useHistoryValue<K extends keyof View>(key: K): [View[K], (value: SetStateAction<View[K]>) => void] {
  const { view, change } = useViewHistory()
  return [view[key], value => change({ [key]: typeof value === 'function' ? (value as (old: View[K]) => View[K])(view[key]) : value })]
}
