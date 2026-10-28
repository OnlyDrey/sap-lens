import type { ReactNode } from 'react'
import { Activity, CalendarRange, ClipboardCheck, FileText, Grid3x3, LayoutDashboard, Search, ShieldCheck } from 'lucide-react'
import { useHistoryValue, useViewHistory, sodHref, type SodView } from '@/hooks/useViewHistory'
import { SecondaryNavigation } from '@/components/Shared/Navigation'
import { Card, PageHeader, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { Button } from '@/components/Shared/Button'
import { useQuery } from '@tanstack/react-query'
import { fetchConfiguration } from '@/api/configuration'
import { SodOverview } from './SodOverview'
import { ActivityMatrix, RiskMatrix } from './SodMatrices'
import { SodExplorer } from './SodExplorer'
import { SodReviews } from './SodReviews'
import { SodPeriods } from './SodPeriods'
import { SodReports } from './SodReports'
import { SodInvestigation } from './SodInvestigation'
import { useSodContext, useSodSubject } from './SodShared'

const VIEWS: [SodView, string, ReactNode][] = [
  ['overview', 'Overview', <LayoutDashboard size={16} aria-hidden="true" />], ['risk-matrix', 'Risk Matrix', <Grid3x3 size={16} aria-hidden="true" />],
  ['activity-matrix', 'Activity Matrix', <Activity size={16} aria-hidden="true" />], ['explorer', 'Access Explorer', <Search size={16} aria-hidden="true" />],
  ['reviews', 'Reviews', <ClipboardCheck size={16} aria-hidden="true" />], ['periods', 'Review Periods', <CalendarRange size={16} aria-hidden="true" />], ['reports', 'Reports', <FileText size={16} aria-hidden="true" />],
]

export function SodWorkspace() {
  const configuration = useQuery({ queryKey: ['configuration'], queryFn: fetchConfiguration }),
    { change: navigate } = useViewHistory()
  if (configuration.data?.settings.features?.sod === false) return (
    <section className="sod-workspace grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={24} aria-hidden="true" />} />
      <Card aria-label="SoD is turned off">
        <StatusBadge tone="neutral">Turned off</StatusBadge>
        <p>SoD analysis is disabled in Features. Imported matrices, risk configuration, review history and periods are kept and return when it is enabled.</p>
        <Toolbar><Button variant="primary" onClick={() => navigate({ settings: true, settingsTarget: 'features' })}>Open Features</Button></Toolbar>
      </Card>
    </section>
  )
  return <SodWorkspaceContent />
}

function SodWorkspaceContent() {
  const [selected] = useHistoryValue('sodView'),
    { change } = useViewHistory(),
    view = selected || 'overview',
    [subject, setSubject] = useSodSubject(),
    [context] = useSodContext(),
    [detailRole] = useHistoryValue('detailRole')
  return (
    <section className="sod-workspace grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={24} aria-hidden="true" />} />
      <SecondaryNavigation label="SoD views" items={VIEWS.map(([value, label, icon]) => ({ value, label, icon, href: sodHref(value), active: view === value, onSelect: () => change({ sodView: value }) }))} />
      {view === 'overview' ? <SodOverview /> : view === 'risk-matrix' ? <RiskMatrix /> : view === 'activity-matrix' ? <ActivityMatrix /> : view === 'explorer' ? <SodExplorer />
        : view === 'reviews' ? <SodReviews /> : view === 'periods' ? <SodPeriods /> : <SodReports />}
      {/* One side panel at a time: it yields to the role detail panel and returns on Back. */}
      {subject && !detailRole && <SodInvestigation context={context} user={subject.user} risk={subject.risk} activity={subject.activity} onClose={() => setSubject(null)} />}
    </section>
  )
}
