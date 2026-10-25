import type { ReactNode } from 'react'
import { X } from 'lucide-react'
export function Notification({
  children,
  variant = 'info',
  onDismiss,
  label,
  className = '',
}: {
  children: ReactNode
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral'
  label?: string
  className?: string
  onDismiss?: () => void
}) {
  return (
    <div
      className={`notification notification-${variant} ${className}`}
      role={variant === 'error' ? 'alert' : 'status'}
      aria-label={label}
    >
      <div className="notification-content">
        <div>{children}</div>
        {onDismiss && (
          <button
            type="button"
            className="notification-close"
            aria-label="Dismiss notification"
            onClick={onDismiss}
          >
            <X size={17} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}
