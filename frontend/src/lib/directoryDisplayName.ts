/** Display only: recognize exactly two letter-only name parts in 'Surname, Given names' form. */
export function directoryDisplayName(value: string): string {
  const parts = value.trim().split(',')
  const name = /^[\p{L}\p{M}]+(?:[\s'’\-][\p{L}\p{M}]+)*$/u
  return parts.length === 2 &&
    parts.every(
      (part) =>
        name.test(part.trim()) &&
        [...part.replace(/[^\p{L}]/gu, '')].length >= 2,
    )
    ? `${parts[1].trim()} ${parts[0].trim()}`
    : value.trim()
}
