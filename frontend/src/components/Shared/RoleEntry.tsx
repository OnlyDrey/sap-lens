import type { ReactNode } from 'react'
import { Layers } from 'lucide-react'
import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import { useModuleDefinitions } from '@/components/Modules/ModuleRegistry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { RoleIdentifier } from './RoleIdentifier'
import { TruncatedText } from './TruncatedText'
import { TransactionCount } from './TransactionCount'
import { cn } from '@/lib/utils'

export type RoleEntryDensity = 'compact' | 'standard' | 'detailed'

/**
 * Shared presentation of a role record, used by Role Lookup, Single Roles, the Access Package, comparison and review lists.
 *
 * Line 1: module icon and code, the role description, then optional counts and contextual actions on the right. The header is
 * one line: a description that does not fit ends in an ellipsis and reveals its full text on demand (hover, focus, click).
 * Line 2: the copyable SAP role identifier.
 * Line 3 (optional): supporting metadata such as counts, validity or review status.
 *
 * Composite roles, single roles and assigned records feed it their own evidence. The module is shown only when the caller
 * supplies it (or the description carries a known area label); nothing else is inferred. "standard" is the card layout,
 * "compact" the dense list row and "detailed" adds room for supporting evidence under the identifier.
 */
export function RoleEntry({
  moduleCode, showUnclassified = false, description, title, identifier, identifierLabel, tcodeCount, singleRoleCount,
  countPlacement = 'meta', actions, selected = false, density = 'standard', children, meta, footer, className, identifierSlot,
}: {
  moduleCode?: string | null
  showUnclassified?: boolean
  /** Raw source description; a leading "AREA - " label that matches a known module is shown as the module badge instead. */
  description?: string | null
  /** Already presentable name; takes precedence over `description`. */
  title?: string | null
  identifier: string
  identifierLabel?: string
  tcodeCount?: number
  singleRoleCount?: number
  /** Transaction count beside the actions (top right) or on the supporting line. */
  countPlacement?: 'top' | 'meta'
  /** Contextual controls at the top right, after the module identity and description in DOM order. */
  actions?: ReactNode
  selected?: boolean
  density?: RoleEntryDensity | 'card' | 'row'
  /** Extra evidence between the identifier and the supporting line. */
  children?: ReactNode
  /** Supporting metadata line (validity, status, assigned users). */
  meta?: ReactNode
  /** Trailing controls on the supporting line (for example "View details"). */
  footer?: ReactNode
  className?: string
  /** Replaces the plain identifier (for example a link to the user or role). */
  identifierSlot?: ReactNode
}) {
  const registry = useModuleDefinitions()
  const known = Object.keys(registry)
  const presentation = presentRoleDescription(description, known)
  const resolved = moduleCode && moduleCode !== 'UNCLASSIFIED' ? moduleCode : undefined
  const name = title ?? presentation.description
  const level: RoleEntryDensity = density === 'card' ? 'standard' : density === 'row' ? 'compact' : density
  const count = tcodeCount !== undefined && <TransactionCount count={tcodeCount} />
  const hasMeta = (countPlacement === 'meta' && tcodeCount !== undefined) || (singleRoleCount ?? 0) > 0 || meta || footer
  return (
    <div className={cn('role-entry', className)} data-density={level} data-selected={selected || undefined}>
      <div className="role-entry-head">
        <ModuleBadge moduleId={resolved || presentation.area} showUnclassified={showUnclassified} />
        <p className="role-entry-title" data-empty={!name || undefined}>{name ? <TruncatedText text={name} label="Role description" /> : 'No description'}</p>
        {(actions || (countPlacement === 'top' && count)) && (
          <div className="role-entry-actions">{countPlacement === 'top' && count}{actions}</div>
        )}
      </div>
      {identifierSlot ?? <RoleIdentifier value={identifier} label={identifierLabel} />}
      {children}
      {hasMeta && (
        <div className="role-entry-meta">
          {(singleRoleCount ?? 0) > 0 && (
            <span className="role-entry-single-roles"><Layers size={12} aria-hidden="true" /><b>{singleRoleCount}</b> {singleRoleCount === 1 ? 'single role' : 'single roles'}</span>
          )}
          {countPlacement === 'meta' && count}
          {meta}
          {footer && <span className="role-entry-footer">{footer}</span>}
        </div>
      )}
    </div>
  )
}
