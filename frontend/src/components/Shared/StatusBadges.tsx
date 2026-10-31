import { CheckCircle2, CircleSlash, Lock, RefreshCw } from 'lucide-react'
import { StatusBadge } from './Presentation'

/** Enabled and Disabled for a feature, risk or source: the same wording, tone and icon wherever they appear. */
export function EnabledBadge({ enabled, disabledLabel = 'Disabled', tone, className = '' }: { enabled: boolean; disabledLabel?: string; /** Enabled but not in effect (for example a historical risk) can be shown neutral. */ tone?: 'success' | 'neutral'; className?: string }) {
  return <StatusBadge tone={tone ?? (enabled ? 'success' : 'neutral')} className={className}>{enabled ? <CheckCircle2 size={14} aria-hidden="true" /> : <CircleSlash size={14} aria-hidden="true" />}{enabled ? 'Enabled' : disabledLabel}</StatusBadge>
}

/** Static (neutral, locked) or Dynamic (accent, refreshing) source mode. */
export function ModeBadge({ mode }: { mode: 'static' | 'dynamic' | string | undefined }) {
  if (mode !== 'static' && mode !== 'dynamic') return <StatusBadge>Mode unavailable</StatusBadge>
  return <StatusBadge tone={mode === 'static' ? 'neutral' : 'accent'}>{mode === 'static' ? <Lock size={14} aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}{mode === 'static' ? 'Static' : 'Dynamic'}</StatusBadge>
}
