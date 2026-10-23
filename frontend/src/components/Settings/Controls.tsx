import { Select } from '@/components/Shared/Select'
import { useId, type SelectHTMLAttributes } from 'react'
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
  id
}: {
  label: string
  value: string
  onChange: (value: string) => void
  onReset: () => void
  id?: string
}) {
  const generated = useId()
  const fieldId = id || generated
  const valid = isHex(value)
  return (
    <div className="space-y-2">
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>
      <div className="settings-color-control">
        <input
          type="color"
          aria-label={`${label} visual selection`}
          value={valid ? value : '#64748b'}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          id={fieldId}
          aria-label={label}
          className="settings-control font-mono"
          value={value}
          maxLength={7}
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
