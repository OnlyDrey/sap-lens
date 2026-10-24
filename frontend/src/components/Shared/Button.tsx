import {
  forwardRef,
  useId,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react'
import { Loader2 } from 'lucide-react'
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive'
  size?: 'default' | 'compact' | 'icon'
  loading?: boolean
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = 'secondary',
      size = 'default',
      loading = false,
      disabled,
      className = '',
      children,
      type = 'button',
      ...props
    },
    ref,
  ) {
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        className={`ui-button ui-button-${variant} ui-button-${size} ${className}`}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
      >
        {loading && (
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        )}
        {children}
      </button>
    )
  },
)
export function Tooltip({
  label,
  children,
  id,
}: {
  label: string
  children: ReactNode
  id?: string
}) {
  const generated = useId(),
    [open, setOpen] = useState(false)
  return (
    <span
      className="ui-tooltip-anchor"
      data-open={open}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false)
      }}
    >
      {children}
      <span id={id || generated} role="tooltip" className="ui-tooltip">
        {label}
      </span>
    </span>
  )
}
export function IconButton({
  label,
  tooltip = label,
  children,
  ...props
}: ButtonProps & { label: string; tooltip?: string }) {
  const id = useId()
  return (
    <Tooltip label={tooltip} id={id}>
      <Button {...props} size="icon" aria-label={label} aria-describedby={id}>
        {children}
      </Button>
    </Tooltip>
  )
}
export function ButtonGroup({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string; icon?: ReactNode }[]
  onChange: (s: string) => void
}) {
  return (
    <div className="ui-button-group" role="group" aria-label={label}>
      {options.map((option) => (
        <Button
          key={option.value}
          size="compact"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </Button>
      ))}
    </div>
  )
}
