import type { ClassificationStatus } from '../api/functionalGroups.ts'
import { formatDate } from './dateFormat.ts'

/** Last confirmation as stored: a missing date and a missing reviewer are reported separately, and nothing is invented. */
export function confirmationText(confirmedAt: string | null | undefined, confirmedBy: string | null | undefined, confirmed: boolean): string | null {
  const when = confirmedAt ? formatDate(confirmedAt) : '', who = (confirmedBy ?? '').trim()
  if (when && who) return `Last confirmed ${when} by ${who}`
  if (when) return `Last confirmed ${when}; reviewer not recorded`
  if (who) return `Last confirmed by ${who}; date not recorded`
  return confirmed ? 'Confirmed; date and reviewer not recorded' : null
}

/** The action names what will happen: assign, change a confirmed assignment, or confirm one that still needs it. */
export function actionLabel(hasGroup: boolean, status: ClassificationStatus): string {
  if (!hasGroup) return 'Assign group'
  return status === 'Confirmed' ? 'Change group' : 'Assign / Confirm'
}

export type PatternKind = 'common' | 'shared' | 'uncommon' | 'not compared'
const PATTERN_LABELS: Record<PatternKind, string> = { common: 'Common', shared: 'Shared', uncommon: 'Uncommon', 'not compared': 'Not compared' }
/** Display label of an Access Analysis pattern. The API/enum value (lower case) is unchanged. */
export const patternLabel = (kind: PatternKind): string => PATTERN_LABELS[kind] ?? kind
export const patternTone = (kind: PatternKind): 'warning' | 'success' | 'neutral' => (kind === 'uncommon' ? 'warning' : kind === 'common' ? 'success' : 'neutral')

/** Consistent text for a user's memberships in compact places (tables, exports): names joined with "; ", or "Unassigned". */
export const membershipNames = (groups: { name: string }[] | undefined | null): string => (groups && groups.length ? groups.map(group => group.name).join('; ') : 'Unassigned')
