import {
  forwardRef,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react'
import { Loader2 } from 'lucide-react'
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive' | 'success'
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
/** Hint for a control. The bubble is `position: fixed` and placed from the anchor's viewport rectangle, so scroll containers
 *  (`overflow: auto` table regions) cannot clip it. It flips above the anchor when there is no room below and is kept inside the viewport. */
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
    [open, setOpen] = useState(false),
    [place, setPlace] = useState<{ top: number; left: number } | null>(null),
    anchor = useRef<HTMLSpanElement>(null),
    bubble = useRef<HTMLSpanElement>(null)
  const position = () => {
    const a = anchor.current?.getBoundingClientRect(), b = bubble.current
    if (!a || !b) return
    const margin = 8, width = b.offsetWidth, height = b.offsetHeight
    const below = a.bottom + margin, above = a.top - margin - height
    const top = below + height <= window.innerHeight - margin || above < margin ? below : above
    const left = Math.min(Math.max(a.right - width, margin), Math.max(margin, window.innerWidth - width - margin))
    setPlace(previous => (previous && previous.top === top && previous.left === left ? previous : { top, left }))
  }
  useLayoutEffect(() => { if (open) position() }, [open, label]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return
    window.addEventListener('scroll', position, true)
    window.addEventListener('resize', position)
    return () => { window.removeEventListener('scroll', position, true); window.removeEventListener('resize', position) }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span
      ref={anchor}
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
      <span ref={bubble} id={id || generated} role="tooltip" className="ui-tooltip" style={place ? { top: place.top, left: place.left } : undefined}>
        {label}
      </span>
    </span>
  )
}
export function IconButton({
  label,
  tooltip = label,
  children,
  loading = false,
  ...props
}: ButtonProps & { label: string; tooltip?: string }) {
  const id = useId()
  return (
    <Tooltip label={tooltip} id={id}>
      <Button {...props} size="icon" loading={loading} aria-label={label} aria-describedby={id}>
        {loading ? null : children}
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
