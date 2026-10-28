import type { ReactNode } from 'react'
import { Layers } from 'lucide-react'
import { TransactionCount } from './TransactionCount'
import { RoleIdentifier } from './RoleIdentifier'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
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
    <ModuleIcon moduleId={resolved || presentation.area} Icon={resolved || presentation.area ? undefined : Layers}/>
    {resolved && <span className="evidence-badge evidence-neutral">{resolved}</span>}
    {presentation.area&&presentation.area!==resolved&&<span className="evidence-badge evidence-neutral" title="SAP area label in the source description; canonical classification is unchanged.">{presentation.area}</span>}
    <span className="role-metadata-title">{caption}</span>{children}
  </div>
}

/** Single-role entry header shared by the role detail panel and both comparison layouts: module icon and code with the
 * transaction count below, the description beside them, and the copyable role identifier last. */
export function RoleEntryHeader({ code, name, description, tcodeCount, identifier, children }: { code?: string | null; name?: string | null; description?: string | null; tcodeCount: number; identifier: string; children?: ReactNode }) {
  const registry = useModuleDefinitions()
  const presentation = presentRoleDescription(description, Object.keys(registry))
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved || presentation.area)
  const caption = presentation.description || (resolved ? (visual.name === resolved ? name || resolved : visual.name) : 'Unclassified')
  return (
    <div className="role-entry-header">
      <div className="role-entry-module">
        <div className="role-entry-module-line">
          <ModuleIcon moduleId={resolved || presentation.area} Icon={resolved || presentation.area ? undefined : Layers} />
          {resolved && <span className="evidence-badge evidence-neutral">{resolved}</span>}
          {presentation.area && presentation.area !== resolved && <span className="evidence-badge evidence-neutral" title="SAP area label in the source description; canonical classification is unchanged.">{presentation.area}</span>}
        </div>
        <TransactionCount count={tcodeCount} />
      </div>
      <p className="role-entry-description">{caption}</p>
      <div className="role-entry-identifier"><RoleIdentifier value={identifier} />{children}</div>
    </div>
  )
}
