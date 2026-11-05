import { Checkbox, FormField, controlClass } from '@/components/Shared/Controls'
import type { Configuration } from '@/api/configuration'

export const DEFAULT_IMPORT_CHECKS = { enabled: true, max_drop_percent: 30, min_previous_records: 20 }

/** When a valid replacement file shrinks sharply compared with the active revision of the same source, it waits for confirmation. */
export function ImportChecksSettings({ draft, onChange }: { draft: Configuration; onChange: (value: NonNullable<Configuration['import_checks']>) => void }) {
  const checks = draft.import_checks ?? DEFAULT_IMPORT_CHECKS
  const number = (value: string, fallback: number, min: number, max: number) => Math.min(max, Math.max(min, Number.isFinite(Number(value)) && value !== '' ? Math.round(Number(value)) : fallback))
  return (
    <details className="settings-advanced">
      <summary>Import checks</summary>
      <div className="grid gap-3 py-2">
        <p className="ui-description">
          A valid file is compared with the active data of the same source only. A drop beyond the limit in records or distinct users, roles or accounts, or the loss of a whole
          organizational group, holds the import for confirmation; the active data stays untouched. Structurally invalid files are always rejected and cannot be confirmed.
          Changes apply with Apply settings.
        </p>
        <Checkbox checked={checks.enabled} onChange={event => onChange({ ...checks, enabled: event.target.checked })}>Hold suspicious imports for confirmation</Checkbox>
        <FormField label="Largest accepted reduction (%)" description="Between 1 and 95. Default 30.">
          <input className={controlClass} type="number" min={1} max={95} disabled={!checks.enabled} value={checks.max_drop_percent}
            onChange={event => onChange({ ...checks, max_drop_percent: number(event.target.value, 30, 1, 95) })} />
        </FormField>
        <FormField label="Smallest source that is checked (records)" description="Smaller active sources are never held. Default 20.">
          <input className={controlClass} type="number" min={0} max={1000000} disabled={!checks.enabled} value={checks.min_previous_records}
            onChange={event => onChange({ ...checks, min_previous_records: number(event.target.value, 20, 0, 1000000) })} />
        </FormField>
      </div>
    </details>
  )
}
