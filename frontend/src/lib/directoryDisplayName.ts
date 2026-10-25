/** Display only: recognize exactly two letter-only name parts in 'Surname, Given names' form. */
export function directoryDisplayName(value: string): string {
  const parts = value.trim().split(',')
  const name = /^[\p{L}\p{M}]+(?:[\s'’\-][\p{L}\p{M}]+)*$/u
  const comma =
    parts.length === 2 &&
    !/^(Jr|Sr|II|III|IV)\.?$/i.test(parts[1].trim()) &&
    parts.every(
      (part) =>
        name.test(part.trim()) &&
        [...part.replace(/[^\p{L}]/gu, '')].length >= 2,
    )
      ? `${parts[1].trim()} ${parts[0].trim()}`
      : null
  if (comma) return comma
  const tokens = value.trim().split(/\s+/)
  const upper = (v: string) =>
    /^[\p{Lu}\p{M}]+(?:[’'\-][\p{Lu}\p{M}]+)*$/u.test(v) && v.length > 1
  const boundary = tokens.findIndex((token) => !upper(token))
  return boundary > 0 &&
    tokens
      .slice(boundary)
      .every((token) => name.test(token) && /[\p{Ll}]/u.test(token))
    ? [...tokens.slice(boundary), ...tokens.slice(0, boundary)].join(' ')
    : value.trim()
}
