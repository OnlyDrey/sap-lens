import { Select } from '@/components/Shared/Select'
import { useId, type ReactNode, type SelectHTMLAttributes } from 'react'
import { RotateCcw } from 'lucide-react'
import { isHex } from '@/lib/theme'

export function SettingsSelect({
  className = '',
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return <Select {...props} className={`settings-control ${className}`}/>

}

export function ColorControl({
  label,
  value,
  onChange,
  onReset,
  id,
  optional = false,
  preview
}: {
  label: string
  value: string
  onChange: (value: string) => void
  onReset: () => void
  id?: string
  /** An empty value is valid and means "no color". */
  optional?: boolean
  /** Shows the entered color in context, for example an identifier pill. */
  preview?: ReactNode
}) {
  const generated = useId()
  const fieldId = id || generated
  const valid = isHex(value) || (optional && value === '')
  return (
    <div className="space-y-2">
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>
      <div className="settings-color-control">
        <input
          type="color"
          aria-label={`${label} visual selection`}
          value={isHex(value) ? value : '#64748b'}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          id={fieldId}
          aria-label={label}
          className="settings-control font-mono"
          value={value}
          maxLength={7}
          placeholder={optional ? 'No color' : undefined}
          spellCheck={false}
          aria-invalid={!valid}
          aria-describedby={!valid ? `${fieldId}-error` : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="settings-icon-button"
          aria-label={`Reset ${label}`}
          title="Reset to default"
          onClick={onReset}
        >
          <RotateCcw size={16} />
        </button>
      </div>
      {preview && <div className="flex items-center gap-2 text-xs">Preview {preview}</div>}
      {!valid && (
        <p
          id={`${fieldId}-error`}
          role="alert"
          className="text-xs text-[var(--error)]"
        >
          Enter a six-digit HEX value, such as #123456.
        </p>
      )}
    </div>
  )
}
