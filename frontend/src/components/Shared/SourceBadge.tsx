import { CircleCheck, CircleHelp, CircleX, Loader2 } from 'lucide-react'
export function SourceBadge({ loading = false, error, loaded = false }: { loading?: boolean; error?: unknown; loaded?: boolean }) {
  const Icon = loading ? Loader2 : loaded ? CircleCheck : error ? CircleX : CircleHelp
  const tone = loading ? 'info' : loaded ? 'success' : error ? 'error' : 'neutral'
  return <span className={`evidence-badge source-badge source-badge-${tone}`}><Icon size={14} aria-hidden="true" className={loading ? 'animate-spin' : ''}/>{loading ? 'Loading' : loaded ? 'Loaded' : error ? 'Last attempt failed' : 'Not loaded'}</span>
}
