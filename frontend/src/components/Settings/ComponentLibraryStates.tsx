import { useState } from 'react'
import { Button } from '@/components/Shared/Button'
import { Card } from '@/components/Shared/Presentation'
import { ConfirmDialog } from '@/components/Shared/ConfirmDialog'
import { DecisionChoice, type DecisionChoiceValue } from '@/components/Shared/DecisionChoice'
import { FilterChip } from '@/components/Shared/FilterChip'
import { IdPill } from '@/components/Shared/IdPill'
import { EnabledBadge, ModeBadge } from '@/components/Shared/StatusBadges'
import { StatusPill } from '@/components/Shared/StatusPill'
import { TimeInput24 } from '@/components/Shared/TimeInput24'
import { UserGroupCell } from '@/components/Shared/UserGroup'

const CHIPS = ['SU01', 'PFCG', 'SE16N']

/**
 * Production Shared components that the application uses on several screens, rendered in their meaningful states so their generic
 * behavior (selection, removal, toggling, validation, confirmation) is tested once here (frontend/tests/component-library.spec.ts)
 * instead of on every page. Synthetic values only; nothing here reads or writes application data.
 */
export function ComponentLibraryStates() {
  const [decision, setDecision] = useState<DecisionChoiceValue | null>(null)
  const [chips, setChips] = useState(CHIPS)
  const [enabled, setEnabled] = useState(true)
  const [time, setTime] = useState('02:00')
  const [confirming, setConfirming] = useState(false)
  const [outcome, setOutcome] = useState('No confirmation requested')
  return (
    <Card aria-label="Decision, chip and status previews">
      <h2>Decisions, chips and status</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-label="Decision choice preview" className="grid gap-2">
          <DecisionChoice label="Demo proposed decision" value={decision} onChange={setDecision} emptyHint="No decision is preselected." />
          <p aria-live="polite">Selected decision: {decision ?? 'none'}</p>
          <DecisionChoice label="Demo disabled decision" value="Keep" onChange={() => undefined} disabled />
        </section>
        <section aria-label="Filter chip preview" className="grid gap-2">
          <div className="flex flex-wrap gap-2">
            {chips.map(chip => <FilterChip key={chip} removeLabel={`Remove ${chip} filter`} onRemove={() => setChips(chips.filter(item => item !== chip))}>{chip}</FilterChip>)}
            {!chips.length && <span className="ui-description">No transaction filters</span>}
          </div>
          <Button size="compact" onClick={() => setChips(CHIPS)} disabled={chips.length === CHIPS.length}>Reset demo chips</Button>
        </section>
        <section aria-label="Status pill and badge preview" className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill enabled={enabled} onToggle={() => setEnabled(!enabled)} label="Demo feature enabled" />
            <StatusPill enabled={false} onToggle={() => undefined} label="Demo locked feature" disabled />
            <StatusPill enabled />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <EnabledBadge enabled /><EnabledBadge enabled={false} /><ModeBadge mode="static" /><ModeBadge mode="dynamic" /><ModeBadge mode={undefined} />
          </div>
        </section>
        <section aria-label="Identifier and group preview" className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2"><IdPill kind="risk" value="R001" /><IdPill kind="activity" value="A010" /></div>
          <table className="w-auto"><caption className="sr-only">SAP User Group cells</caption><tbody>
            <tr><th scope="row">Several groups</th><td><UserGroupCell groups={['FINANCE', 'SUPPORT']} /></td></tr>
            <tr><th scope="row">No group</th><td><UserGroupCell groups={null} /></td></tr>
          </tbody></table>
        </section>
        <section aria-label="Time and confirmation preview" className="grid gap-2">
          <TimeInput24 value={time} onChange={setTime} label="Demo backup time (24-hour, HH:mm)" />
          <p aria-live="polite">Accepted time: {time}</p>
          <Button variant="destructive" onClick={() => setConfirming(true)}>Delete demo record</Button>
          <p aria-live="polite">{outcome}</p>
          {confirming && <ConfirmDialog title="Delete demo record" confirmLabel="Delete demo record" onCancel={() => { setConfirming(false); setOutcome('Deletion cancelled') }} onConfirm={() => { setConfirming(false); setOutcome('Demo record deleted') }}>
            The synthetic record is removed from this preview only.
          </ConfirmDialog>}
        </section>
      </div>
    </Card>
  )
}
