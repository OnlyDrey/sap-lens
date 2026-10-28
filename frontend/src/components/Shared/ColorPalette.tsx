import { Check } from 'lucide-react'

/** Fixed palette: every swatch has a text name, and pills always show their identifier, so color is never the only signal. */
export const PALETTE: { name: string; value: string }[] = [
  { name: 'Blue', value: '#2563eb' }, { name: 'Teal', value: '#0d9488' }, { name: 'Green', value: '#16a34a' }, { name: 'Amber', value: '#d97706' },
  { name: 'Orange', value: '#ea580c' }, { name: 'Red', value: '#dc2626' }, { name: 'Pink', value: '#db2777' }, { name: 'Purple', value: '#7c3aed' },
  { name: 'Slate', value: '#64748b' }, { name: 'Brown', value: '#92400e' },
]

export function ColorPalette({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <fieldset className="color-palette">
      <legend>{label}</legend>
      <div role="radiogroup" aria-label={label}>
        <label className="color-swatch" data-selected={!value}>
          <input type="radio" name={label} checked={!value} onChange={() => onChange('')} />
          <span className="color-swatch-chip color-swatch-none" aria-hidden="true" />
          <span>No color</span>
        </label>
        {PALETTE.map((color) => (
          <label key={color.value} className="color-swatch" data-selected={value === color.value}>
            <input type="radio" name={label} checked={value === color.value} onChange={() => onChange(color.value)} />
            <span className="color-swatch-chip" style={{ background: color.value }} aria-hidden="true">{value === color.value && <Check size={12} />}</span>
            <span>{color.name}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
