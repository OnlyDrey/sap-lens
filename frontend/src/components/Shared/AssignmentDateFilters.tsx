import { CalendarDays, ChevronDown } from 'lucide-react'
import { ClearFilterButton } from './ClearFilterButton'
import { Select } from './Select'
import { formatDate } from '@/lib/dateFormat'
export interface AssignmentDates {
  valid_from_min: string
  valid_from_max: string
  valid_to_min: string
  valid_to_max: string
  open_ended: string
}
export const emptyDates: AssignmentDates = {
  valid_from_min: '',
  valid_from_max: '',
  valid_to_min: '',
  valid_to_max: '',
  open_ended: '',
}
export const dateParams = (dates: AssignmentDates): Record<string, string> =>
  Object.fromEntries(Object.entries(dates).filter(([, value]) => value))
export const datesActive = (dates: AssignmentDates) =>
  Object.values(dates).some(Boolean)
export function AssignmentDateFilters({
  value,
  onChange,
}: {
  value: AssignmentDates
  onChange: (value: AssignmentDates) => void
}) {
  const invalid =
    (value.valid_from_min &&
      value.valid_from_max &&
      value.valid_from_min > value.valid_from_max) ||
    (value.valid_to_min &&
      value.valid_to_max &&
      value.valid_to_min > value.valid_to_max)
  return (
    <details className="assignment-date-filters settings-advanced">
      <summary className="flex gap-2 items-center">
        <CalendarDays size={16} aria-hidden="true" />
        Assignment date filters
        {datesActive(value)
          ? ` · Active · ${Object.entries(value)
              .filter(([, item]) => item)
              .map(([key, item]) =>
                key === 'open_ended'
                  ? item === 'only'
                    ? 'Only open-ended'
                    : 'Exclude open-ended'
                  : `${key.startsWith('valid_from') ? 'Start' : 'End'} ${key.endsWith('_min') ? '≥' : '≤'} ${formatDate(item)}`,
              )
              .join(' · ')}`
          : ''}
        <ChevronDown
          size={14}
          aria-hidden="true"
          className="date-filter-chevron shrink-0"
        />
      </summary>
      <div className="filter-grid py-3">
        {(['valid_from', 'valid_to'] as const).map((field) => (
          <fieldset key={field} className="space-y-2">
            <legend>
              {field === 'valid_from' ? 'Valid from' : 'Valid to'}
            </legend>
            {(['min', 'max'] as const).map((bound) => (
              <label key={bound} className="flex flex-col gap-1 text-sm">
                {field === 'valid_from' ? 'Valid from' : 'Valid to'}{' '}
                {bound === 'min' ? 'earliest' : 'latest'}
                <input
                  type="date"
                  min="0001-01-01"
                  max="9999-12-31"
                  className="date-filter-input"
                  value={value[`${field}_${bound}`]}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      [`${field}_${bound}`]: event.target.value,
                    })
                  }
                />
              </label>
            ))}
            {(value[`${field}_min`] ||
              value[`${field}_max`] ||
              (field === 'valid_to' && value.open_ended)) && (
              <ClearFilterButton
                onClick={() =>
                  onChange({
                    ...value,
                    [`${field}_min`]: '',
                    [`${field}_max`]: '',
                    ...(field === 'valid_to' ? { open_ended: '' } : {}),
                  })
                }
              >
                Clear {field === 'valid_from' ? 'valid from' : 'valid to'}
              </ClearFilterButton>
            )}
          </fieldset>
        ))}
        <label className="flex flex-col gap-1 text-sm">
          Open-ended assignments
          <Select
            value={value.open_ended}
            onChange={(event) =>
              onChange({ ...value, open_ended: event.target.value })
            }
          >
            <option value="">Include open-ended dates</option>
            <option value="only">Only valid to 31.12.9999</option>
            <option value="exclude">Exclude valid to 31.12.9999</option>
          </Select>
        </label>
      </div>
      {invalid && (
        <p role="alert">
          Earliest assignment dates must not follow their latest dates.
        </p>
      )}
      <p className="text-xs text-[var(--muted)]">
        Inclusive assignment date bounds. Missing dates do not match an active
        bound; account validity is independent.
      </p>
      {datesActive(value) && (
        <p className="text-sm" aria-label="Active assignment date filters">
          {Object.entries(value)
            .filter(([, v]) => v)
            .map(([key, v]) =>
              key === 'open_ended'
                ? `${v === 'only' ? 'Only' : 'Exclude'} open-ended assignments`
                : `${key.replace(/_/g, ' ')}: ${formatDate(v)}`,
            )
            .join(' · ')}
        </p>
      )}
    </details>
  )
}
