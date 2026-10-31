import { calmZero } from '@/lib/labels'

/** What a KPI figure means. Pages name the metric, never a colour: the mapping from meaning to tone lives here only. */
export type KpiMeaning = 'info' | 'attention' | 'critical' | 'positive'
export type KpiTone = 'neutral' | 'warning' | 'error' | 'success'

const TONE: Record<KpiMeaning, KpiTone> = { info: 'neutral', attention: 'warning', critical: 'error', positive: 'success' }

/**
 * Informational totals are `info` (neutral). `attention` needs investigation or action and is warning, which never claims a confirmed violation.
 * `critical` (danger) is reserved for overdue or otherwise genuinely critical actionable states; `positive` marks completion.
 */
const METRIC_MEANING: Record<string, KpiMeaning> = {
  // SoD Overview and the Dashboard SoD card
  users_with_conflicts: 'attention', multi_risk_users: 'attention', user_risk_findings: 'attention', enabled_risks: 'info',
  activities_pending: 'attention', activities_approved: 'positive', activities_removal: 'attention',
  risks_accepted: 'positive', risks_rejected: 'attention', risk_decisions_pending: 'attention', sod_reviews_pending: 'attention',
  assignments_removal: 'attention', open_actions: 'attention', overdue_actions: 'critical', remediation_awaiting: 'attention',
  // Account Review and the Dashboard directory and review metrics
  requiring_review: 'attention', missing: 'attention', directory_missing: 'attention', directory_ambiguous: 'attention', position_changes: 'attention',
  mismatch: 'attention', ad_disabled_open: 'attention', outdated: 'attention', pending: 'attention', reviewed: 'positive',
}

/** Review states shared by the matrices, work queues and remediation: pending, outdated, rejected and removal need attention; accepted, approved and conditional are settled. */
const STATE_MEANING: Record<string, KpiMeaning> = {
  Pending: 'attention', Outdated: 'attention', 'Needs review': 'attention', Rejected: 'attention', 'Removal required': 'attention', 'Remove assignment': 'attention', 'Investigate assignment': 'attention', 'Removal recommended': 'attention', 'Under investigation': 'attention',
  Accepted: 'positive', Approved: 'positive', Conditional: 'positive', Complete: 'positive', 'Completed (Keep or Remove)': 'positive',
}

const resolve = (meaning: KpiMeaning | undefined, value: unknown): KpiTone => calmZero(TONE[meaning ?? 'info'], value)

/** Tone of a named metric; a zero value is always neutral. Unknown metrics are informational. */
export const kpiTone = (metric: string, value: unknown): KpiTone => resolve(METRIC_MEANING[metric], value)
/** Tone of a review state label (for example a status tile); a zero value is always neutral. */
export const stateTone = (state: string, value: unknown): KpiTone => resolve(STATE_MEANING[state], value)
