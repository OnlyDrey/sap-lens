import { useId, useState, useRef, useEffect } from 'react'
import { CalendarDays, X } from 'lucide-react'
import { ClearFilterButton } from './ClearFilterButton'
import { NorwegianDateInput, parseNorwegianDate } from './NorwegianDateInput'
import { formatDate } from '@/lib/dateFormat'
export interface AssignmentDates {
  valid_from_min: string
  valid_from_max: string
  valid_to_min: string
  valid_to_max: string
  include_missing_end: boolean
}
export const emptyDates: AssignmentDates = {
  valid_from_min: '',
  valid_from_max: '',
  valid_to_min: '',
  valid_to_max: '',
  include_missing_end: true,
}
const fields = [
  'valid_from_min',
  'valid_from_max',
  'valid_to_min',
  'valid_to_max',
] as const
const labels = {
  valid_from_min: 'Valid from earliest',
  valid_from_max: 'Valid from latest',
  valid_to_min: 'Valid to earliest',
  valid_to_max: 'Valid to latest',
}
export const dateParams = (dates: AssignmentDates): Record<string, string> => ({
  ...Object.fromEntries(
    fields.filter((key) => dates[key]).map((key) => [key, dates[key]]),
  ),
  ...(!dates.include_missing_end ? { include_missing_end: 'false' } : {}),
})
export const datesActive = (dates: AssignmentDates) =>
  fields.some((key) => !!dates[key]) || !dates.include_missing_end
export function AssignmentDateFilters({
  value,
  onChange,
}: {
  value: AssignmentDates
  onChange: (value: AssignmentDates) => void
}) {
  const [open, setOpen] = useState(false),
    [draft, setDraft] = useState<Record<(typeof fields)[number], string>>({
      valid_from_min: '',
      valid_from_max: '',
      valid_to_min: '',
      valid_to_max: '',
    }),
    [includeMissing, setIncludeMissing] = useState(true),
    [error, setError] = useState('')
  const trigger = useRef<HTMLButtonElement>(null)
  const close = () => {
    setOpen(false)
    trigger.current?.focus()
  }
  useEffect(() => {
    if (open) {
      setDraft(
        Object.fromEntries(
          fields.map((key) => [key, formatDate(value[key], '')]),
        ) as typeof draft,
      )
      setIncludeMissing(value.include_missing_end)
      setError('')
    }
  }, [value])
  const id = useId(),
    count =
      fields.filter((key) => !!value[key]).length +
      Number(!value.include_missing_end)
  const begin = () => {
    setDraft(
      Object.fromEntries(
        fields.map((key) => [key, formatDate(value[key], '')]),
      ) as typeof draft,
    )
    setIncludeMissing(value.include_missing_end)
    setError('')
    setOpen(!open)
  }
  const apply = () => {
    const next = { ...emptyDates, include_missing_end: includeMissing }
    for (const key of fields) {
      const parsed = parseNorwegianDate(draft[key])
      if (parsed === null) {
        setError(`${labels[key]}: use a valid DD.MM.YYYY date.`)
        return
      }
      next[key] = parsed
    }
    if (
      (next.valid_from_min &&
        next.valid_from_max &&
        next.valid_from_min > next.valid_from_max) ||
      (next.valid_to_min &&
        next.valid_to_max &&
        next.valid_to_min > next.valid_to_max)
    ) {
      setError('Earliest assignment dates must not follow their latest dates.')
      return
    }
    onChange(next)
    close()
  }
  return (
    <div
      className="assignment-date-filters"
      role="group"
      aria-label="Assignment date filters"
    >
      <button
        ref={trigger}
        type="button"
        className="settings-secondary-button"
        aria-expanded={open}
        aria-controls={id}
        onClick={begin}
      >
        <CalendarDays size={16} aria-hidden="true" />
        Assignment date filters{count ? ` (${count} active)` : ''}
      </button>
      {open && (
        <div
          id={id}
          className="assignment-date-panel space-y-3"
          role="group"
          aria-label="Assignment date controls"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation()
              close()
            }
          }}
        >
          <div className="date-input-grid">
            {fields.map((key) => (
              <NorwegianDateInput
                key={key}
                label={labels[key]}
                value={draft[key]}
                onChange={(text) => {
                  setDraft((previous) => ({ ...previous, [key]: text }))
                  setError('')
                }}
              />
            ))}
          </div>
          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={includeMissing}
              onChange={(event) => setIncludeMissing(event.target.checked)}
            />
            Include assignments without end date
          </label>
          <p className="text-xs text-[var(--muted)]">
            Only assignment records are filtered. Missing ends stay unknown and
            are included when checked, even with end-date bounds. 31.12.9999 is
            a real SAP maximum date and obeys those bounds.
          </p>
          {error && (
            <p role="alert" className="text-[var(--error)]">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="settings-secondary-button"
              onClick={apply}
            >
              Apply date filters
            </button>
            <ClearFilterButton
              onClick={() => {
                onChange({ ...emptyDates })
                close()
              }}
            >
              Clear date filters
            </ClearFilterButton>
            <button
              type="button"
              className="settings-secondary-button"
              onClick={close}
            >
              Cancel date changes
            </button>
          </div>
        </div>
      )}
      {datesActive(value) && (
        <div
          className="transaction-chips mt-2"
          aria-label="Active assignment date filters"
        >
          {fields
            .filter((key) => value[key])
            .map((key) => (
              <span className="transaction-chip" key={key}>
                {labels[key]}: {formatDate(value[key])}
                <button
                  type="button"
                  aria-label={`Remove ${labels[key]} filter`}
                  onClick={() => onChange({ ...value, [key]: '' })}
                >
                  <X size={13} aria-hidden="true" />
                </button>
              </span>
            ))}
          {!value.include_missing_end && (
            <span className="transaction-chip">
              Missing end dates excluded
              <button
                type="button"
                aria-label="Remove missing end date filter"
                onClick={() =>
                  onChange({ ...value, include_missing_end: true })
                }
              >
                <X size={13} />
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  )
}
