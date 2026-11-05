/** Revision of the data the API serves, as sent in `X-Data-Revision` (`boot.publication.directory`).
 *  Ordering is only defined within one backend process: another boot is always newer (a restart replaces the process, it never comes back). */
export type DataRevision = { boot: string; publication: number; directory: number }

export function parseRevision(token: string | null | undefined): DataRevision | null {
  const match = /^([a-f0-9]+)\.(\d+)\.(\d+)$/.exec(token ?? '')
  return match ? { boot: match[1], publication: Number(match[2]), directory: Number(match[3]) } : null
}

/** Positive when `candidate` is newer than `known`, negative when it is older (stale), zero when equal. */
export function compareRevision(candidate: DataRevision, known: DataRevision): number {
  if (candidate.boot !== known.boot) return 1
  return candidate.publication - known.publication || candidate.directory - known.directory
}

export type Observation = 'first' | 'same' | 'newer' | 'stale'

/** Tracks the newest revision seen. A response older than that must not replace newer data; a newer one means the data changed under this client. */
export class RevisionTracker {
  private known: DataRevision | null = null
  get current(): DataRevision | null { return this.known }
  observe(token: string | null | undefined): Observation {
    const revision = parseRevision(token)
    if (!revision) return 'same'                       // an older backend without the header: nothing can be concluded
    if (!this.known) { this.known = revision; return 'first' }
    const order = compareRevision(revision, this.known)
    if (order > 0) { this.known = revision; return 'newer' }
    return order < 0 ? 'stale' : 'same'
  }
}
