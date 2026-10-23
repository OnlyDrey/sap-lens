const dateOnly = /^\d{4}-\d{2}-\d{2}$/
export function formatDate(value?: string | null, fallback = 'Unknown'): string {
  if (!value || !dateOnly.test(value) || value.startsWith('0000')) return fallback
  const date = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) return fallback
  const parts = new Intl.DateTimeFormat('nb-NO', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }).formatToParts(date)
  const get = (type: string) => parts.find(part => part.type === type)?.value || ''
  return `${get('day')}.${get('month')}.${get('year').padStart(4, '0')}`
}
export function formatTimestamp(value?: string | null, fallback = 'Not available', seconds = false): string {
  if (!value || value.startsWith('0000')) return fallback
  if (dateOnly.test(value)) return formatDate(value, fallback)
  const day = value.slice(0, 10)
  if (dateOnly.test(day) && !formatDate(day, '')) return fallback
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return fallback
  // Offset-bearing instants display in local time; unzoned local strings stay local.
  const parts = new Intl.DateTimeFormat('nb-NO', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hourCycle: 'h23' }).formatToParts(date)
  const get = (key: string) => parts.find(part => part.type === key)?.value || ''
  return `${get('day')}.${get('month')}.${get('year').padStart(4, '0')} ${get('hour')}:${get('minute')}${seconds ? ':' + get('second') : ''}`
}
