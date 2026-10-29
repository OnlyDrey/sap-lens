import { Button } from '@/components/Shared/Button'
import { RoleEntry } from '@/components/Shared/RoleEntry'
import { PackageToggle } from '@/components/Shared/PackageToggle'
import { Scale, Plus, Check, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RoleSummary } from '@/api/types'

interface Props {
  role: RoleSummary
  isSelected: boolean
  onSelect: (n: string) => void
  inCart: boolean
  onCart: (n: string) => void
  onClick: (n: string) => void
}

const cleanTitle = (t: string | null) =>
  t ? t.replace(/^[A-Z]{2,3}\s*-\s*/, '').trim() : ''

export function RoleCard({ role, isSelected, onSelect, inCart, onCart, onClick }: Props) {
  const title   = cleanTitle(role.text)
  const hasTcodeMatch = (role.matching_tcodes?.length ?? 0) > 0

  const handleCardClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-np]')) return
    onClick(role.agr_name)
  }

  return (
    <article
      onClick={handleCardClick}
      aria-label={`${title || role.agr_name}${isSelected ? ', selected' : ''}${inCart ? ', in access package' : ''}`}
      className={cn('role-card rounded-2xl cursor-pointer transition-all duration-150 flex flex-col')}
      style={{
        backgroundColor: 'var(--surface)',
        border: isSelected
          ? '2px solid var(--accent2)'
          : hasTcodeMatch
            ? '1.5px solid color-mix(in srgb, var(--accent) 40%, transparent)'
            : '1px solid var(--border)',
        padding: isSelected ? '15px' : '16px',
      }}>
      <RoleEntry
        moduleCode={role.function_key}
        showUnclassified
        title={title}
        identifier={role.agr_name}
        tcodeCount={role.tcode_count}
        singleRoleCount={role.single_role_count}
        selected={isSelected}
        actions={<>
          <PackageToggle active={isSelected} label={isSelected ? 'Remove from comparison' : 'Add to comparison'} onToggle={() => onSelect(role.agr_name)}>
            <Scale className="w-3.5 h-3.5" strokeWidth={2.5} />
          </PackageToggle>
          <PackageToggle active={inCart} label={inCart ? 'Remove from access package' : 'Add to access package'} onToggle={() => onCart(role.agr_name)}>
            {inCart ? <Check className="w-3.5 h-3.5" strokeWidth={3} /> : <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />}
          </PackageToggle>
        </>}
        footer={
          <Button data-np variant="outline" size="compact"
            onClick={e => { e.stopPropagation(); onClick(role.agr_name) }}
            aria-label={`View details for ${title || role.agr_name}`}
            className="role-card-details ml-auto">
            View details <ArrowRight className="w-3 h-3" />
          </Button>
        }>
        {hasTcodeMatch && (
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[9px] font-black uppercase tracking-wide" style={{ color:'var(--muted)' }}>T-code match:</span>
            {role.matching_tcodes!.slice(0, 4).map(tc => (
              <span key={tc} className="font-mono text-xs font-black px-1.5 py-0.5 rounded-md"
                style={{ backgroundColor:'color-mix(in srgb, var(--accent) 15%, transparent)', color:'var(--accent2)' }}>{tc}</span>
            ))}
            {role.matching_tcodes!.length > 4 && (
              <span className="text-[9px]" style={{ color:'var(--muted)' }}>+{role.matching_tcodes!.length - 4} more</span>
            )}
          </div>
        )}
      </RoleEntry>
    </article>
  )
}
