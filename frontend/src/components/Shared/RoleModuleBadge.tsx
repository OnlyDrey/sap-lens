import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import { moduleOfRoles, useRoleModules } from '@/hooks/useRoleModules'

/** Compact module identity for a role record that matched catalogue roles; renders nothing without unambiguous evidence. */
export function RoleModuleBadge({ catalogueRoles }: { catalogueRoles?: readonly string[] }) {
  const code = moduleOfRoles(useRoleModules(), catalogueRoles)
  return code ? <ModuleBadge moduleId={code} variant="compact" /> : null
}
