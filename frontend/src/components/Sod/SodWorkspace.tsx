import { ShieldCheck } from 'lucide-react'
import { useHistoryValue, useViewHistory, sodHref, type SodView } from '@/hooks/useViewHistory'
import { SecondaryNavigation } from '@/components/Shared/Navigation'
import { PageHeader } from '@/components/Shared/Presentation'
import { SodOverview } from './SodOverview'
import { ActivityMatrix, RiskMatrix } from './SodMatrices'
import { SodExplorer } from './SodExplorer'
import { SodReviews } from './SodReviews'
import { SodPeriods } from './SodPeriods'
import { SodReports } from './SodReports'

const VIEWS: [SodView, string][] = [['overview', 'Overview'], ['risk-matrix', 'Risk Matrix'], ['activity-matrix', 'Activity Matrix'], ['explorer', 'Access Explorer'], ['reviews', 'Reviews'], ['periods', 'Review Periods'], ['reports', 'Reports']]

export function SodWorkspace() {
  const [selected] = useHistoryValue('sodView'),
    { change } = useViewHistory(),
    view = selected || 'overview'
  return (
    <section className="grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={24} aria-hidden="true" />} />
      <SecondaryNavigation label="SoD views" items={VIEWS.map(([value, label]) => ({ value, label, href: sodHref(value), active: view === value, onSelect: () => change({ sodView: value }) }))} />
      {view === 'overview' ? <SodOverview /> : view === 'risk-matrix' ? <RiskMatrix /> : view === 'activity-matrix' ? <ActivityMatrix /> : view === 'explorer' ? <SodExplorer />
        : view === 'reviews' ? <SodReviews /> : view === 'periods' ? <SodPeriods /> : <SodReports />}
    </section>
  )
}
