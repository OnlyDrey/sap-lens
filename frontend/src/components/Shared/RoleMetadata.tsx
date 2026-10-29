import type { ReactNode } from 'react'
import { TransactionCount } from './TransactionCount'
import { RoleIdentifier } from './RoleIdentifier'
import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import {presentRoleDescription} from '@/lib/rolePresentation'
import {useModuleDefinitions} from '@/components/Modules/ModuleRegistry'
import { useModuleVisual } from '@/components/Modules/ModuleRegistry'

/** Canonical backend module evidence only; descriptions never classify roles. */
export function RoleMetadata({ code, name, description, children }: {children?: ReactNode; code?: string | null; name?: string | null; description?: string | null }) {
  const registry=useModuleDefinitions()
  const presentation=presentRoleDescription(description,Object.keys(registry))
  const text=presentation.description
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved || presentation.area)
  const caption = text || (resolved ? visual.name === resolved ? name || resolved : visual.name : 'Unclassified')
  return <div className="role-module-metadata text-current">
    <ModuleBadge moduleId={resolved || presentation.area} showUnclassified />
    {presentation.area&&presentation.area!==resolved&&<span className="evidence-badge evidence-neutral" title="SAP area label in the source description; canonical classification is unchanged.">{presentation.area}</span>}
    <span className="role-metadata-title">{caption}</span>{children}
  </div>
}

/** Single-role entry header shared by the role detail panel and both comparison layouts: the module identity first with the
 * transaction count at the top right, then the description, then the copyable role identifier last (DOM order = visual order). */
export function RoleEntryHeader({ code, name, description, tcodeCount, identifier, children }: { code?: string | null; name?: string | null; description?: string | null; tcodeCount: number; identifier: string; children?: ReactNode }) {
  const registry = useModuleDefinitions()
  const presentation = presentRoleDescription(description, Object.keys(registry))
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved || presentation.area)
  const caption = presentation.description || (resolved ? (visual.name === resolved ? name || resolved : visual.name) : 'Unclassified')
  return (
    <div className="role-entry-header">
      <div className="role-entry-top">
        <ModuleBadge moduleId={resolved || presentation.area} showUnclassified />
        {presentation.area && presentation.area !== resolved && <span className="evidence-badge evidence-neutral" title="SAP area label in the source description; canonical classification is unchanged.">{presentation.area}</span>}
        <span className="role-entry-count"><TransactionCount count={tcodeCount} /></span>
      </div>
      <p className="role-entry-description">{caption}</p>
      <div className="role-entry-identifier"><RoleIdentifier value={identifier} />{children}</div>
    </div>
  )
}
