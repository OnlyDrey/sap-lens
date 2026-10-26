import type { ReactNode } from 'react'
import { Layers } from 'lucide-react'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { useModuleVisual } from '@/components/Modules/ModuleRegistry'

/** Canonical backend module evidence only; descriptions never classify roles. */
export function RoleMetadata({ code, name, description, children }: {children?: ReactNode; code?: string | null; name?: string | null; description?: string | null }) {
  const text = description?.trim()
  const resolved = code && code !== 'UNCLASSIFIED' ? code : undefined
  const visual = useModuleVisual(resolved)
  const caption = text || (resolved ? visual.name === resolved ? name || resolved : visual.name : 'Unclassified')
  return <div className="role-module-metadata text-current">
    <ModuleIcon moduleId={resolved} Icon={resolved ? undefined : Layers}/>
    {resolved && <span className="evidence-badge evidence-neutral">{resolved}</span>}
    {children}<span className="role-metadata-title">{caption}</span>
  </div>
}
