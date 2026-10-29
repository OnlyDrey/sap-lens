import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleDashed, ClipboardCheck, Grid3x3, ListChecks, ShieldAlert, ShieldCheck, ShieldX, UserMinus, UsersRound, Wrench } from 'lucide-react'
import { emptyFilters, sod, type Filters } from '@/api/sod'
import { useHistoryValue, useViewHistory, type SodView } from '@/hooks/useViewHistory'
import { Card, ErrorState, LoadingState, SectionHeader, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { MetricTile } from '@/components/Shared/MetricTile'
import { Button } from '@/components/Shared/Button'
import { formatDate, formatTimestamp } from '@/lib/dateFormat'
import { AlertNote } from './SodShared'
import { SodGroupHeatmap } from './SodGroupHeatmap'

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
  const Kpi = ({ icon, label, value, onOpen, tone }: { icon: ReactNode; label: string; value: number | string | undefined; onOpen?: () => void; tone?: 'warning' | 'error' }) => (
    <MetricTile icon={icon} label={label} value={value} onOpen={onOpen} tone={tone} />
  )
  const activities = g.activities || {}, acceptance = g.acceptance || {}
  return (
    <section className="grid min-w-0 gap-4" aria-label="SoD overview">
      {!g.available && <Card><AlertNote>Conflict analysis is unavailable ({g.reason === 'sod_disabled' ? 'SoD is turned off in Features' : g.reason === 'mapping_disabled' ? 'User–Role Mapping is disabled' : 'a supported SoD matrix, validated role catalogue and User–Role Mapping data are required'}). Missing evidence is not proof that no conflict exists.</AlertNote>
        <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: g.reason === 'mapping_disabled' || g.reason === 'sod_disabled' ? 'features' : 'sod' })}>Review configuration</Button></Toolbar></Card>}
      {g.available && <section className="dashboard-workspace sod-overview-cards" aria-label="SoD key figures">
          <section className="dashboard-section min-w-0 rounded-card bg-surface p-4" aria-label="Conflicts">
            <SectionHeader title="Conflicts" icon={<ShieldAlert size={18} aria-hidden="true" />} />
            <div className="dashboard-metrics dashboard-secondary-metrics">
              <Kpi icon={<UsersRound size={18} aria-hidden="true" />} label="Users with potential conflicts" value={g.users_with_conflicts} onOpen={() => go('risk-matrix', 'riskMatrix')} />
              <Kpi icon={<Grid3x3 size={18} aria-hidden="true" />} label="Detected user-risk findings" value={g.user_risk_findings} onOpen={() => go('explorer', 'explorer', {}, { sodExplorer: 'user_risk' })} />
              <Kpi icon={<ListChecks size={18} aria-hidden="true" />} label="Enabled risk definitions" value={counts.enabled ?? undefined} onOpen={() => change({ settings: true, settingsTarget: 'sod' })} />
            </div>
          </section>
          <section className="dashboard-section min-w-0 rounded-card bg-surface p-4" aria-label="Reviews">
            <SectionHeader title="Reviews" icon={<ClipboardCheck size={18} aria-hidden="true" />} />
            <div className="dashboard-metrics dashboard-secondary-metrics">
              <Kpi icon={<CircleDashed size={18} aria-hidden="true" />} label="Activities pending or outdated" value={(activities.Pending || 0) + (activities.Outdated || 0)} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Pending' })} />
              <Kpi icon={<CheckCircle2 size={18} aria-hidden="true" />} label="Activities approved or conditional" value={(activities.Approved || 0) + (activities.Conditional || 0)} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Approved' })} />
              <Kpi icon={<UserMinus size={18} aria-hidden="true" />} label="Activities marked for removal" value={activities['Removal required'] || 0} onOpen={() => go('activity-matrix', 'activityMatrix', { activity_decision: 'Removal required' })} />
              <Kpi icon={<ShieldCheck size={18} aria-hidden="true" />} label="Risks accepted" value={acceptance.Accepted || 0} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Accepted' })} />
              <Kpi icon={<ShieldX size={18} aria-hidden="true" />} label="Risks rejected" value={acceptance.Rejected || 0} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Rejected' })} />
              <Kpi icon={<CircleDashed size={18} aria-hidden="true" />} label="Risk decisions pending" value={(acceptance.Pending || 0) + (acceptance.Outdated || 0)} onOpen={() => go('risk-matrix', 'riskMatrix', { acceptance: 'Pending' })} />
            </div>
          </section>
          <section className="dashboard-section min-w-0 rounded-card bg-surface p-4" aria-label="Remediation">
            <SectionHeader title="Remediation" icon={<Wrench size={18} aria-hidden="true" />} />
            <div className="dashboard-metrics dashboard-secondary-metrics">
              <Kpi icon={<UserMinus size={18} aria-hidden="true" />} label="Role assignments marked for removal" value={g.assignments_marked_remove} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi icon={<ListChecks size={18} aria-hidden="true" />} label="Open actions" value={g.remediation?.open_actions} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi icon={<AlertTriangle size={18} aria-hidden="true" />} label="Overdue actions" value={g.remediation?.overdue} tone="error" onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
              <Kpi icon={<Wrench size={18} aria-hidden="true" />} label="Removal recommendations without an action" value={g.remediation?.removal_without_action} onOpen={() => go('reviews', undefined, {}, { sodReviews: 'remediation' })} />
            </div>
          </section>
        </section>}
      {g.available && <SodGroupHeatmap onOpen={(kind, patch) => go(kind === 'risk' ? 'risk-matrix' : 'activity-matrix', kind === 'risk' ? 'riskMatrix' : 'activityMatrix', patch)} />}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Card className="content-start" aria-label="Review period progress">
          <SectionHeader title="Review period and approval" icon={<ClipboardCheck size={18} aria-hidden="true" />} />
          {g.latest_approval
            ? <p className="ui-description">Last approved: <strong>{g.latest_approval.name}</strong> ({g.latest_approval.state}) on {formatDate(g.latest_approval.approval_date)}, approver {g.latest_approval.approver} (self-reported).</p>
            : <p className="ui-description">No period has been approved yet.</p>}
          {g.periods?.length ? <ul className="overview-periods" aria-label="Open review periods">{g.periods.map((period) => (
            <li key={period.id}>
              <span className="overview-period-name">{period.name}</span>
              <StatusBadge>{period.state}</StatusBadge>
              <progress max={Math.max(period.total, 1)} value={period.decided} aria-label={`${period.name} decided ${period.decided} of ${period.total}`} />
              <span className="overview-period-count">{period.decided}/{period.total}{period.blocking ? ` · ${period.blocking} blocking approval` : ''}</span>
            </li>))}</ul> : <p className="ui-description">No open review periods.</p>}
          <Toolbar><Button onClick={() => go('periods')}>Open review periods</Button></Toolbar>
        </Card>
        <Card className="content-start" aria-label="Data freshness and coverage">
          <SectionHeader title="Evidence freshness and coverage" icon={<ShieldCheck size={18} aria-hidden="true" />} />
          <dl className="overview-facts">
            <div><dt>Evaluation date</dt><dd>{g.as_of ? formatDate(g.as_of) : '—'}</dd></div>
            <div><dt>SoD matrix imported</dt><dd>{formatTimestamp(source.imported_at)}</dd></div>
            <div><dt>Last checked</dt><dd>{formatTimestamp(source.checked_at)}</dd></div>
            <div><dt>Since the previous refresh</dt><dd>{g.change ? (g.change.unavailable ? 'Change summary unavailable (baseline too large)' : `${g.change.new} newly detected · ${g.change.no_longer_detected} no longer detected (${g.change.previous_total} → ${g.change.total} user-risk findings)`) : 'No earlier baseline yet'}</dd></div>
            <div><dt>Catalogue coverage</dt><dd>{coverage.status === 'available' ? `${coverage.mapped_assignment_records ?? 0} of ${coverage.eligible_assignment_records ?? 0} eligible assignment records matched (${coverage.unmapped_assignment_records ?? 0} unmatched)` : 'Incomplete'}</dd></div>
          </dl>
          <p className="ui-description">Potential transaction-derived conflicts, not effective authorization. Review decisions never change what is detected. Criticality labels keep their source values. Risk definitions are maintained in Settings.</p>
          <Toolbar><Button onClick={() => change({ settings: true, settingsTarget: 'sod' })}>Configure risks in Settings</Button></Toolbar>
        </Card>
      </div>
    </section>
  )
}
