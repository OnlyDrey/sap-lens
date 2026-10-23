import { CircleCheck, CircleHelp, CircleX, Loader2 } from 'lucide-react'
export function SourceBadge({ loading = false, error, loaded = false }: { loading?: boolean; error?: unknown; loaded?: boolean }) {
  const Icon = loading ? Loader2 : error ? CircleX : loaded ? CircleCheck : CircleHelp
  const tone = loading ? 'info' : error ? 'error' : loaded ? 'success' : 'neutral'
  return <span className={`evidence-badge source-badge source-badge-${tone}`}><Icon size={14} aria-hidden="true" className={loading ? 'animate-spin' : ''}/>{loading ? 'Loading' : error ? 'Last attempt failed' : loaded ? 'Loaded' : 'Not loaded'}</span>
}
