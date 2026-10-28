import { Button } from '@/components/Shared/Button'
import { TransactionCount } from '@/components/Shared/TransactionCount'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { Scale, Plus, ArrowRight, Layers } from 'lucide-react'
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

/** Round selection toggle shared by comparison and the access package so both read the same. */
function ToggleButton({ active, label, onToggle, children }: { active: boolean; label: string; onToggle: () => void; children: React.ReactNode }) {
  return (
    <button data-np type="button" onClick={e => { e.stopPropagation(); onToggle() }} aria-label={label} title={label} aria-pressed={active}
      className={cn('w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] hover:scale-110 active:scale-95')}
      style={active
        ? { backgroundColor:'var(--accent)', color:'var(--on-accent)', border:'none' }
        : { backgroundColor:'var(--surface2)', color:'var(--muted)', border:'1.5px solid var(--border)' }}>
      {children}
    </button>
  )
}

const cleanTitle = (t: string | null) =>
  t ? t.replace(/^[A-Z]{2,3}\s*-\s*/, '').trim() : ''

export function RoleCard({ role, isSelected, onSelect, inCart, onCart, onClick }: Props) {
  const title   = cleanTitle(role.text)
  const modName = role.module_name ?? role.function_key ?? ''
  const hasSR   = (role.single_role_count ?? 0) > 0
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
      <div className="flex flex-col gap-2.5 flex-1">

        {/* Top row: module label + compare, then add to access package (rightmost) */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <ModuleIcon moduleId={role.function_key} selected={isSelected} />
            <span className="text-xs font-semibold truncate" style={{ color:'var(--text2)' }}>
              {modName}{role.module_ambiguous?' · Ambiguous':''}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <ToggleButton active={isSelected} label={isSelected ? 'Remove from comparison' : 'Add to comparison'} onToggle={() => onSelect(role.agr_name)}>
              <Scale className="w-3.5 h-3.5" strokeWidth={2.5} />
            </ToggleButton>
            <ToggleButton active={inCart} label={inCart ? 'Remove from access package' : 'Add to access package'} onToggle={() => onCart(role.agr_name)}>
              <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />
            </ToggleButton>
          </div>
        </div>

        {/* Role title */}
        <p className={cn('font-black text-[15px] leading-snug flex-1', !role.text && 'italic')}
          style={{ color: role.text ? 'var(--text)' : 'var(--muted)' }}>
          {title || 'No description'}
        </p>

        {/* AGR_NAME */}
        <RoleIdentifier value={role.agr_name} />

        {/* T-code match badges â€” shown only when role was found via T-code search */}
        {hasTcodeMatch && (
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[9px] font-black uppercase tracking-wide"
              style={{ color:'var(--muted)' }}>
              T-code match:
            </span>
            {role.matching_tcodes!.slice(0, 4).map(tc => (
              <span key={tc}
                className="font-mono text-xs font-black px-1.5 py-0.5 rounded-md"
                style={{ backgroundColor:'color-mix(in srgb, var(--accent) 15%, transparent)', color:'var(--accent2)' }}>
                {tc}
              </span>
            ))}
            {role.matching_tcodes!.length > 4 && (
              <span className="text-[9px]" style={{ color:'var(--muted)' }}>
                +{role.matching_tcodes!.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* Stats row: single roles | T-codes | View details */}
        <div className="flex flex-wrap items-center gap-2.5 pt-3 mt-auto"
          style={{ borderTop:'1px solid var(--border)' }}>

          {hasSR && (
            <div className="flex items-center gap-1">
              <Layers className="w-3 h-3 flex-shrink-0" style={{ color:'var(--accent2)' }} />
              <span className="text-xs font-bold tabular-nums" style={{ color:'var(--text2)' }}>
                {role.single_role_count}
              </span>
              <span className="text-xs" style={{ color:'var(--muted)' }}>{role.single_role_count === 1 ? 'single role' : 'single roles'}</span>
            </div>
          )}
          {hasSR && <span style={{ color:'var(--border)', userSelect:'none' }}>|</span>}

          <TransactionCount count={role.tcode_count}/>

          <Button data-np variant="outline" size="compact"
            onClick={e => { e.stopPropagation(); onClick(role.agr_name) }}
            aria-label={`View details for ${title || role.agr_name}`}
            className="role-card-details ml-auto"
>
            View details <ArrowRight className="w-3 h-3" />
          </Button>
        </div>
      </div>
    </article>
  )
}