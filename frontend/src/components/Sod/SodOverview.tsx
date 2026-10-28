import { useQuery } from '@tanstack/react-query'
import { emptyFilters, sod, type Filters } from '@/api/sod'
import { useHistoryValue, useViewHistory, type SodView } from '@/hooks/useViewHistory'
import { Card, ErrorState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { Button } from '@/components/Shared/Button'
import { formatDate, formatTimestamp } from '@/lib/dateFormat'
import { AlertNote } from './SodShared'

interface Governance {
  available: boolean; reason?: string | null
  users_with_conflicts?: number; user_risk_findings?: number
  activities?: Record<string, number>; assignments?: Record<string, number>; acceptance?: Record<string, number>
  assignments_marked_remove?: number
  remediation?: { open_actions: number; overdue: number; removal_without_action: number }
  periods?: { id: string; name: string; state: string; decided: number; total: number; blocking: number }[]
  change?: { new?: number; no_longer_detected?: number; previous_total?: number; total?: number; since?: string; unavailable?: boolean } | null
  as_of?: string
  latest_approval?: { id: string; name: string; state: string; approval_date: string; approver: string } | null
}
interface Overview {
  counts: Record<string, number | null>
  source: { loaded: boolean; imported_at: string | null; checked_at: string | null }
  coverage: { status: string; eligible_assignment_records?: number; mapped_assignment_records?: number; unmapped_assignment_records?: number }
  governance: Governance
}

export function SodOverview() {
  const result = useQuery({ queryKey: ['sod-overview'], queryFn: () => sod<Overview>('/api/sod/overview') }),
    { change } = useViewHistory(),
    [stored] = useHistoryValue('sodFilters')
  if (result.isError) return <ErrorState error={result.error} onRetry={() => void result.refetch()} title="The SoD overview could not be loaded" />
  if (!result.data) return <LoadingState />
  const { counts, source, coverage, governance: g } = result.data
  const go = (view: SodView, name?: string, patch: Filters = {}, extra: Record<string, unknown> = {}) =>
    change({ sodView: view, ...(name ? { sodFilters: { ...stored, [name]: { ...emptyFilters, ...patch } } } : {}), ...extra })
  const Kpi = ({ label, value, onOpen, tone }: { label: string; value: number | string | undefined; onOpen?: () => void; tone?: 'warning' | 'error' }) => (
    <div className="sod-tile" data-tone={tone && Number(value) > 0 ? tone : undefined}>
      {onOpen ? <button type="button" onClick={onOpen}>{label}</button> : <span>{label}</span>}
      <strong>{value ?? '—'}</strong>
    </div>
  )
  const activities = g.activities || {}, acceptance = g.acceptance || {}
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD overview">
      {!g.available && <Card><AlertNote>Conflict analysis is unavailable ({g.reason === 'sod_disabled' ? 'SoD is turned off in Features' : g.reason === 'mapping_disabled' ? 'User–Role Mapping is disabled' : 'a supported SoD matrix, validated role catalogue and User–Role Mapping data are required'}). Missing evidence is not proof that no conflict exists.</AlertNote>
        <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: g.reason === 'mapping_disabled' || g.reason === 'sod_disabled' ? 'features' : 'sod' })}>Review configuration</Button></Toolbar></Card>}
      {g.available && <section className="sod-overview-figures" aria-label="SoD key figures">
          <div className="sod-kpi-group">
            <h3>Conflicts</h3>
            <div className="sod-tiles">
              <Kpi label="Users with potential conflicts" value={g.users_with_conflicts} onOpen={() => go('risk-matrix', 'riskMatrix')} />
              <Kpi label="Detected user-risk findings" value={g.user_risk_findings} onOpen={() => go('explorer', 'explorer', {}, { sodExplorer: 'user_risk' })} />
              <Kpi label="Enabled risk definitions" value={counts.enabled ?? undefined} onOpen={() => change({ settings: true, settingsTarget: 'sod' })} />
            </div>
          </div>
          <div className="sod-kpi-group">
            <h3>Reviews</h3>
            <div className="sod-tiles">
              <Kpi label="Activities pending or outdated" value={(activities.Pending || 0) + (activities.Outdated || 0)} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Pending' })} />
              <Kpi label="Activities approved or conditional" value={(activities.Approved || 0) + (activities.Conditional || 0)} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Approved' })} />
              <Kpi label="Activities marked for removal" value={activities['Removal required'] || 0} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Removal required' })} />
              <Kpi label="Risks accepted" value={acceptance.Accepted || 0} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Accepted' })} />
              <Kpi label="Risks rejected" value={acceptance.Rejected || 0} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Rejected' })} />
              <Kpi label="Risk decisions pending" value={(acceptance.Pending || 0) + (acceptance.Outdated || 0)} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Pending' })} />
            </div>
          </div>
          <div className="sod-kpi-group">
            <h3>Remediation</h3>
            <div className="sod-tiles">
              <Kpi label="Role assignments marked for removal" value={g.assignments_marked_remove} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi label="Open actions" value={g.remediation?.open_actions} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi label="Overdue actions" value={g.remediation?.overdue} tone="error" onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi label="Removal recommendations without an action" value={g.remediation?.removal_without_action} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
            </div>
          </div>
      </section>}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Card className="content-start" aria-label="Review period progress">
          <h3 className="text-base font-semibold">Review period and approval</h3>
          {g.latest_approval ? <p className="ui-description">Last approved: {g.latest_approval.name} ({g.latest_approval.state}) on {formatDate(g.latest_approval.approval_date)}, approver {g.latest_approval.approver} (self-reported).</p> : <p className="ui-description">No period has been approved yet.</p>}
          {g.periods?.length ? <ul className="grid gap-2">{g.periods.map((period) => (
            <li key={period.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>{period.name}</span>
              <span><StatusBadge>{period.state}</StatusBadge> <progress className="align-middle" max={Math.max(period.total, 1)} value={period.decided} aria-label={`${period.name} decided ${period.decided} of ${period.total}`} /> {period.decided}/{period.total}{period.blocking ? ` · ${period.blocking} blocking approval` : ''}</span>
            </li>))}</ul> : <p className="ui-description">No open review periods.</p>}
          <Toolbar><Button onClick={() => go('periods')}>Open review periods</Button></Toolbar>
        </Card>
        <Card className="content-start" aria-label="Data freshness and coverage">
          <h3 className="text-base font-semibold">Evidence freshness and coverage</h3>
          <p>{g.change ? (g.change.unavailable ? 'A source refresh was detected; the change summary is unavailable because the baseline is too large.' : `Since the previous refresh: ${g.change.new} newly detected and ${g.change.no_longer_detected} no longer detected user-risk findings (${g.change.previous_total} → ${g.change.total}).`) : 'No earlier refresh baseline yet. Changes appear after the next source refresh.'}</p>
          <p className="ui-description">Evaluation date {g.as_of ? formatDate(g.as_of) : '—'} · SoD matrix imported {formatTimestamp(source.imported_at)}, checked {formatTimestamp(source.checked_at)}</p>
          <p className="ui-description">{coverage.status === 'available' ? `${coverage.mapped_assignment_records ?? 0} of ${coverage.eligible_assignment_records ?? 0} eligible assignment records matched to the catalogue (${coverage.unmapped_assignment_records ?? 0} unmatched).` : 'Evidence coverage is incomplete.'}</p>
          <p className="ui-description">Potential transaction-derived conflicts, not effective authorization. Review decisions never change what is detected. Criticality labels keep their source values. Risk definitions are maintained in Settings.</p>
          <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: 'sod' })}>Configure risks in Settings</Button></Toolbar>
        </Card>
      </div>
    </section>
  )
}
