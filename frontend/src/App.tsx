import { useState, useCallback } from 'react'
import { AppLayout } from '@/components/Layout/AppLayout'
import { RoleList } from '@/components/RoleList/RoleList'
import { RoleDetailPanel } from '@/components/RoleDetail/RoleDetailPanel'
import { ComparisonView } from '@/components/RoleComparison/ComparisonView'
import { useTheme } from '@/hooks/useTheme'

export function App() {
  const { isDark, toggle } = useTheme()
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [detailRole, setDetailRole] = useState<string | null>(null)
  const [showComparison, setShowComparison] = useState(false)
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
      isDark={isDark}
      onToggleTheme={toggle}>
      {showComparison
        ? <ComparisonView roleNames={selectedRoles} onBack={() => setShowComparison(false)} />
        : <RoleList
            selectedRoles={selectedRoles}
            onSelectRole={handleSelectRole}
            onViewDetail={n => setDetailRole(n)}
            onCompare={() => { if (selectedRoles.length >= 2) { setShowComparison(true); setDetailRole(null) } }}
          />
      }
      <RoleDetailPanel roleName={detailRole} onClose={() => setDetailRole(null)} />
    </AppLayout>
  )
}