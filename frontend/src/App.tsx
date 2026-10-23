import { useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { useState, useCallback, useRef, useLayoutEffect } from 'react'
import { AppLayout } from '@/components/Layout/AppLayout'
import { RoleList } from '@/components/RoleList/RoleList'
import { RoleDetailPanel } from '@/components/RoleDetail/RoleDetailPanel'
import { ComparisonView } from '@/components/RoleComparison/ComparisonView'
import { UserAccess } from '@/components/Access/UserAccess'
import { ReleaseRoles } from '@/components/Access/ReleaseRoles'
import { Search, Users, FileCheck2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'

export function App() {
  const { isDark, toggle } = useTheme()
  const [page] = useHistoryValue('page')
  const { change } = useViewHistory()
  const [visited, setVisited] = useState(() => new Set([page]))
  const scrollPositions = useRef<Record<string, number>>({})
  const navigate = (next: 'roles'|'users'|'releases') => { scrollPositions.current[page] = window.scrollY; setVisited(previous => new Set([...previous, next])); change({page:next, detailRole:null}) }
  useLayoutEffect(() => { setVisited(previous => new Set([...previous, page])); window.scrollTo(0, scrollPositions.current[page] || 0) }, [page])
  const [userContext] = useHistoryValue('userContext')
  const [selectedUser] = useHistoryValue('user')
  const [releaseDrill] = useHistoryValue('release')
  const [releaseContext] = useHistoryValue('releaseContext')
  const investigateUsers = (filter:{user?:string;role?:string;tcode?:string}) => { setVisited(previous => new Set([...previous, 'users'])); change({page:'users', user:filter.user || '', userContext:{role:filter.role,tcode:filter.tcode},detailRole:null,settings:false}) }
  const investigateRelease = (release:string) => { setVisited(previous => new Set([...previous, 'releases'])); change({page:'releases', release:{role:release,status:'all'},releaseContext:release,detailRole:null,settings:false}) }
  const [catalogueOrder, setCatalogueOrder] = useState<string[]>([])
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [detailRole, setDetailRole] = useHistoryValue('detailRole')
  const [showComparison, setShowComparison] = useHistoryValue('comparison')
  const [dataGeneration,setDataGeneration] = useState(0)
  const [lastLoaded, setLastLoaded] = useState<string | null>(null)

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
      <nav aria-label="Main navigation" className="primary-navigation">
        {([['roles','Role Lookup',Search],['users','User Access',Users],['releases','Release Roles',FileCheck2]] as const).map(([key,label,Icon])=><button key={key} title={label} className="primary-nav-button" aria-current={page===key?'page':undefined} onClick={()=>navigate(key)}><Icon size={17} aria-hidden="true"/><span>{label}</span></button>)}
      </nav>
      </>}
      lastLoaded={lastLoaded}
      onRefresh={() => setLastLoaded(new Date().toISOString())}
      onDataChanged={() => {
        setDataGeneration(value=>value+1)
        setSelectedRoles([])
        setDetailRole(null)
        setShowComparison(false)
        setLastLoaded(new Date().toISOString())
      }}
      isDark={isDark}
      onToggleTheme={toggle}>
      <div className={page==='roles'?'':'hidden'}>
      {showComparison
        ? <ComparisonView roleNames={selectedRoles} onBack={() => setShowComparison(false)} />
        : <RoleList key={dataGeneration}
            onFilteredRoles={setCatalogueOrder}
            selectedRoles={selectedRoles}
            onSelectRole={handleSelectRole}
            onViewDetail={n => setDetailRole(n)}
            onCompare={() => { if (selectedRoles.length >= 2) { setShowComparison(true); setDetailRole(null) } }}
          />
      }
      </div>
      {visited.has('users') && <div hidden={page!=='users'}><UserAccess key={JSON.stringify(userContext)} initialUser={selectedUser} initialRole={userContext.role} initialTcode={userContext.tcode} onRole={setDetailRole} onRelease={investigateRelease}/></div>}
      {visited.has('releases') && <div hidden={page!=='releases'}><ReleaseRoles key={releaseContext} initialRole={releaseDrill?.role || ''} onUser={user=>investigateUsers({user})}/></div>}
      <RoleDetailPanel navigation={page === 'roles' && detailRole ? catalogueNavigation : undefined} parent={page === 'users' ? 'User Access' : page === 'releases' ? 'Release Roles' : 'Role Lookup'} roleName={detailRole} onClose={() => setDetailRole(null)} onUsers={role=>investigateUsers({role})} onTcodeUsers={tcode=>investigateUsers({tcode})}/>
    </AppLayout>
  )
}