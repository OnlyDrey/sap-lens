import type { ReactNode } from 'react'
import { X } from 'lucide-react'
export function FilterChip({
  children,
  removeLabel,
  onRemove,
}: {
  children: ReactNode
  removeLabel: string
  onRemove: () => void
}) {
  return (
    <span className="transaction-chip">
      {children}
      <button type="button" aria-label={removeLabel} onClick={onRemove}>
        <X size={13} aria-hidden="true" />
      </button>
    </span>
  )
}
