import { useState } from 'react'
import { Database, FileDown, ShieldCheck, UsersRound } from 'lucide-react'
import { Button, ButtonGroup } from '@/components/Shared/Button'
import { Card, StatusBadge } from '@/components/Shared/Presentation'
import { Kpi } from '@/components/Shared/Kpi'
import { InfoList, InfoRow } from '@/components/Shared/InfoList'
import { InfoTip } from '@/components/Shared/InfoTip'
import { BarChart, StackedBar } from '@/components/Shared/Charts'
import { DisclosureChevron } from '@/components/Shared/DisclosureChevron'
import { MultiSelectFilter } from '@/components/Shared/MultiSelectFilter'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { SortControl } from '@/components/Shared/FilterLayout'
import { Dialog } from '@/components/Shared/Dialog'
import { matchHealthTone, MATCH_HEALTH_LEGEND } from '@/lib/health'

const LONG_ROLE = 'ZC:SYN:A_VERY_LONG_ROLE_IDENTIFIER_FOR_LAYOUT_STRESS_TESTING:ABCDEFGHIJKLMNOP'
const VALIDATION: [string, 'success' | 'warning' | 'error', string][] = [['Confirmed', 'success', 'In the imported catalogue'], ['Unconfirmed', 'warning', 'Valid name, not in the catalogue'], ['Invalid', 'error', 'Not a valid SAP role name'], ['Needs suffix', 'warning', 'Suffix required']]

/** Summaries, charts, tables, modals and disclosure patterns used by the Dashboard, the Access Package and the SoD pages, with synthetic values only. */
export function ComponentLibraryPatterns() {
  const [selected, setSelected] = useState<string[]>(['FIN']), [row, setRow] = useState('SYN_B'), [open, setOpen] = useState(false), [card, setCard] = useState(false)
  const [kind, setKind] = useState('risk'), [sort, setSort] = useState('users'), [descending, setDescending] = useState(true), [modal, setModal] = useState(false), [heatOpen, setHeatOpen] = useState(true)
  const percent = (251 / 264) * 100
  return (
    <Card aria-label="Summaries and data presentation">
      <h2>Summaries &amp; data presentation</h2>
      <p className="ui-description">Which component shows what: a KPI for a prominent figure, an information list for secondary facts, a chart for a real distribution, a table for comparable records, a badge for status and a codeblock for an exact identifier.</p>
      <div className="demo-grid">
        <section aria-label="Compact KPI" className="grid gap-2">
          <h3>Compact KPI</h3>
          <div className="flex flex-wrap gap-2"><Kpi label="SAP users" value="264" icon={<UsersRound size={16} aria-hidden="true" />} /><Kpi label="Pending reviews" value="12" tone="warning" onClick={() => undefined} navigates /></div>
        </section>
        <section aria-label="Information list" className="grid gap-2">
          <h3>Information list</h3>
          <InfoList label="Demo information list">
            <InfoRow primary icon={<UsersRound size={18} aria-hidden="true" />} label="SAP users" value="264" onClick={() => undefined} navigates />
            <InfoRow icon={<Database size={16} aria-hidden="true" />} label="Catalogue roles" value="96" onClick={() => undefined} navigates />
            <InfoRow icon={<ShieldCheck size={16} aria-hidden="true" />} label="Release roles" value="41" />
          </InfoList>
        </section>
        <section aria-label="Chart presentation" className="grid gap-2">
          <h3>Charts <InfoTip label="About chart presentation"><p>Charts are drawn from real counts with semantic colors; tooltips carry the exact share and rows open the filtered list.</p></InfoTip></h3>
          <BarChart label="Demo distribution" data={[{ key: 'a', label: '0–5 roles', value: 40, note: '15%', title: '40 users (15.2%)' }, { key: 'b', label: '6–10 roles', value: 70, note: '27%', title: '70 users (26.5%)' }, { key: 'c', label: '11–20 roles', value: 90, note: '34%', title: '90 users (34.1%)' }]} />
          <StackedBar label="Demo review progress" total={264} segments={[{ key: 'c', label: 'Completed', value: 40, tone: 'success' }, { key: 'p', label: 'Not yet reviewed', value: 212, tone: 'neutral' }, { key: 'o', label: 'Outdated', value: 12, tone: 'warning' }]} />
        </section>
        <section aria-label="Match health progress" className="grid gap-2">
          <h3>Health thresholds</h3>
          <div className="progress-summary"><strong className="progress-summary-value">{percent.toFixed(1)}%</strong><span className="progress-summary-caption">251 / 264 matched</span>
            <progress className="progress-summary-bar" data-tone={matchHealthTone(percent)} max={264} value={251} aria-label="Demo match coverage" /></div>
          <p className="ui-description">{MATCH_HEALTH_LEGEND}</p>
        </section>
        <section aria-label="Table states" className="grid gap-2">
          <h3>Table zebra, hover and selection</h3>
          <div className="access-table" role="region" aria-label="Demo table states" tabIndex={0} data-density="compact">
            <table>
              <thead><tr><th>SAP user</th><th>Group</th></tr></thead>
              <tbody>{['SYN_A', 'SYN_B', 'SYN_C'].map((user) => <tr key={user} data-selected={row === user || undefined} onClick={() => setRow(user)}><td>{user}</td><td>FIN</td></tr>)}</tbody>
            </table>
          </div>
        </section>
        <section aria-label="Codeblock" className="grid gap-2">
          <h3>Codeblock</h3>
          <p className="ui-description">One line, scrolls horizontally inside its box, copies the full value.</p>
          <RoleIdentifier value={LONG_ROLE} label="role" />
        </section>
        <section aria-label="Validation status" className="grid gap-2">
          <h3>Status and validation badges</h3>
          <ul className="grid gap-1" aria-label="Validation states">{VALIDATION.map(([text, tone, hint]) => <li key={text} className="flex flex-wrap items-center gap-2"><StatusBadge tone={tone}>{text}</StatusBadge><span className="ui-description">{hint}</span></li>)}</ul>
        </section>
        <section aria-label="Disclosure and expandable cards" className="grid gap-2">
          <h3>Disclosure controls</h3>
          <div className="flex flex-wrap gap-2"><Button aria-expanded={open} onClick={() => setOpen(!open)}><DisclosureChevron open={open} />Technical details</Button><Button onClick={() => setCard(!card)} aria-expanded={card}><DisclosureChevron open={card} />Expandable card</Button></div>
          {open && <p className="ui-description">Right chevron when collapsed, down when expanded; one standard everywhere.</p>}
          {card && <div className="settings-card"><p>Cards expand independently: only their own column moves.</p></div>}
        </section>
        <section aria-label="Multiselect toolbar" className="grid gap-2">
          <h3>Multiselect toolbar</h3>
          <MultiSelectFilter label="Demo SAP User Group" values={selected} options={['FIN', 'P2P', 'HR', 'MM']} onChange={setSelected} placeholder="All groups · type to search" />
        </section>
        <section aria-label="Heatmap controls" className="grid gap-2">
          <h3>Heatmap controls</h3>
          <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Demo heatmap controls">
            <Button aria-expanded={heatOpen} onClick={() => setHeatOpen(!heatOpen)}><DisclosureChevron open={heatOpen} />Conflicts by SAP User Group</Button>
            <ButtonGroup label="Demo heatmap columns" value={kind} onChange={setKind} options={[{ value: 'risk', label: 'Risks' }, { value: 'activity', label: 'Activities' }]} />
            <SortControl label="Demo sort groups" value={sort} options={[{ value: 'name', label: 'SAP User Group' }, { value: 'users', label: 'Distinct users' }]} descending={descending} onChange={setSort} onDescending={setDescending} />
          </div>
        </section>
        <section aria-label="Modal layout" className="grid gap-2">
          <h3>Wide modal</h3>
          <div className="flex flex-wrap gap-2"><Button onClick={() => setModal(true)}>Open wide modal</Button><Button><FileDown size={16} aria-hidden="true" />Export CSV</Button></div>
          {modal && <Dialog title="Demo evidence modal" onClose={() => setModal(false)} footer={<Button onClick={() => setModal(false)}>Close</Button>}>
            <dl className="evidence-summary"><div><dt>SAP user</dt><dd>SYN_A</dd></div><div><dt>Risk</dt><dd>R1</dd></div><div><dt>Roles</dt><dd>3</dd></div></dl>
            <div className="evidence-scroll" tabIndex={0} role="region" aria-label="Demo scrollable evidence"><table><thead><tr><th>Role</th></tr></thead><tbody><tr><td><RoleIdentifier value="ROLE_A1" label="role" /></td></tr><tr><td><RoleIdentifier value="ROLE_B" label="role" /></td></tr></tbody></table></div>
          </Dialog>}
        </section>
      </div>
    </Card>
  )
}
