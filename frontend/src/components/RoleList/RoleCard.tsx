import { Plus, Check, ArrowRight, Zap, Layers,
  DollarSign, BarChart2, Package, Wrench, Users, TrendingUp, Cog,
  FolderKanban, CheckCircle, Server, Warehouse } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RoleSummary } from '@/api/types'

interface Props {
  role: RoleSummary
  isSelected: boolean
  onSelect: (n: string) => void
  onClick: (n: string) => void
}

const MOD_ICON: Record<string, React.ComponentType<{className?: string}>> = {
  FI:DollarSign, CO:BarChart2,   MM:Package,
  SD:TrendingUp, PP:Cog,         PM:Wrench,
  CA:Layers,     HR:Users,       WM:Warehouse,
  PS:FolderKanban, BC:Server,    QM:CheckCircle,
}
const MOD_COLOR: Record<string,string> = {
  FI:'#3d4d8a', CO:'#5a0090', MM:'#c44d10',
  SD:'#1d5a6e', PP:'#1a4d28', PM:'#9a6c00',
  CA:'#4a5568', HR:'#162340', WM:'#0a3848',
  PS:'#1e2d78', BC:'#374151', QM:'#8b1a1a',
}

const cleanTitle = (t: string | null) =>
  t ? t.replace(/^[A-Z]{2,3}\s*-\s*/, '').trim() : ''

export function RoleCard({ role, isSelected, onSelect, onClick }: Props) {
  const title   = cleanTitle(role.text)
  const Icon    = role.function_key ? (MOD_ICON[role.function_key] ?? null) : null
  const color   = role.function_key ? (MOD_COLOR[role.function_key] ?? '#515793') : '#94a3b8'
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
      aria-label={`${title || role.agr_name}${isSelected ? ', selected' : ''}`}
      className={cn('rounded-2xl cursor-pointer transition-all duration-150 flex flex-col')}
      style={{
        backgroundColor: 'var(--surface)',
        border: isSelected
          ? '2px solid var(--accent)'
          : hasTcodeMatch
            ? '1.5px solid rgba(250,100,20,0.4)'
            : '1px solid var(--border)',
        padding: isSelected ? '15px' : '16px',
        boxShadow: isSelected
          ? '0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent)'
          : hasTcodeMatch
            ? '0 0 0 3px rgba(250,100,20,0.08)'
            : '0 1px 3px rgba(0,0,0,0.06)',
      }}>
      <div className="flex flex-col gap-2.5">

        {/* Top row: module label + add button */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <div className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: color }}>
              {Icon ? <Icon className="w-3.5 h-3.5 text-white" /> : null}
            </div>
            <span className="text-[11px] font-semibold truncate" style={{ color:'var(--text2)' }}>
              {modName}
            </span>
          </div>
          <button data-np
            onClick={e => { e.stopPropagation(); onSelect(role.agr_name) }}
            aria-label={isSelected ? 'Remove from comparison' : 'Add to comparison'}
            className={cn('w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 transition-all focus:outline-none hover:scale-110 active:scale-95')}
            style={isSelected
              ? { backgroundColor:'var(--accent)', color:'#fff', border:'none' }
              : { backgroundColor:'var(--surface2)', color:'var(--muted)', border:'1.5px solid var(--border)' }}>
            {isSelected
              ? <Check className="w-3.5 h-3.5" strokeWidth={3} />
              : <Plus  className="w-3.5 h-3.5" strokeWidth={2.5} />}
          </button>
        </div>

        {/* Role title */}
        <p className={cn('font-black text-[15px] leading-snug flex-1', !role.text && 'italic')}
          style={{ color: role.text ? 'var(--text)' : 'var(--muted)' }}>
          {title || 'No description'}
        </p>

        {/* AGR_NAME */}
        <p className="font-mono text-[10px] truncate" style={{ color:'var(--text2)' }} title={role.agr_name}>
          {role.agr_name}
        </p>

        {/* T-code match badges â€” shown only when role was found via T-code search */}
        {hasTcodeMatch && (
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[9px] font-black uppercase tracking-wide"
              style={{ color:'var(--muted)' }}>
              T-code match:
            </span>
            {role.matching_tcodes!.slice(0, 4).map(tc => (
              <span key={tc}
                className="font-mono text-[10px] font-black px-1.5 py-0.5 rounded-md"
                style={{ backgroundColor:'rgba(250,100,20,0.15)', color:'var(--accent)' }}>
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
        <div className="flex items-center gap-2.5 pt-3"
          style={{ borderTop:'1px solid var(--border)' }}>

          {hasSR && (
            <div className="flex items-center gap-1">
              <Layers className="w-3 h-3 flex-shrink-0" style={{ color:'var(--accent2)' }} />
              <span className="text-[11px] font-bold tabular-nums" style={{ color:'var(--text2)' }}>
                {role.single_role_count}
              </span>
              <span className="text-[10px]" style={{ color:'var(--muted)' }}>single roles</span>
            </div>
          )}
          {hasSR && <span style={{ color:'var(--border)', userSelect:'none' }}>|</span>}

          <div className="flex items-center gap-1">
            <Zap className="w-3 h-3 flex-shrink-0" style={{ color:'var(--accent)' }} />
            <span className="text-[11px] font-bold tabular-nums" style={{ color:'var(--text2)' }}>
              {role.tcode_count.toLocaleString()}
            </span>
            <span className="text-[10px]" style={{ color:'var(--muted)' }}>T-codes</span>
          </div>

          <button data-np
            onClick={e => { e.stopPropagation(); onClick(role.agr_name) }}
            aria-label={`View details for ${title || role.agr_name}`}
            className="ml-auto flex items-center gap-0.5 text-[11px] font-bold hover:underline focus:outline-none flex-shrink-0"
            style={{ color:'var(--accent2)' }}>
            View details <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      </div>
    </article>
  )
}