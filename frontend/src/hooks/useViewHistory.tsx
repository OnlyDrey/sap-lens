import { createContext, useContext, useEffect, useState, type ReactNode, type SetStateAction } from 'react'

export type ReleaseDrill = { status?: string; username?: string; role_search?: string; ungrouped?: boolean; role?: string; group?: string; document_type?: string; release_group?: string; strategy?: string }
export type SodFilterState = Record<string,string|boolean|number|string[]>
export type SodView = 'overview'|'risk-matrix'|'activity-matrix'|'explorer'|'reviews'|'periods'|'reports'
export type SodExplorerTable = 'user_risk'|'user_activity'|'access_list'|'lookup'|'roles'
type View = { userTrail?:string[]; sodView?:SodView; sodFilters?:Record<string,SodFilterState>; sodContext?:string; sodSubject?:{user:string;risk?:string;activity?:string}|null; sodExplorer?:SodExplorerTable; sodReviews?:'queue'|'remediation'; assignmentBand?:string; catalogueArea?:string; accountReviewFilters?:{search:string;license:string;state:string;sort:string;descending:boolean}; userComparison?:{sort?:string;descending?:boolean;a:string;b:string;validity:string;kind:string;difference:string;search:string;area:string}; accessMode?: 'directory'|'review'|'compare'; reviewFinding?: string; kpiNavigation?: Partial<Record<'roles'|'users'|'releases',number>>; settingsTarget?: 'roles' | 'users' | 'employees' | 'sod' | 'diagnostics' | 'features'; page: 'dashboard' | 'roles' | 'users' | 'releases' | 'sod'; user: string; release: ReleaseDrill | null; detailRole: string | null; comparison: boolean; settings: boolean; releaseContext: string; userContext: { role?: string; tcode?: string } }
const paths = { dashboard: 'dashboard', roles: 'role-lookup', users: 'user-access', releases: 'release-roles', sod:'sod' }
const defaults: View = { page: 'dashboard', user: '', release: null, detailRole: null, comparison: false, settings: false, releaseContext: '', userContext: {} }
export function userAccessHref(mode:'directory'|'review'|'compare') {return '#/user-access'+(mode==='directory'?'':mode==='review'?'/account-review':'/compare')}
/** Direct link to one SAP user in User Access; the same route is produced when a user is opened in the app. */
export function userHref(username:string){return '#/user-access/user/'+encodeURIComponent(username)}
export function pageHref(page:'dashboard'|'roles'|'users'|'releases'|'sod'){return page==='users'?userAccessHref('directory'):page==='sod'?sodHref('overview'):`#/${paths[page]}`}
export function sodHref(view:SodView){return '#/sod'+(view==='overview'?'':`/${view}`)}
function viewUrl(view:View) {
 const base=view.page==='sod'?sodHref(view.sodView||'overview'):view.page==='users'?((view.accessMode||'directory')==='directory'&&view.user?userHref(view.user):userAccessHref(view.accessMode||'directory')):`#/${paths[view.page]}`
 const query=location.hash.startsWith('#/')?location.hash.split('?').slice(1).join('?'):''
 return base+(query?'?'+query:'')
}
function readView(): View {
 const stored=history.state?.sapLensView as View|undefined
 const segments=location.hash.slice(2).split('?')[0].split('/')
 const page=Object.entries(paths).find(([,value])=>value===segments[0])?.[0] as View['page']|undefined
 const base=stored&&['dashboard','roles','users','releases','sod'].includes(stored.page)?{...defaults,...stored}:{...defaults,page:page||'dashboard'}
 if(page)base.page=page
 if(page==='sod'){
  const part=segments[1],views:SodView[]=['risk-matrix','activity-matrix','explorer','reviews','periods','reports']
  base.sodView=views.find(item=>item===part)||(part==='users'||part==='roles'?'explorer':'overview')
  if(part==='users')base.sodExplorer='user_risk'
  if(part==='roles')base.sodExplorer='roles'
 }
 if(page==='users'&&segments[1]){
  base.accessMode=segments[1]==='account-review'?'review':segments[1]==='compare'?'compare':'directory'
  if(segments[1]==='user'&&segments[2]){try{base.user=decodeURIComponent(segments[2])}catch{base.user=segments[2]}}
 }
 if(page==='users'&&(base.accessMode||'directory')==='directory'&&segments[1]!=='user')base.user=''
 return base
}
export function initializeViewHistory() {
    const current = readView()
    const url = viewUrl(current)
    if (!history.state?.sapLensView) {
      // Boundary is the same meaningful view, never a bootstrap document. Back at
      // the app's first record stays here; normal Back/Forward is untouched.
      history.replaceState({ sapLensView: current, sapLensBoundary:true }, '', url)
      history.pushState({ sapLensView: current }, '', url)
    } else history.replaceState({ ...history.state, sapLensView: current }, '', url)
}
const Context = createContext<{ view: View; change: (patch: Partial<View>, replace?: boolean) => void } | null>(null)
/** Navigation identities and bounded comparison controls live in session history; result datasets and credentials never do. */
export function ViewHistory({ children }: { children: ReactNode }) {
  const [view, setView] = useState(readView)
  useEffect(() => {
    const pop = (event: PopStateEvent) => {
      if (event.state?.sapLensBoundary) { history.forward(); return }
      setView(readView())
    }
    const hash=()=>{if(!history.state?.sapLensBoundary)setView(readView())}
    window.addEventListener('popstate', pop)
    window.addEventListener('hashchange',hash)
    return () => {window.removeEventListener('popstate',pop);window.removeEventListener('hashchange',hash)}
  }, [])
  const change = (patch: Partial<View>, replace = false) => {
    const next = { ...readView(), ...patch }
    if (JSON.stringify(next) === JSON.stringify(readView())) return
    history[replace ? 'replaceState' : 'pushState']({ sapLensView: next }, '', viewUrl(next))
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
