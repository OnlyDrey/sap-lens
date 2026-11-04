import { ShieldCheck } from 'lucide-react'
import { useHistoryValue, useViewHistory, sodHref } from '@/hooks/useViewHistory'
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
import { ContextBar } from './SodShared'
import { SOD_VIEWS } from '@/lib/navigationItems'
import { SodGroupHeatmap } from './SodGroupHeatmap'


export function SodWorkspace() {
  const configuration = useQuery({ queryKey: ['configuration'], queryFn: fetchConfiguration }),
    { change: navigate } = useViewHistory()
  if (configuration.data?.settings.features?.sod === false) return (
    <section className="sod-workspace grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={22} aria-hidden="true" />} />
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
    view = selected || 'overview'
  return (
    <section className="sod-workspace grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={22} aria-hidden="true" />} />
      <SecondaryNavigation label="SoD views" items={SOD_VIEWS.map(({ value, label, icon }) => ({ value, label, icon, href: sodHref(value), active: view === value, onSelect: () => change({ sodView: value }) }))} />
      <ContextBar />
      <SodGroupHeatmap />
      {view === 'overview' ? <SodOverview /> : view === 'risk-matrix' ? <RiskMatrix /> : view === 'activity-matrix' ? <ActivityMatrix /> : view === 'explorer' ? <SodExplorer />
        : view === 'reviews' ? <SodReviews /> : view === 'periods' ? <SodPeriods /> : <SodReports />}
    </section>
  )
}
