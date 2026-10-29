import type { ReactNode } from 'react'
import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import { RoleEntry } from './RoleEntry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { useModuleDefinitions, useModuleVisual } from '@/components/Modules/ModuleRegistry'

/** Canonical backend module evidence only; descriptions never classify roles. One badge: a module code that merely repeats the description label is not shown twice. */
export function RoleMetadata({ code, name, description, children }: { children?: ReactNode; code?: string | null; name?: string | null; description?: string | null }) {
  const registry = useModuleDefinitions()
  const presentation = presentRoleDescription(description, Object.keys(registry))
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved || presentation.area)
  const caption = presentation.description || (resolved ? (visual.name === resolved ? name || resolved : visual.name) : 'Unclassified')
  return (
    <div className="role-module-metadata text-current">
      <ModuleBadge moduleId={resolved || presentation.area} showUnclassified />
      {resolved && presentation.area && presentation.area !== resolved && (
        <span className="evidence-badge evidence-neutral" title="SAP area label in the source description; canonical classification is unchanged.">{presentation.area}</span>
      )}
      <span className="role-metadata-title">{caption}</span>{children}
    </div>
  )
}

/** Single-role entry shared by the role detail panel and both comparison layouts: the standard role presentation in its compact
 * variant with the transaction count at the top right. */
export function RoleEntryHeader({ code, name, description, tcodeCount, identifier, children, actions }: { code?: string | null; name?: string | null; description?: string | null; tcodeCount: number; identifier: string; children?: ReactNode; actions?: ReactNode }) {
  const registry = useModuleDefinitions()
  const presentation = presentRoleDescription(description, Object.keys(registry))
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved || presentation.area)
  const title = presentation.description || (resolved ? (visual.name === resolved ? name || resolved : visual.name) : 'Unclassified')
  return (
    <RoleEntry density="compact" moduleCode={resolved || presentation.area} showUnclassified title={title} identifier={identifier} tcodeCount={tcodeCount} countPlacement="top" actions={actions}>
      {children}
    </RoleEntry>
  )
}
