import { useState, useCallback } from 'react'
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
  const [request,setRequest] = useState<{id:number;user?:string;role?:string;tcode?:string;release?:string}>({id:0})
  const investigateUsers = (filter:{user?:string;role?:string;tcode?:string}) => {setDetailRole(null);setPage('users');setRequest(previous=>({id:previous.id+1,...filter}))}
  const investigateRelease = (release:string) => {setPage('releases');setRequest(previous=>({id:previous.id+1,release}))}
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
      <nav aria-label="Main navigation" className="flex flex-wrap gap-2 mb-5">
        {([['roles','Role Lookup',Search],['users','User Access',Users],['releases','Release Roles',FileCheck2]] as const).map(([key,label,Icon])=><button key={key} className="settings-secondary-button" aria-current={page===key?'page':undefined} onClick={()=>setPage(key)}><Icon size={17} aria-hidden="true"/>{label}</button>)}
      </nav>
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
      {page==='users'&&<UserAccess key={request.id} initialUser={request.user} initialRole={request.role} initialTcode={request.tcode} onRole={setDetailRole} onRelease={investigateRelease}/>}
      {page==='releases'&&<ReleaseRoles key={request.id} initialRole={request.release} onUser={user=>investigateUsers({user})}/>}
      <RoleDetailPanel roleName={detailRole} onClose={() => setDetailRole(null)} onUsers={role=>investigateUsers({role})} onTcodeUsers={tcode=>investigateUsers({tcode})}/>
    </AppLayout>
  )
}