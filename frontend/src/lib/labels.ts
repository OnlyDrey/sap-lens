/** A zero count never carries warning, danger or success styling: nothing found, nothing overdue and nothing completed are neutral facts. */
export const isZeroValue = (value: unknown) => value === 0 || (typeof value === 'string' && /^0(?:\.0+)?%?$/.test(value.trim()))
export const calmZero = <T extends string>(tone: T, value: unknown): T | 'neutral' => (isZeroValue(value) && (tone === 'warning' || tone === 'error' || tone === 'success') ? 'neutral' : tone)

/** Internal enum values (`directory_match`, `missing_email`, `ad_disabled`) never reach the interface as typed: they become sentence case with the usual acronyms kept. */
const ACRONYMS = /\b(sap|ad|csv|sod|id|pr|po|unc|ldap|url)\b/gi
export function sentenceCase(value: string | null | undefined): string {
  const text = (value ?? '').replace(/[_-]+/g, ' ').trim().toLowerCase().replace(ACRONYMS, (match) => (match.toLowerCase() === 'sod' ? 'SoD' : match.toUpperCase()))
  return text.charAt(0).toUpperCase() + text.slice(1)
}
