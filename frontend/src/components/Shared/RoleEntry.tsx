import type { ReactNode } from 'react'
import { Layers } from 'lucide-react'
import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import { RoleIdentifier } from './RoleIdentifier'
import { TransactionCount } from './TransactionCount'
import { cn } from '@/lib/utils'

/**
 * Shared presentation of a role record: module identity first, display name above the copyable technical name,
 * optional counts and actions. Composite roles, single roles and assigned records feed it their own evidence;
 * it never derives a module or a name that the caller did not supply.
 */
export function RoleEntry({
  moduleCode, showUnclassified = false, title, identifier, identifierLabel, tcodeCount, singleRoleCount,
  actions, selected = false, density = 'card', children, footer, className,
}: {
  moduleCode?: string | null
  showUnclassified?: boolean
  /** Display name or description; omitted text shows "No description". */
  title?: string | null
  identifier: string
  identifierLabel?: string
  tcodeCount?: number
  singleRoleCount?: number
  /** Controls at the top right, after the module identity in DOM order. */
  actions?: ReactNode
  selected?: boolean
  density?: 'card' | 'row'
  /** Extra evidence between the identifier and the counts row. */
  children?: ReactNode
  /** Trailing controls on the counts row (for example "View details"). */
  footer?: ReactNode
  className?: string
}) {
  const hasCounts = tcodeCount !== undefined || (singleRoleCount ?? 0) > 0 || footer
  return (
    <div className={cn('role-entry', className)} data-density={density} data-selected={selected || undefined}>
      <div className="role-entry-top">
        <ModuleBadge moduleId={moduleCode} showUnclassified={showUnclassified} selected={selected} />
        {actions && <div className="role-entry-actions">{actions}</div>}
      </div>
      <p className="role-entry-title" data-empty={!title || undefined}>{title || 'No description'}</p>
      <RoleIdentifier value={identifier} label={identifierLabel} />
      {children}
      {hasCounts && (
        <div className="role-entry-counts">
          {(singleRoleCount ?? 0) > 0 && (
            <span className="role-entry-single-roles"><Layers size={12} aria-hidden="true" /><b>{singleRoleCount}</b> {singleRoleCount === 1 ? 'single role' : 'single roles'}</span>
          )}
          {tcodeCount !== undefined && <TransactionCount count={tcodeCount} />}
          {footer}
        </div>
      )}
    </div>
  )
}
