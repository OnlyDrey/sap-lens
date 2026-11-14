/** One presentation of a count in the Functional Group settings: zero is plain muted text, a positive number opens its list, unknown is "n/a". */
export function GroupCount({ count, label, onOpen }: { count: number | null | undefined; label: string; onOpen: () => void }) {
  if (count == null) return <span className="text-muted">n/a</span>
  if (count === 0) return <span className="text-muted">0</span>
  return <button type="button" className="role-count-button" aria-label={label} onClick={onOpen}>{count.toLocaleString()}</button>
}
