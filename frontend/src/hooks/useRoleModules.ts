import { useMemo } from 'react'
import { useRoles } from './useRoles'

/** Module evidence per catalogue role, from the cached catalogue list (no new request when Role Lookup has loaded it). */
export function useRoleModules() {
  const roles = useRoles()
  return useMemo(() => new Map((roles.data ?? []).map(role => [role.agr_name, role.module_ambiguous ? null : role.function_key] as const)), [roles.data])
}

/** The module shared by every matched catalogue role, or undefined: unmatched, ambiguous or conflicting evidence is never classified. */
export function moduleOfRoles(modules: Map<string, string | null>, names: readonly string[] | undefined) {
  if (!names?.length) return undefined
  const found = new Set(names.map(name => modules.get(name) ?? null))
  const [only] = found
  return found.size === 1 && only && only !== 'UNCLASSIFIED' ? only : undefined
}

/** Catalogue description per role name, from the same cached list. Roles without catalogue evidence have none. */
export function useRoleDescriptions() {
  const roles = useRoles()
  return useMemo(() => new Map((roles.data ?? []).map(role => [role.agr_name, role.text || ''] as const)), [roles.data])
}
