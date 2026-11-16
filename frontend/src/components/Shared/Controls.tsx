import { Button } from './Button'
import { StatusPill } from './StatusPill'
import {
  createContext,
  forwardRef,
  useContext,
  useId,
  useState,
  Children,
  isValidElement,
  cloneElement,
  type ReactElement,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react'
import { Eye, EyeOff, Search, X } from 'lucide-react'
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
/** Password field with a visibility toggle. The toggle is a real button (aria-pressed) after the input, so it is reachable by keyboard and
 *  announced; the value never leaves the input. Use inside FormField so the label targets the input. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>>(function PasswordInput({ className = '', ...props }, ref) {
 const [visible, setVisible] = useState(false)
 return <span className="ui-password"><Input {...props} ref={ref} className={className} type={visible ? 'text' : 'password'} spellCheck={false} autoCapitalize="off"/><Button variant="ghost" size="icon" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} disabled={props.disabled} onClick={() => setVisible(value => !value)}>{visible ? <EyeOff size={16} aria-hidden="true"/> : <Eye size={16} aria-hidden="true"/>}</Button></span>
})
/** Slot at the right of a field's label row; controls (for example the multi-select Clear action) render into it through a portal. */
const FieldActionSlot = createContext<HTMLElement | null>(null)
export const useFieldActionSlot = () => useContext(FieldActionSlot)

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
    help = `${generated}-help`,
    [slot, setSlot] = useState<HTMLElement | null>(null)
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
      <span ref={setSlot} className="ui-field-action" />
      <FieldActionSlot.Provider value={slot}>{content}</FieldActionSlot.Provider>
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
