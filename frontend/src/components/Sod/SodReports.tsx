import { useState } from 'react'
import { announceExport } from '@/lib/exportNotice'
import { useQuery } from '@tanstack/react-query'
import { downloadFile, REPORT_NAME, sod, sodPost } from '@/api/sod'
import { Button } from '@/components/Shared/Button'
import { Card, DataTable, StatusBadge, Toolbar, EvidenceDisclosure } from '@/components/Shared/Presentation'
import { FormField, Input, Checkbox } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { ContentTabs } from '@/components/Shared/Navigation'
import { NorwegianDateInput, parseNorwegianDate } from '@/components/Shared/NorwegianDateInput'

const sectionNames: Record<string, string> = { executive: 'Executive Summary', methodology: 'Scope and Evaluation Period', risk_overview: 'Overall Findings and Risk Exposure',
  activity_results: 'Review Progress: Activity Decisions', assignment_results: 'Review Progress: Role Assignment Decisions', risk_acceptance: 'Review Progress: Risk Acceptance Decisions',
  controls: 'Compensating Controls and Conditions', outstanding: 'Outstanding Risks and Actions', remediation: 'Remediation Responsibilities and Status', sources: 'Evidence Freshness and Limitations',
  changes: 'Changes Since Previous Review', conclusion: 'Conclusion and Approval', appendices: 'Technical Appendices' }
/** What each status does and does not establish; names are typed locally and never authenticated. */
const STATUS_HELP: Record<string, string> = {
  Draft: 'Not reviewed or approved.',
  Reviewed: 'A reviewer is named by the preparer. The name is not authenticated, so this is not an approval.',
  Approved: 'The review period has a recorded approval and is frozen. Names remain locally entered and are not authenticated.',
  'Externally signed': 'The preparer states the document was signed outside SAP Lens. SAP Lens cannot verify the signature.',
}
const groups = ['Remove assignment', 'Investigate assignment', 'Apply compensating control', 'Maintain access', 'No action required', 'Awaiting review']
const FROZEN = ['Approved', 'Closed', 'Approved / closed']
type Preview = { model_checksum: string; snapshot_checksum: string; status: string; status_statement?: string; sections: { key: string; title: string; paragraphs: string[]; tables: string[][][] }[]; limitation: string; row_count?: number }
type PeriodItem = { id: string; name: string; state: string }
const todayText = () => new Date().toLocaleDateString('nb-NO', { day: '2-digit', month: '2-digit', year: 'numeric' })

export function SodReports() {
  const periods = useQuery({ queryKey: ['sod-periods', false], queryFn: () => sod<{ items: PeriodItem[] }>('/api/sod/periods') })
  const items = periods.data?.items || []
  return (
    <section className="grid min-w-0 gap-3" aria-label="SoD reports">
      <h2>SoD Reports</h2>
      <EvidenceDisclosure title="Reports, approval and external signing">DOCX remains editable; PDF is a stable distribution format suitable for external signing. Reports are written in English for management readers, with transaction-level evidence in the technical appendices. Report generation does not approve a review. Draft, Reviewed, Approved and Externally signed describe the document only: names and signature lines are typed locally and are not verified digital signatures. Approved periods stay frozen; choose an approved previous period for reproducible change analysis.</EvidenceDisclosure>
      <ReportTabs items={items} />
    </section>
  )
}

function ReportTabs({ items }: { items: PeriodItem[] }) {
  const [tab, setTab] = useState('formal')
  return (
    <ContentTabs label="SoD report types" value={tab} onChange={setTab} items={[{ value: 'formal', label: 'Formal review report' }, { value: 'remediation', label: 'Access remediation report' }]}>
      {tab === 'formal' ? <FormalReport items={items} /> : <RemediationReport items={items} />}
    </ContentTabs>
  )
}

function useExport() {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('')
  const run = async (path: string, body: unknown, kind: 'csv' | 'document', label: string) => {
    setBusy(true)
    try {
      const name = await downloadFile(path, { method: 'POST', body, namePattern: kind === 'csv' ? /^sap-lens-sod-access-remediation-\d{4}-\d{2}-\d{2}\.csv$/ : REPORT_NAME, kind })
      announceExport(name ? { kind: 'success', message: `${label} exported as ${name}.` } : { kind: 'info', message: 'Export cancelled.' })
    } catch (error) {
      announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Report export failed.' })
    } finally {
      setBusy(false)
    }
  }
  return { busy, setBusy, message, setMessage, run }
}

function FormalReport({ items }: { items: PeriodItem[] }) {
  const [period, setPeriod] = useState(''), [title, setTitle] = useState('SoD Access Review'), [status, setStatus] = useState('Draft'),
    [prepared, setPrepared] = useState(''), [reviewer, setReviewer] = useState(''), [approver, setApprover] = useState(''), [reviewerRole, setReviewerRole] = useState(''), [approverRole, setApproverRole] = useState(''),
    [version, setVersion] = useState('1.0'), [comments, setComments] = useState(''), [previous, setPrevious] = useState(''), [date, setDate] = useState(todayText), [sections, setSections] = useState(Object.keys(sectionNames)),
    [appendices, setAppendices] = useState(true), [preview, setPreview] = useState<Preview | null>(null), [previewKey, setPreviewKey] = useState('')
  const exporter = useExport()
  const selected = items.find((item) => item.id === period)
  const frozen = !!selected && FROZEN.includes(selected.state)
  const options = { title, status, prepared_by: prepared, reviewer, approver, reviewer_role: reviewerRole, approver_role: approverRole, document_version: version, management_comments: comments,
    previous_period_id: previous || null, report_date: parseNorwegianDate(date), sections, include_appendices: appendices }
  const key = JSON.stringify({ period_id: period, options }), active = previewKey === key ? preview : null
  const showPreview = async () => {
    exporter.setBusy(true)
    exporter.setMessage('')
    try {
      if (!options.report_date) throw Error('Use DD.MM.YYYY for report date.')
      setPreview(await sodPost<Preview>('/api/sod/reports/preview', { period_id: period, options }))
      setPreviewKey(key)
    } catch (error) {
      exporter.setMessage(error instanceof Error ? error.message : 'Report preview failed.')
    } finally {
      exporter.setBusy(false)
    }
  }
  return (
    <div className="grid min-w-0 gap-3">
      <Card>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <FormField label="Report period"><Select value={period} onChange={(event) => { setPeriod(event.target.value); setStatus('Draft') }}><option value="">Choose period</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.state}</option>)}</Select></FormField>
          <FormField label="Report title"><Input value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} /></FormField>
          <FormField label="Report status"><Select value={status} onChange={(event) => setStatus(event.target.value)}><option>Draft</option><option>Reviewed</option>{frozen && <option>Approved</option>}{frozen && <option>Externally signed</option>}</Select><p className="ui-description">{STATUS_HELP[status]}</p></FormField>
        </div>
        <details className="sod-report-details"><summary>Document details</summary>
        <div className="grid min-w-0 gap-3 py-3 sm:grid-cols-2 xl:grid-cols-4">
          {([['Prepared by', prepared, setPrepared], ['Report reviewer', reviewer, setReviewer], ['Reviewer role', reviewerRole, setReviewerRole], ['Report approver', approver, setApprover], ['Approver role', approverRole, setApproverRole], ['Document version', version, setVersion]] as [string, string, (value: string) => void][]).map(([label, value, set]) => (
            <FormField key={label} label={label}><Input value={value} maxLength={label === 'Document version' ? 80 : 120} onChange={(event) => set(event.target.value)} /></FormField>))}
          <NorwegianDateInput label="Report date" value={date} onChange={setDate} />
          <FormField label="Previous approved period"><Select value={previous} onChange={(event) => setPrevious(event.target.value)}><option value="">No comparison</option>{items.filter((item) => FROZEN.includes(item.state) && item.id !== period).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></FormField>
        </div>
        <FormField label="Management comments"><textarea className="ui-control min-h-24" value={comments} maxLength={12000} onChange={(event) => setComments(event.target.value)} /></FormField>
        </details>
        <details><summary>Included report sections</summary><div className="grid gap-2 py-3 sm:grid-cols-2">{Object.entries(sectionNames).map(([value, label]) => <Checkbox key={value} checked={sections.includes(value)} onChange={(event) => setSections((previousList) => (event.target.checked ? [...previousList, value] : previousList.filter((name) => name !== value)))}>{label}</Checkbox>)}</div></details>
        <Checkbox checked={appendices} onChange={(event) => setAppendices(event.target.checked)}>Include detailed appendices</Checkbox>
        <Toolbar>
          <Button loading={exporter.busy} disabled={!period} onClick={() => void showPreview()}>Preview report</Button>
          {(['docx', 'pdf'] as const).map((kind) => <Button key={kind} disabled={exporter.busy || !active} onClick={() => void exporter.run(`/api/sod/reports/${kind}`, { period_id: period, options, expected_model: active!.model_checksum }, 'document', kind.toUpperCase())}>Export {kind.toUpperCase()}</Button>)}
        </Toolbar>
      </Card>
      {exporter.message && <p role="status" className="break-all">{exporter.message}</p>}
      {active && <Card aria-label="Structured report preview">
        <Toolbar><h3>{title}</h3><StatusBadge>{active.status}</StatusBadge></Toolbar>
        {active.status_statement && <p>{active.status_statement}</p>}
        <p>{active.limitation}</p>
        <p className="break-all text-xs">Snapshot reference {active.snapshot_checksum.slice(0, 12)} · Report model reference {active.model_checksum.slice(0, 12)} (full values in the technical appendix and document integrity block)</p>
        {active.sections.map((section) => <details key={section.key}><summary>{section.title} · {section.tables.reduce((sum, table) => sum + Math.max(0, table.length - 1), 0)} table rows</summary>{section.paragraphs.map((text, index) => <p key={index} className="my-2 whitespace-pre-wrap">{text}</p>)}</details>)}
      </Card>}
    </div>
  )
}

function RemediationReport({ items }: { items: PeriodItem[] }) {
  const [context, setContext] = useState('current'), [prepared, setPrepared] = useState(''), [version, setVersion] = useState('1.0'), [date, setDate] = useState(todayText),
    [title, setTitle] = useState('Access Remediation Report'), [recommended, setRecommended] = useState(groups), [preview, setPreview] = useState<Preview | null>(null), [previewKey, setPreviewKey] = useState('')
  const exporter = useExport()
  const options = { title, prepared_by: prepared, document_version: version, report_date: parseNorwegianDate(date), recommended }
  const key = JSON.stringify({ context, options }), active = previewKey === key ? preview : null
  const showPreview = async () => {
    exporter.setBusy(true)
    exporter.setMessage('')
    try {
      if (!options.report_date) throw Error('Use DD.MM.YYYY for report date.')
      setPreview(await sodPost<Preview>('/api/sod/reports/remediation/preview', { context, options }))
      setPreviewKey(key)
    } catch (error) {
      exporter.setMessage(error instanceof Error ? error.message : 'Report preview failed.')
    } finally {
      exporter.setBusy(false)
    }
  }
  return (
    <div className="grid min-w-0 gap-3">
      <p className="ui-description">An operational list of what should happen to each access, separate from the formal approval document. A proposed removal is not completed remediation, and verification reflects later source evidence only.</p>
      <Card>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <FormField label="Evidence context"><Select value={context} onChange={(event) => setContext(event.target.value)}><option value="current">Current evidence</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.state}</option>)}</Select></FormField>
        </div>
        <fieldset><legend>Included handling</legend><div className="grid gap-2 py-2 sm:grid-cols-2 xl:grid-cols-3">{groups.map((group) => <Checkbox key={group} checked={recommended.includes(group)} onChange={(event) => setRecommended((previousList) => (event.target.checked ? [...previousList, group] : previousList.filter((name) => name !== group)))}>{group}</Checkbox>)}</div></fieldset>
        <details className="sod-report-details"><summary>Document details</summary>
        <div className="grid min-w-0 gap-3 py-3 sm:grid-cols-2 xl:grid-cols-4">
          <FormField label="Report title"><Input value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} /></FormField>
          <FormField label="Prepared by"><Input value={prepared} maxLength={120} onChange={(event) => setPrepared(event.target.value)} /></FormField>
          <FormField label="Document version"><Input value={version} maxLength={80} onChange={(event) => setVersion(event.target.value)} /></FormField>
          <NorwegianDateInput label="Report date" value={date} onChange={setDate} />
        </div>
        </details>
        <Toolbar>
          <Button loading={exporter.busy} disabled={!recommended.length} onClick={() => void showPreview()}>Preview report</Button>
          <Button disabled={exporter.busy || !active} onClick={() => void exporter.run('/api/sod/reports/remediation/csv', { context, options, expected_model: active!.model_checksum }, 'csv', 'CSV')}>Export CSV</Button>
          {(['docx', 'pdf'] as const).map((kind) => <Button key={kind} disabled={exporter.busy || !active} onClick={() => void exporter.run(`/api/sod/reports/remediation/${kind}`, { context, options, expected_model: active!.model_checksum }, 'document', kind.toUpperCase())}>Export {kind.toUpperCase()}</Button>)}
        </Toolbar>
      </Card>
      {exporter.message && <p role="status" className="break-all">{exporter.message}</p>}
      {active && <Card aria-label="Remediation report preview">
        <h3>{title}</h3><p>{active.row_count} rows across the selected handling groups.</p>
        {active.sections[0] && <DataTable caption="Remediation summary"><thead><tr>{active.sections[0].tables[0][0].map((cell) => <th key={cell}>{cell}</th>)}</tr></thead><tbody>{active.sections[0].tables[0].slice(1).map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></DataTable>}
      </Card>}
    </div>
  )
}
