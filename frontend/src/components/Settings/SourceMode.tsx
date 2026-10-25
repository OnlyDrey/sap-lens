import { FormField } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'

export function SourceMode({
  value,
  onChange,
}: {
  value: 'static' | 'dynamic'
  onChange: (value: 'static' | 'dynamic') => void
}) {
  return (
    <div className="source-mode-row">
      <FormField label="CSV source mode">
        <Select
          className="ui-control"
          value={value}
          onChange={(e) => onChange(e.target.value as 'static' | 'dynamic')}
        >
          <option value="static">Static — manual replacement</option>
          <option value="dynamic">Dynamic — refresh configured file</option>
        </Select>
      </FormField>
      <p className="text-sm text-[var(--muted)]">
        {value === 'static'
          ? 'Validated records are saved locally. Global Refresh leaves this source unchanged; replace it explicitly when needed.'
          : 'Global Refresh rereads the configured path and validates a complete replacement. Failed reads preserve the last valid local snapshot.'}
      </p>
    </div>
  )
}
