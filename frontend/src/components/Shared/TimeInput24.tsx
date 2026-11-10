import { useEffect, useState } from 'react'
import { normalizeTimeOfDay } from '@/lib/dateFormat'
import { Input } from './Controls'

/** 24-hour time of day (HH:mm). A native <input type="time"> follows the browser locale and shows AM/PM, so this is a text field with a fixed format:
 *  it reports a value only when it is valid, and marks invalid text instead of guessing. */
export function TimeInput24({ value, onChange, label = 'Time (24-hour, HH:mm)', ...rest }: { value: string; onChange: (value: string) => void; label?: string; id?: string; disabled?: boolean }) {
  const [text, setText] = useState(value)
  useEffect(() => { setText(value) }, [value])
  const valid = normalizeTimeOfDay(text) !== null
  return (
    <Input {...rest} inputMode="numeric" autoComplete="off" maxLength={8} placeholder="HH:mm" aria-label={label} aria-invalid={!valid || undefined} pattern="([01][0-9]|2[0-3]):[0-5][0-9]" value={text}
      onChange={event => { const next = event.target.value; setText(next); const normal = normalizeTimeOfDay(next); if (normal) onChange(normal) }}
      onBlur={() => { const normal = normalizeTimeOfDay(text); setText(normal ?? value) }} />
  )
}
