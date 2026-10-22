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
  const [page,setPage] = useState<'roles'|'users'|'releases'>('roles')
  const [visited, setVisited] = useState(() => new Set(['roles']))
  const scrollPositions = useRef<Record<string, number>>({})
  const navigate = (next: 'roles'|'users'|'releases') => { scrollPositions.current[page] = window.scrollY; setDetailRole(null); setVisited(previous => new Set([...previous, next])); setPage(next) }
  useLayoutEffect(() => { window.scrollTo(0, scrollPositions.current[page] || 0) }, [page])
  const [request,setRequest] = useState<{id:number;user?:string;role?:string;tcode?:string}>({id:0})
  const [releaseRequest,setReleaseRequest] = useState({ id:0, release:'' })
  const investigateUsers = (filter:{user?:string;role?:string;tcode?:string}) => {navigate('users');setRequest(previous=>({id:previous.id+1,...filter}))}
  const investigateRelease = (release:string) => {navigate('releases');setReleaseRequest(previous=>({id:previous.id+1,release}))}
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [detailRole, setDetailRole] = useState<string | null>(null)
  const [showComparison, setShowComparison] = useState(false)
  const [dataGeneration,setDataGeneration] = useState(0)
  const [lastLoaded, setLastLoaded] = useState<string | null>(null)

  const handleSelectRole = useCallback((name: string) => {
    setSelectedRoles(prev =>
      prev.includes(name) ? prev.filter(r => r !== name) : prev.length >= 5 ? prev : [...prev, name]
    )
  }, [])

  return (
    <AppLayout
      navigation={<>
      <nav aria-label="Main navigation" className="primary-navigation">
        {([['roles','Role Lookup',Search],['users','User Access',Users],['releases','Release Roles',FileCheck2]] as const).map(([key,label,Icon])=><button key={key} className="primary-nav-button" aria-current={page===key?'page':undefined} onClick={()=>navigate(key)}><Icon size={17} aria-hidden="true"/><span>{label}</span></button>)}
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
            selectedRoles={selectedRoles}
            onSelectRole={handleSelectRole}
            onViewDetail={n => setDetailRole(n)}
            onCompare={() => { if (selectedRoles.length >= 2) { setShowComparison(true); setDetailRole(null) } }}
          />
      }
      </div>
      {visited.has('users') && <div hidden={page!=='users'}><UserAccess key={request.id} initialUser={request.user} initialRole={request.role} initialTcode={request.tcode} onRole={setDetailRole} onRelease={investigateRelease}/></div>}
      {visited.has('releases') && <div hidden={page!=='releases'}><ReleaseRoles key={releaseRequest.id} initialRole={releaseRequest.release} onUser={user=>investigateUsers({user})}/></div>}
      <RoleDetailPanel parent={page === 'users' ? 'User Access' : page === 'releases' ? 'Release Roles' : 'Role Lookup'} roleName={detailRole} onClose={() => setDetailRole(null)} onUsers={role=>investigateUsers({role})} onTcodeUsers={tcode=>investigateUsers({tcode})}/>
    </AppLayout>
  )
}