import { Layers } from 'lucide-react'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { useModuleVisual } from '@/components/Modules/ModuleRegistry'

/** Display only explicit module evidence; never infer a module from a role identifier. */
export function RoleMetadata({ code, name }: { code?: string | null; name?: string | null }) {
  const known = Boolean(code && code !== 'UNCLASSIFIED')
  const visual = useModuleVisual(code)
  return <div className="role-module-metadata text-current">
    <ModuleIcon moduleId={code} Icon={known ? undefined : Layers}/>
    {known && <span className="evidence-badge evidence-neutral">{code}</span>}
    <span>{known ? visual.name === code ? name || code : visual.name : 'Unclassified'}</span>
  </div>
}
