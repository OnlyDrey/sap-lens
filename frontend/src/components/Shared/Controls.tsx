import { Button } from './Button'
import { StatusPill } from './StatusPill'
import {
  forwardRef,
  useId,
  Children,
  isValidElement,
  cloneElement,
  type ReactElement,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react'
import { Search, X } from 'lucide-react'
export const controlClass = 'ui-control'
export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function Input({ className = '', ...props }, ref) {
  return (
    <input {...props} ref={ref} className={`${controlClass} ${className}`} />
  )
})
export const SearchInput = forwardRef<HTMLInputElement,InputHTMLAttributes<HTMLInputElement> & {onClear?:()=>void}>(function SearchInput({onClear,...props},ref) {
 return <span className="ui-search" data-clearable={!!onClear}><Search size={16} aria-hidden="true"/><Input {...props} ref={ref} type={props.type || 'search'}/>{onClear&&!!props.value&&<Button variant="ghost" size="icon" aria-label={`Clear ${props['aria-label'] || 'search'}`} onClick={event=>{const input=event.currentTarget.previousElementSibling;onClear();if(input instanceof HTMLInputElement)input.focus()}}><X size={14} aria-hidden="true"/></Button>}</span>
})
export function FormField({
  label,
  description,
  children,
}: {
  label: string
  description?: string
  children: ReactNode
}) {
  const generated = useId(),
    help = `${generated}-help`
  let linked = false,
    controlId = generated
  const content = Children.toArray(children).map((child) => {
    if (linked || !isValidElement(child)) return child
    linked = true
    const control = child as ReactElement<{
      id?: string
      'aria-describedby'?: string
    }>
    controlId = control.props.id || generated
    return cloneElement(control, {
      id: controlId,
      'aria-describedby':
        [control.props['aria-describedby'], description ? help : '']
          .filter(Boolean)
          .join(' ') || undefined,
    })
  })
  return (
    <div className="ui-field">
      <label htmlFor={controlId}>{label}</label>
      {content}
      {description && (
        <small id={help} className="ui-description">
          {description}
        </small>
      )}
    </div>
  )
}
export function Checkbox({
  children,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { children: ReactNode }) {
  return (
    <label className="ui-checkbox">
      <input {...props} type="checkbox" />
      {children}
    </label>
  )
}
export function Toggle({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <StatusPill enabled={checked} label={label} disabled={disabled} onToggle={()=>onChange(!checked)}/>
  )
}
