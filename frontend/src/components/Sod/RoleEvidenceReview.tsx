import { useQuery } from '@tanstack/react-query'
import { Check, Search, Trash2 } from 'lucide-react'
import { emptyFilters, scopeParams, sod, type OverviewAssignment, type Subject } from '@/api/sod'
import { Button } from '@/components/Shared/Button'
import { decisionVariant, type DecisionChoiceValue } from '@/components/Shared/DecisionChoice'
import { FormField, Input } from '@/components/Shared/Controls'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { DataTable } from '@/components/Shared/Presentation'
import { formatDate } from '@/lib/dateFormat'
import { SodDecisionStatus } from './SodDecisionStatus'
import { QUICK_RATIONALE, useAssignmentQuickReview } from './useAssignmentQuickReview'

const ACTIONS: { value: DecisionChoiceValue; label: string; icon: typeof Search; selected: (row: OverviewAssignment) => boolean; hint: string }[] = [
  { value: 'Investigate', label: 'Investigate', icon: Search, selected: row => row.decision === 'Investigate', hint: 'Mark for further investigation (not a final decision)' },
  { value: 'Keep', label: 'Keep', icon: Check, selected: row => row.decision === 'Keep', hint: 'Keep this role assignment' },
  { value: 'Remove', label: 'Remove', icon: Trash2, selected: row => row.decision === 'Removal required', hint: 'Recommend removing this role assignment (no change in SAP)' },
]

/** Role table of the Role Evidence modal with the Role Assignment Review decision per assignment. Decisions use the same service as the review panel
 *  (`/api/sod/decisions/assignment`, keyed by the assignment id of this user), are confirmed by the server before a row changes, and only record a
 *  recommendation: imported SAP assignments, mappings and evidence snapshots are never modified. */
export function RoleEvidenceReview({ context, user, risk, roles }: { context: string; user: string; risk: string; roles: string[] }) {
  const params = scopeParams(context, emptyFilters, { user, risk })
  const query = useQuery({ queryKey: ['sod-subject', params.toString()], queryFn: () => sod<Subject>('/api/sod/subject', params) })
  const review = useAssignmentQuickReview(user, params, query.data)
  const assignments = (query.data?.overview.assignments ?? []).filter(row => row.risks.includes(risk))
  const byRole = new Map<string, OverviewAssignment[]>()
  for (const row of assignments) byRole.set(row.role, [...(byRole.get(row.role) ?? []), row])
  const reviewable = !!query.data?.reviewable&&review.canDecide
  const rows = roles.flatMap(role => (byRole.get(role) ?? [undefined]).map(assignment => ({ role, assignment, several: (byRole.get(role)?.length ?? 0) > 1 })))
  return (
    <>
      {reviewable && !review.authenticated && (
        <FormField label={review.authenticated?'Reviewer (authenticated)':'Reviewer (local profile, self-reported)'}><Input readOnly value={review.reviewer} maxLength={120} placeholder="Your name" onChange={event => review.setQuickReviewer(event.target.value)} /></FormField>
      )}
      {reviewable && <FormField label="Rationale (optional)"><Input value={review.quickRationale} maxLength={400} placeholder={QUICK_RATIONALE} onChange={event => review.setQuickRationale(event.target.value)} /></FormField>}
      {query.isError && <p role="alert">Review decisions could not be loaded. The roles are shown without review actions.</p>}
      {query.data && !reviewable && <p className="ui-description">Decisions are not available for this review context (for example a frozen/historical period or read-only account).</p>}
      {review.quickError && <p role="alert" className="text-[var(--error)]">{review.quickError}</p>}
      <div className="evidence-scroll" tabIndex={0} role="region" aria-label="Roles supplying this evidence">
        <DataTable caption="Roles supplying this evidence" density="compact">
          <thead><tr><th>Role</th><th>Status</th><th className="col-actions">Review actions</th></tr></thead>
          <tbody>{rows.map(({ role, assignment, several }) => {
            const pending = assignment ? review.quickBusy.get(assignment.id) : undefined
            return (
              <tr key={assignment?.id ?? role} data-assignment-id={assignment?.id}>
                <td className="col-role"><RoleIdentifier value={role} label="assigned role" />{several && assignment && <span className="ui-description">{formatDate(assignment.valid_from)} → {formatDate(assignment.valid_to)}</span>}</td>
                <td className="whitespace-nowrap">{assignment
                  ? <SodDecisionStatus kind="assignment" label={role} status={assignment.decision} summary={assignment.decision_summary} event={assignment.event} coverage={assignment.review_coverage} user={user} context={context} assignmentId={assignment.id} validFrom={assignment.valid_from} validTo={assignment.valid_to} verification={assignment.remediation_verification} activities={assignment.activities} risks={assignment.risks} />
                  : <span className="text-muted">{query.isLoading ? 'Loading…' : 'Not reviewable'}</span>}</td>
                <td className="col-actions">
                  {assignment && reviewable && (
                    <span className="sod-decision-icons" role="group" aria-label={`Review ${role}`}>
                      {ACTIONS.map(({ value, label, icon: Icon, selected, hint }) => {
                        const active = selected(assignment)
                        return <Button key={value} size="compact" variant={decisionVariant(value, active)} aria-pressed={active} title={hint} aria-label={`${label} ${role}`}
                          loading={pending === value} disabled={!!pending} onClick={() => review.quickDecide(assignment, value as 'Keep' | 'Remove' | 'Investigate')}>{pending === value ? null : <Icon size={14} aria-hidden="true" />}{label}</Button>
                      })}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}</tbody>
        </DataTable>
      </div>
    </>
  )
}
