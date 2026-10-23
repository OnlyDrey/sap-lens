import { Layers } from 'lucide-react'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { useModuleDefinitions, useModuleVisual } from '@/components/Modules/ModuleRegistry'

/** Description prefixes are display evidence only, resolved through the existing registry.
 * Explicit source module metadata wins. No role-name parsing or persistent classification. */
export function RoleMetadata({ code, name, description }: { code?: string | null; name?: string | null; description?: string | null }) {
  const registry = useModuleDefinitions()
  const text = description?.trim()
  const parts = text?.split(/\s+[-–—]\s+/) || []
  const prefix = parts.length > 1 ? parts[0].toUpperCase() : ''
  const candidates = Object.values(registry).filter(item => item.id.toUpperCase() === prefix || item.aliases.some(alias => alias.toUpperCase() === prefix))
  const describedCode = candidates.length === 1 && candidates[0].id !== 'UNCLASSIFIED' ? candidates[0].id : undefined
  const explicitCode = code && code !== 'UNCLASSIFIED' ? code : undefined
  const resolved = explicitCode || describedCode
  const visual = useModuleVisual(resolved)
  const caption = text ? describedCode && describedCode === resolved ? parts.slice(1).join(' · ') : text
    : resolved ? visual.name === resolved ? name || resolved : visual.name : 'Unclassified'
  return <div className="role-module-metadata text-current">
    <ModuleIcon moduleId={resolved} Icon={resolved ? undefined : Layers}/>
    {resolved && <span className="evidence-badge evidence-neutral">{resolved}</span>}
    <span className="role-metadata-title">{caption}</span>
  </div>
}
