import { Check, MinusCircle } from 'lucide-react'
export function StatusPill({ enabled }: { enabled: boolean }) {
  const Icon = enabled ? Check : MinusCircle
  return (
    <span
      className={`status-pill ${enabled ? 'status-enabled' : 'status-disabled'}`}
    >
      <Icon size={13} aria-hidden="true" />
      {enabled ? 'Enabled' : 'Disabled'}
    </span>
  )
}
