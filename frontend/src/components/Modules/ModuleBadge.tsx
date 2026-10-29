import { Hash } from 'lucide-react'
import type { CSSProperties } from 'react'
import { isHex } from '@/lib/theme'
import { ModuleIcon } from './ModuleIcon'
import { useModuleVisual } from './ModuleRegistry'

/**
 * One SAP module identity: icon and abbreviation on the same tinted surface, as in the SAP Modules settings.
 * Only a module known from canonical evidence is shown; unknown roles are never assigned an identity.
 */
export function ModuleBadge({ moduleId, variant = 'standard', showUnclassified = false, selected = false, disabled = false }: {
  moduleId?: string | null
  variant?: 'standard' | 'compact'
  /** Render a neutral "Unclassified" badge instead of nothing when the module is unknown. */
  showUnclassified?: boolean
  selected?: boolean
  disabled?: boolean
}) {
  const known = !!moduleId && moduleId !== 'UNCLASSIFIED'
  const visual = useModuleVisual(known ? moduleId : undefined)
  if (!known && !showUnclassified) return null
  const color = isHex(visual.color) ? visual.color : '#64748b'
  return (
    <span
      className="module-badge"
      data-variant={variant}
      data-selected={selected || undefined}
      data-disabled={disabled || undefined}
      data-module={known ? moduleId : undefined}
      style={{ '--module-color': color } as CSSProperties}
      title={known ? visual.name : 'No module classification in the imported evidence'}
    >
      {known ? <ModuleIcon moduleId={moduleId} size="small" disabled={disabled} /> : <ModuleIcon Icon={Hash} color="#8793a2" size="small" />}
      <span className="module-badge-label">{known ? moduleId : 'Unclassified'}</span>
    </span>
  )
}
