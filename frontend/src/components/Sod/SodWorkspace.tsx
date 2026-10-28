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
import { SodInvestigation } from './SodInvestigation'
import { useSodContext, useSodSubject } from './SodShared'

const VIEWS: [SodView, string][] = [['overview', 'Overview'], ['risk-matrix', 'Risk Matrix'], ['activity-matrix', 'Activity Matrix'], ['explorer', 'Access Explorer'], ['reviews', 'Reviews'], ['periods', 'Review Periods'], ['reports', 'Reports']]

export function SodWorkspace() {
  const [selected] = useHistoryValue('sodView'),
    { change } = useViewHistory(),
    view = selected || 'overview',
    [subject, setSubject] = useSodSubject(),
    [context] = useSodContext(),
    [detailRole] = useHistoryValue('detailRole')
  return (
    <section className="sod-workspace grid min-w-0 gap-3" aria-label="SoD investigation">
      <PageHeader title="Segregation of Duties" icon={<ShieldCheck size={24} aria-hidden="true" />} />
      <SecondaryNavigation label="SoD views" items={VIEWS.map(([value, label]) => ({ value, label, href: sodHref(value), active: view === value, onSelect: () => change({ sodView: value }) }))} />
      {view === 'overview' ? <SodOverview /> : view === 'risk-matrix' ? <RiskMatrix /> : view === 'activity-matrix' ? <ActivityMatrix /> : view === 'explorer' ? <SodExplorer />
        : view === 'reviews' ? <SodReviews /> : view === 'periods' ? <SodPeriods /> : <SodReports />}
      {/* One side panel at a time: it yields to the role detail panel and returns on Back. */}
      {subject && !detailRole && <SodInvestigation context={context} user={subject.user} risk={subject.risk} activity={subject.activity} onClose={() => setSubject(null)} />}
    </section>
  )
}
