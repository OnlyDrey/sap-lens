import {SodWorkspace} from '@/components/Sod/SodWorkspace'
import {applicationToken} from '@/api/client'
import { MainNavigation, MainNavigationGroup, MainNavigationItem } from '@/components/Shared/Navigation'
import { SOD_VIEWS, USER_ACCESS_VIEWS } from '@/lib/navigationItems'
import { pageHref, sodHref, useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { userAccessHref } from '@/hooks/useViewHistory'
import { DISCARD_PROMPT, settingsDirty } from '@/lib/settingsGuard'
import { useState, useCallback, useRef, useLayoutEffect, useEffect } from 'react'
import { AppLayout } from '@/components/Layout/AppLayout'
import { RoleList } from '@/components/RoleList/RoleList'
import { RoleDetailPanel } from '@/components/RoleDetail/RoleDetailPanel'
import { ComparisonView } from '@/components/RoleComparison/ComparisonView'
import { MappingAvailability } from '@/components/Access/MappingAvailability'
import { UserAccess } from '@/components/Access/UserAccess'
import { ReleaseRoles } from '@/components/Access/ReleaseRoles'
import { Search, Users, FileCheck2, LayoutDashboard, ShieldCheck } from 'lucide-react'
import { Dashboard } from '@/components/Dashboard'
import { useTheme } from '@/hooks/useTheme'
import { useQuery } from '@tanstack/react-query'
import { fetchConfiguration } from '@/api/configuration'

export function App() {
  const { isDark, toggle } = useTheme()
  const [page] = useHistoryValue('page')
  const [settingsOpen] = useHistoryValue('settings')
  const [kpiNavigation] = useHistoryValue('kpiNavigation')
  const [catalogueArea] = useHistoryValue('catalogueArea')
  const { change } = useViewHistory()
  const configuration = useQuery({ queryKey: ['configuration'], queryFn: fetchConfiguration })
  // Unknown (still loading or unreadable) keeps the entry; only an explicit saved "off" hides it.
  const sodEnabled = configuration.data?.settings.features?.sod !== false
  useEffect(()=>{
    const open=()=>{if(window.pywebview?.api.desktop_runtime)change({settings:true})}
    const ready=()=>{void window.pywebview?.api.desktop_frontend_ready?.(applicationToken()).catch(()=>{})}
    window.addEventListener('sap-lens-open-settings',open);window.addEventListener('pywebviewready',ready)
    window.__sapLensSettingsReady=true;ready()
    return()=>{window.__sapLensSettingsReady=false;window.removeEventListener('sap-lens-open-settings',open);window.removeEventListener('pywebviewready',ready)}
  },[change])
  const [visited, setVisited] = useState(() => new Set([page]))
  const scrollPositions = useRef<Record<string, number>>({})
  const navigate = (next: 'dashboard'|'roles'|'users'|'releases'|'sod') => { scrollPositions.current[page] = window.scrollY; setVisited(previous => new Set([...previous, next])); change({page:next, detailRole:null, settings:false}) }
  const [accessMode] = useHistoryValue('accessMode'), [sodView] = useHistoryValue('sodView')
  /** A submenu entry opens one page of a module; unsaved Settings edits are confirmed first, like every other destination. */
  const openPage = (next: 'users' | 'sod', patch: Record<string, unknown>) => { if (settingsDirty() && !window.confirm(DISCARD_PROMPT)) return; scrollPositions.current[page] = window.scrollY; setVisited(previous => new Set([...previous, next])); change({ page: next, detailRole: null, settings: false, ...patch } as never) }
  const submenus = {
    users: USER_ACCESS_VIEWS.map(({ value, label, icon }) => ({ value, label, icon, href: userAccessHref(value), active: page === 'users' && !settingsOpen && (accessMode || 'directory') === value, onSelect: () => openPage('users', { accessMode: value, user: '', userContext: {} }) })),
    sod: SOD_VIEWS.map(({ value, label, icon }) => ({ value, label, icon, href: sodHref(value), active: page === 'sod' && !settingsOpen && (sodView || 'overview') === value, onSelect: () => openPage('sod', { sodView: value }) })),
  } as const
  /** Settings stay open until the destination is confirmed when they hold unsaved edits. */
  /** The main link opens the module: from another module it returns to where that module was left (open record, filters); on the module itself it opens the main page (User directory, SoD Overview). Other pages are reached through the submenu. */
  const go = (next: 'dashboard'|'roles'|'users'|'releases'|'sod') => { if (settingsDirty() && !window.confirm(DISCARD_PROMPT)) return; if (page === next && !settingsOpen && (next === 'users' || next === 'sod')) openPage(next, next === 'users' ? { accessMode: 'directory', user: '', userContext: {} } : { sodView: 'overview' }); else navigate(next) }
  useLayoutEffect(() => { setVisited(previous => new Set([...previous, page])); window.scrollTo(0, scrollPositions.current[page] || 0) }, [page])
  const [userContext] = useHistoryValue('userContext')
  const [selectedUser] = useHistoryValue('user')
  const [releaseDrill] = useHistoryValue('release')
  const [releaseContext] = useHistoryValue('releaseContext')
  const investigateUsers = (filter:{user?:string;role?:string;tcode?:string}) => { setVisited(previous => new Set([...previous, 'users'])); change({accessMode:'directory',page:'users', user:filter.user || '', userContext:{role:filter.role,tcode:filter.tcode},detailRole:null,settings:false}) }
  const investigateRelease = (release:string) => { setVisited(previous => new Set([...previous, 'releases'])); change({page:'releases', release:{role:release,status:'all'},releaseContext:release,detailRole:null,settings:false}) }
  const [catalogueOrder, setCatalogueOrder] = useState<string[]>([])
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [detailRole, setDetailRole] = useHistoryValue('detailRole')
  const [showComparison, setShowComparison] = useHistoryValue('comparison')
  const [dataGeneration,setDataGeneration] = useState(0)

  const handleSelectRole = useCallback((name: string) => {
    setSelectedRoles(prev =>
      prev.includes(name) ? prev.filter(r => r !== name) : prev.length >= 5 ? prev : [...prev, name]
    )
  }, [])

  const cataloguePosition = detailRole ? catalogueOrder.indexOf(detailRole) : -1
  const catalogueNavigation = {
    index: cataloguePosition,
    total: catalogueOrder.length,
    onPrevious: cataloguePosition > 0 ? () => setDetailRole(catalogueOrder[cataloguePosition - 1]) : undefined,
    onNext: cataloguePosition >= 0 && cataloguePosition + 1 < catalogueOrder.length ? () => setDetailRole(catalogueOrder[cataloguePosition + 1]) : undefined,
    missing: cataloguePosition < 0,
  }

  return (
    <AppLayout
      navigation={<>
      <MainNavigation>
        {([['dashboard','Dashboard',LayoutDashboard],['roles','Role Lookup',Search],['users','User Access',Users],['releases','Release Roles',FileCheck2],['sod','SoD',ShieldCheck]] as const).filter(([key])=>key!=='sod'||sodEnabled).map(([key,label,Icon])=>{const props={label,icon:<Icon size={17} aria-hidden="true"/>,active:page===key&&!settingsOpen,href:pageHref(key),onNavigate:()=>go(key)};return key==='users'||key==='sod'?<MainNavigationGroup key={key} {...props} items={[...submenus[key]]}/>:<MainNavigationItem key={key} {...props}/>})}
      </MainNavigation>
      </>}
      onDataChanged={() => {
        setDataGeneration(value=>value+1)
        setSelectedRoles([])
        setDetailRole(null)
        setShowComparison(false)
      }}
      isDark={isDark}
      onToggleTheme={toggle}>
      {page === 'dashboard' && <Dashboard/>}
      {page === 'sod' && <SodWorkspace/>}
      {visited.has('roles') && <div className={page==='roles'?'':'hidden'}>
      {showComparison
        ? <ComparisonView roleNames={selectedRoles} onBack={() => setShowComparison(false)} />
        : <RoleList key={`${dataGeneration}:${kpiNavigation?.roles || 0}`}
            initialArea={catalogueArea}
            onFilteredRoles={setCatalogueOrder}
            selectedRoles={selectedRoles}
            onSelectRole={handleSelectRole}
            onViewDetail={n => setDetailRole(n)}
            onCompare={() => { if (selectedRoles.length >= 2) { setShowComparison(true); setDetailRole(null) } }}
          />
      }
      </div>}
      {visited.has('users') && <div hidden={page!=='users'}><MappingAvailability><UserAccess key={`${JSON.stringify(userContext)}:${kpiNavigation?.users || 0}`} initialUser={selectedUser} initialRole={userContext.role} initialTcode={userContext.tcode} onRole={setDetailRole} onRelease={investigateRelease}/></MappingAvailability></div>}
      {visited.has('releases') && <div hidden={page!=='releases'}><MappingAvailability><ReleaseRoles key={`${releaseContext}:${kpiNavigation?.releases || 0}`} initialRole={releaseDrill?.role || ''} onUser={user=>investigateUsers({user})}/></MappingAvailability></div>}
      <RoleDetailPanel navigation={page === 'roles' && detailRole ? catalogueNavigation : undefined} parent={page === 'sod' ? 'SoD' : page === 'users' ? 'User Access' : page === 'releases' ? 'Release Roles' : 'Role Lookup'} roleName={detailRole} onClose={() => setDetailRole(null)} onUsers={role=>investigateUsers({role})} onTcodeUsers={tcode=>investigateUsers({tcode})}/>
    </AppLayout>
  )
}