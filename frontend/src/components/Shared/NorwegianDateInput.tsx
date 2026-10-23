import { useEffect, useRef, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { formatDate } from '@/lib/dateFormat'
import { Select } from './Select'

export function parseNorwegianDate(value: string): string | null {
  if (!value.trim()) return ''
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value.trim())
  if (!match) return null
  const iso = `${match[3]}-${match[2]}-${match[1]}`
  return formatDate(iso, '') ? iso : null
}
const isoDay = (year: number, month: number, day: number) =>
  `${String(year).padStart(4, '0')}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
const utc = (iso: string) => new Date(`${iso}T00:00:00Z`)
const months = Array.from({ length: 12 }, (_, month) =>
  new Intl.DateTimeFormat('nb-NO', { month: 'long', timeZone: 'UTC' }).format(
    utc(isoDay(2000, month, 1)),
  ),
)

/** Text and calendar both use Norwegian dates; no locale-dependent native date widget. */
export function NorwegianDateInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (text: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = parseNorwegianDate(value)
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear()),
    [month, setMonth] = useState(today.getMonth())
  const button = useRef<HTMLButtonElement>(null),
    grid = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (open)
      (
        grid.current?.querySelector<HTMLButtonElement>(
          '[aria-pressed="true"]',
        ) ||
        grid.current?.querySelector<HTMLButtonElement>('button[data-day="1"]')
      )?.focus()
  }, [open])
  const first = utc(isoDay(year, month, 1)),
    start = (first.getUTCDay() + 6) % 7
  const days =
    month === 11
      ? 31
      : (utc(isoDay(year, month + 1, 1)).getTime() - first.getTime()) / 86400000
  const move = (delta: number) => {
    const index = year * 12 + month + delta
    const nextYear = Math.floor(index / 12)
    if (nextYear >= 1 && nextYear <= 9999) {
      setYear(nextYear)
      setMonth(index % 12)
    }
  }
  return (
    <div className="norwegian-date-field">
      <label className="flex flex-col gap-1 text-sm">
        {label}
        <span className="flex gap-1">
          <input
            className="date-filter-input"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="DD.MM.YYYY"
            maxLength={10}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={value.trim() !== '' && selected === null}
          />
          <button
            ref={button}
            type="button"
            className="settings-secondary-button"
            aria-label={`Choose ${label}`}
            aria-expanded={open}
            onClick={() => {
              if (selected) {
                const date = utc(selected)
                setYear(date.getUTCFullYear())
                setMonth(date.getUTCMonth())
              }
              setOpen(!open)
            }}
          >
            <CalendarDays size={16} aria-hidden="true" />
          </button>
        </span>
      </label>
      {open && (
        <div
          className="norwegian-calendar space-y-2"
          role="group"
          aria-label={`Calendar for ${label}`}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              event.stopPropagation()
              setOpen(false)
              button.current?.focus()
            }
          }}
        >
          <div className="flex gap-2 items-center">
            <button
              type="button"
              className="settings-secondary-button"
              aria-label="Previous month"
              disabled={year === 1 && month === 0}
              onClick={() => move(-1)}
            >
              <ChevronLeft size={14} />
            </button>
            <Select
              aria-label="Calendar month"
              value={month}
              onChange={(event) => setMonth(Number(event.target.value))}
            >
              {months.map((name, index) => (
                <option key={name} value={index}>
                  {name}
                </option>
              ))}
            </Select>
            <input
              className="date-filter-input"
              type="number"
              aria-label="Calendar year"
              min={1}
              max={9999}
              value={year}
              onChange={(event) => {
                const next = Number(event.target.value)
                if (Number.isInteger(next) && next >= 1 && next <= 9999) setYear(next)
              }}
            />
            <button
              type="button"
              className="settings-secondary-button"
              aria-label="Next month"
              disabled={year === 9999 && month === 11}
              onClick={() => move(1)}
            >
              <ChevronRight size={14} />
            </button>
          </div>
          <p className="text-sm font-semibold">
            {months[month]} {String(year).padStart(4, '0')}
          </p>
          <div
            className="calendar-grid"
            ref={grid}
            role="group"
            aria-label="Calendar days"
          >
            <>
              {['man', 'tir', 'ons', 'tor', 'fre', 'lør', 'søn'].map((day) => (
                <span key={day} className="text-xs text-center">
                  {day}
                </span>
              ))}
              {Array.from({ length: start }, (_, i) => (
                <span key={`empty-${i}`} />
              ))}
              {Array.from({ length: days }, (_, i) => {
                const day = i + 1,
                  iso = isoDay(year, month, day)
                return (
                  <button
                    type="button"
                    key={day}
                    data-day={day}
                    className="calendar-day"
                    aria-pressed={selected === iso}
                    aria-label={formatDate(iso)}
                    onClick={() => {
                      onChange(formatDate(iso))
                      setOpen(false)
                      button.current?.focus()
                    }}
                    onKeyDown={(event) => {
                      const delta = (
                        {
                          ArrowRight: 1,
                          ArrowLeft: -1,
                          ArrowDown: 7,
                          ArrowUp: -7,
                        } as Record<string, number>
                      )[event.key]
                      if (delta) {
                        event.preventDefault()
                        grid.current
                          ?.querySelector<HTMLButtonElement>(
                            `button[data-day="${Math.max(1, Math.min(days, day + delta))}"]`,
                          )
                          ?.focus()
                      }
                    }}
                  >
                    {day}
                  </button>
                )
              })}
            </>
          </div>
        </div>
      )}
    </div>
  )
}
