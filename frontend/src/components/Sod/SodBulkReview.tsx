import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { sodPost, type AssignmentPick, type BulkAction, type BulkResult, type ContextInfo } from '@/api/sod'
import { Dialog } from '@/components/Shared/Dialog'
import { Button } from '@/components/Shared/Button'
import { Checkbox, FormField, Input } from '@/components/Shared/Controls'
import { StatusBadge } from '@/components/Shared/Presentation'

const COPY: Record<BulkAction, { title: string; verb: string; effect: string; confirm: string }> = {
  Keep: { title: 'Keep assignments', verb: 'Keep', effect: 'Each assignment gets its own Keep review event with the reviewer and rationale below.', confirm: 'Keep' },
  Remove: { title: 'Recommend removal', verb: 'Recommend removal', effect: 'Each assignment is marked Remove in its review history. This records a recommendation only: no role is removed from SAP and no imported data changes.', confirm: 'Recommend removal for' },
  Investigate: { title: 'Mark for further investigation', verb: 'Investigate', effect: 'Each assignment gets a tracked Investigate assignment remediation action. The review decision stays unchanged.', confirm: 'Track investigation for' },
}
const counted = (items: string[]) => [...items.reduce((map, value) => map.set(value, (map.get(value) || 0) + 1), new Map<string, number>())].sort(([x], [y]) => x.localeCompare(y))

/** Confirmation and result of a batch review. Success is shown only for assignments the server reports as persisted. */
export function BulkReviewDialog({ action, picks: livePicks, info, onClose, onApplied }: { action: BulkAction; picks: AssignmentPick[]; info: ContextInfo & { revision: number }; onClose: () => void; onApplied: (recorded: string[]) => void }) {
  const copy = COPY[action], qc = useQueryClient()
  // The dialog reports on the selection it was opened with, even after saved assignments leave the live selection.
  const [picks] = useState(livePicks)
  const [reviewer, setReviewer] = useState(''), [rationale, setRationale] = useState(''), [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [result, setResult] = useState<BulkResult | null>(null)
  const users = counted(picks.map((pick) => pick.user)), suffixes = counted(picks.map((pick) => pick.suffix || 'No suffix')), roles = new Set(picks.map((pick) => pick.ref)).size
  const reviewed = action === 'Investigate' ? [] : picks.filter((pick) => pick.decision !== 'Pending')
  const ready = !!reviewer.trim() && !!rationale.trim() && (!reviewed.length || replace) && !busy
  const apply = async () => {
    setBusy(true); setError('')
    try {
      const response = await sodPost<BulkResult>('/api/sod/decisions/assignment/bulk', {
        context: info.context, expected_revision: info.revision, expected_generation: info.generation, action, reviewer: reviewer.trim(), justification: rationale.trim(), replace_existing: replace,
        items: picks.map((pick) => ({ key: pick.key, user: pick.user, ref: pick.ref, evidence_version: pick.evidence_version })),
      })
      setResult(response)
      onApplied(response.recorded)
      await qc.invalidateQueries({ predicate: (query) => ['sod-explorer', 'sod-matrix', 'sod-overview', 'sod-queue', 'sod-remediation', 'sod-subject'].includes(String(query.queryKey[0])) })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The review could not be saved. Nothing was reported as saved.')
    } finally { setBusy(false) }
  }
  if (result) {
    const problems = result.failed.length + result.skipped.length
    return (
      <Dialog title={copy.title} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
        <div className="bulk-dialog" role="region" aria-label="Batch review result">
          <p role="status" className="flex items-center gap-2 font-semibold">{problems ? <AlertTriangle size={16} aria-hidden="true" /> : <CheckCircle2 size={16} aria-hidden="true" />}
            {result.recorded.length} of {picks.length} {picks.length === 1 ? 'assignment' : 'assignments'} saved{problems ? `; ${result.skipped.length} skipped and ${result.failed.length} failed` : ''}.</p>
          {!!result.skipped.length && <><h3 className="text-sm font-semibold">Skipped, nothing changed</h3><ul className="bulk-outcome">{result.skipped.map((item) => <li key={item.key}><strong>{item.user}</strong> {item.ref}: {item.reason}</li>)}</ul></>}
          {!!result.failed.length && <><h3 className="text-sm font-semibold">Failed, nothing saved</h3><ul className="bulk-outcome" role="alert">{result.failed.map((item) => <li key={item.key}><strong>{item.user}</strong> {item.ref}: {item.reason}</li>)}</ul></>}
          {problems > 0 && <p className="ui-description">Skipped and failed assignments stay selected so you can adjust and retry.</p>}
        </div>
      </Dialog>
    )
  }
  return (
    <Dialog title={copy.title} onClose={() => { if (!busy) onClose() }}
      footer={<><Button disabled={busy} onClick={onClose}>Cancel</Button><Button variant={action === 'Remove' ? 'destructive' : 'primary'} loading={busy} disabled={!ready} onClick={() => void apply()}>{copy.confirm} {picks.length} {picks.length === 1 ? 'assignment' : 'assignments'}</Button></>}>
      <div className="bulk-dialog" role="region" aria-label="Batch review summary">
        <dl className="bulk-dialog-summary">
          <div><dt>Assignments affected</dt><dd>{picks.length}</dd></div>
          <div><dt>SAP users</dt><dd>{users.length}</dd></div>
          <div><dt>Distinct roles</dt><dd>{roles}</dd></div>
          <div><dt>Role suffixes</dt><dd>{suffixes.length}</dd></div>
        </dl>
        <p className="ui-description">{copy.effect}</p>
        <section aria-label="Selected SAP users"><h3 className="text-sm font-semibold">SAP users</h3>
          <ul className="bulk-chip-list">{users.slice(0, 30).map(([name, count]) => <li key={name}><StatusBadge>{name} · {count}</StatusBadge></li>)}{users.length > 30 && <li className="ui-description">and {users.length - 30} more users</li>}</ul></section>
        <section aria-label="Selected role suffixes"><h3 className="text-sm font-semibold">Role suffixes</h3>
          <ul className="bulk-chip-list">{suffixes.map(([name, count]) => <li key={name}><StatusBadge>{name} · {count}</StatusBadge></li>)}</ul></section>
        {!!reviewed.length && (
          <section aria-label="Existing decisions" className="review-dialog-trigger">
            <h3>{reviewed.length} {reviewed.length === 1 ? 'assignment has' : 'assignments have'} an earlier review decision</h3>
            <p className="ui-description">Replacing keeps the earlier decisions in each assignment history. They are never overwritten silently.</p>
            <Checkbox checked={replace} onChange={(event) => setReplace(event.target.checked)}>Replace the existing decisions of these {reviewed.length} assignments</Checkbox>
          </section>
        )}
        <div className="review-dialog-fields">
          <FormField label="Reviewer"><Input maxLength={120} value={reviewer} placeholder="Your name (self-declared)" onChange={(event) => setReviewer(event.target.value)} /></FormField>
          <FormField label="Rationale"><Input maxLength={2000} value={rationale} placeholder="Why this applies to the selected assignments" onChange={(event) => setRationale(event.target.value)} /></FormField>
        </div>
        <p className="ui-description">The reviewer name is self-declared and the decision is a local annotation: nothing is sent to or changed in SAP.</p>
        {error && <p role="alert" className="text-[var(--error)]">{error}</p>}
      </div>
    </Dialog>
  )
}
