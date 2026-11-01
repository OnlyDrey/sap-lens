import { Dialog } from '@/components/Shared/Dialog'
import { userHref } from '@/hooks/useViewHistory'
import { type ReviewEvidence } from '@/components/Shared/ReviewFindings'
import { PageHeader, MetadataList } from '@/components/Shared/Presentation'
import { ClipboardCheck as PageIcon } from 'lucide-react'
import { Kpi } from '@/components/Shared/Kpi'
import { kpiTone } from '@/lib/kpiTone'
import { InfoTip } from '@/components/Shared/InfoTip'
import { StackedBar } from '@/components/Shared/Charts'
import { FilterLayout, FilterSection, PageToolbar, SortControl } from '@/components/Shared/FilterLayout'
import { FormField } from '@/components/Shared/Controls'
import { SearchInput } from '@/components/Shared/Controls'
import { Button } from '@/components/Shared/Button'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { useApplicationData } from '@/state/ApplicationData'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, ArrowUpRight, ClipboardCheck, ClipboardList, Download, History, Save, SearchX, UserMinus } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import { useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { FilterChip } from '@/components/Shared/FilterChip'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { Select } from '@/components/Shared/Select'
import { MultiSelectFilter } from '@/components/Shared/MultiSelectFilter'
import { csvField } from '@/lib/accessExport'
import { formatTimestamp } from '@/lib/dateFormat'
import { Filter, Pagination, QueryState, inputClass } from './Shared'
interface Decision {
  state: string
  reviewer: string
  rationale: string
  timestamp: string
  evidence_version: string
}
interface PositionChange {
  id: string
  open: boolean
  fields: ('department' | 'title')[]
  previous_department: string
  current_department: string
  previous_title: string
  current_title: string
  detected_at: string
  source_generation: string
  previous_imported_at?: string | null
  current_imported_at?: string | null
}
interface Row {
  username: string
  name: string
  groups: string[]
  sap_validity: string
  lock_status: string
  ad_status: string
  match_status: string
  findings: string[]
  unlicensed: boolean
  evidence_version: string
  decision: Decision | null
  stale: boolean
  review_state: string
  needs_review: boolean
  priority: 'High' | 'Normal' | 'None'
  position_change: PositionChange | null
  evidence?:ReviewEvidence
  history_count?:number
}
interface Results {
  items: Row[]
  total: number
  loaded: boolean
  directory_available: boolean
  data_revision: string
  summary: Record<string, number | null>
  finding_labels: Record<string, string>
  review_states: string[]
}
const SORTS = [{ value: 'username', label: 'Username' }, { value: 'name', label: 'Name' }, { value: 'sap_validity', label: 'SAP validity' }, { value: 'lock_status', label: 'SAP lock status' }, { value: 'ad_status', label: 'AD status' }, { value: 'review_state', label: 'Review state' }, { value: 'priority', label: 'Priority' }]
const matchLabel = (status: string) => ({matched:'Matched',duplicate_email:'Duplicate Email',missing_email:'Missing Email',ambiguous:'Ambiguous Match',unmatched:'Unmatched',disabled:'Disabled',unavailable:'Unavailable'} as Record<string,string>)[status] || status.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
const changeText = (change: PositionChange) => [
  change.fields.includes('department') && `Department ${change.previous_department} → ${change.current_department}`,
  change.fields.includes('title') && `Job title ${change.previous_title} → ${change.current_title}`,
].filter(Boolean).join(' · ')

/** Review attention: each KPI applies its finding to the list. Review progress (completed and pending) is the separate panel beside it. */
const ATTENTION_TILES: [string, string, ReactNode, { finding: string }][] = [
  ['requiring_review', 'Accounts requiring review', <ClipboardList size={16} />, { finding: 'any' }],
  ['missing', 'Missing or ambiguous directory matches', <SearchX size={16} />, { finding: 'directory_match' }],
  ['position_changes', 'Position changes', <ArrowRightLeft size={16} />, { finding: 'position_change' }],
  ['outdated', 'Outdated reviews', <History size={16} />, { finding: 'stale' }],
]
/** The fifth attention KPI; like the others it occupies one grid cell, so the last cell on the right stays empty. */
const FINAL_TILE: [string, string, ReactNode, { finding: string }] = ['mismatch', 'AD disabled / SAP valid and unlocked', <UserMinus size={16} />, { finding: 'ad_disabled_open' }]
const FINDING_NAMES: Record<string, string> = { any: 'Accounts requiring review', matched: 'Reliably matched identities', directory_missing: 'Missing directory matches', directory_ambiguous: 'Ambiguous directory matches', reviewed: 'Completed reviews', pending: 'Pending reviews', position_change: 'Position changes', stale: 'Outdated reviews' }

/** Department and job title together, labelled so the two are never confused. Changed values are emphasized; unchanged ones are muted. */
function PositionCell({ department, title, changed }: { department?: string | null; title?: string | null; changed?: string[] }) {
  const line = (label: string, value: string | null | undefined, field: string) => (
    <p className="position-line" data-changed={changed?.includes(field) || undefined}><span className="position-label">{label}</span><span className="position-value" title={value || undefined}>{value || '—'}</span></p>
  )
  return <div className="position-cell">{line('Department', department, 'department')}{line('Job title', title, 'title')}</div>
}

export function AccountReview({ onUser }: { onUser: (name: string) => void }) {
  const { loading: dataLoading } = useApplicationData()
  const [retainedFindings, setFindings] = useHistoryValue('reviewFindings')
  const findings = retainedFindings ?? []
  const {view,change}=useViewHistory()
  const retained=view.accountReviewFilters
  const [search, setSearch] = useState(retained?.search||''),
    [licenses, setLicenses] = useState<string[]>(retained?.licenses||[]),
    [states, setStates] = useState<string[]>(retained?.states||[]),
    [sort, setSort] = useState(retained?.sort||'username'),
    [descending, setDescending] = useState(retained?.descending||false),
    [offset, setOffset] = useState(0)
  useEffect(()=>change({accountReviewFilters:{search,licenses,states,sort,descending}},true),[search,licenses,states,sort,descending,change])
  const [term, setTerm] = useState(''),
    [feedback, setFeedback] = useState(''),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState<Row | null>(null),
    [actionError, setActionError] = useState(false)
  const returnUser = useRef(''),
    wasEditing = useRef(false)
  useEffect(() => {
    if (editing) {
      wasEditing.current = true

    }
  }, [editing])
  const [reviewer, setReviewer] = useState(''),
    [rationale, setRationale] = useState(''),
    [decision, setDecision] = useState('Needs review')
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search), 250)
    return () => clearTimeout(timer)
  }, [search])
  useEffect(
    () => setOffset(0),
    [term, findings.join('|'), licenses.join('|'), states.join('|'), sort, descending],
  )
  const params = new URLSearchParams({
    search: term,
    sort,
    descending: String(descending),
  })
  findings.forEach(value => params.append('findings', value))
  licenses.forEach(value => params.append('license_groups', value))
  states.forEach(value => params.append('review_states', value))
  const generation = useRef(0)
  useEffect(() => {
    generation.current++
    return () => {
      generation.current++
    }
  }, [params.toString()])
  const qc = useQueryClient()
  const result = useQuery({
    queryKey: ['account-review', params.toString(), offset],
    queryFn: () =>
      apiRequest<Results>(
        `/api/account-review?${params}&offset=${offset}&limit=25`,
      ),
  })
  const data = result.data
  const [historyOffset,setHistoryOffset]=useState(0)
  useEffect(()=>setHistoryOffset(0),[editing?.username])
  const history=useQuery({queryKey:['review-history',editing?.username,historyOffset],queryFn:()=>apiRequest<{items:Decision[];total:number}>(`/api/account-review/history/${encodeURIComponent(editing!.username)}?offset=${historyOffset}`),enabled:!!editing})
  const startReview = (row: Row) => {
    returnUser.current = row.username
    setEditing(row)
    setReviewer(row.decision?.reviewer || '')
    setRationale(row.decision?.rationale || '')
    setDecision(row.review_state)
  }
  /** Tiles toggle: a finding joins the finding filter (OR), the classification tile joins the classification filter (AND with findings). The first tile clears both. */
  const toggleTile = (target: { finding: string; license?: string }) => {
    if (target.license) setLicenses(list => list.includes(target.license!) ? list.filter(item => item !== target.license) : [...list, target.license!])
    else if (target.finding) setFindings(list => (list ?? []).includes(target.finding) ? (list ?? []).filter(item => item !== target.finding) : [...(list ?? []), target.finding])
    else { setFindings([]); setLicenses([]) }
  }
  /** Review progress (about one third) beside review attention (about two thirds); no account is counted twice in the progress. */
  const renderOverview = () => {
    if (!data) return null
    const { total, reviewed, pending } = data.summary
    const known = total != null && reviewed != null && pending != null
    const percent = known && total ? (reviewed! / total) * 100 : 0
    const activeFinding = (name: string) => findings.includes(name)
    const tile = ([key, label, icon, target]: [string, string, ReactNode, { finding: string }], extra = '') => {
      const value = data.summary[key]
      return <Kpi key={key} className={extra} icon={icon} label={label} value={value?.toLocaleString() ?? 'Unavailable'} tone={kpiTone(key, value)} active={activeFinding(target.finding)} onClick={() => toggleTile(target)} />
    }
    return (
      <div className="review-overview">
        <section aria-label="Account review progress" className="review-progress" data-primary="true">
          <div className="review-progress-head">
            <h2>Account review progress</h2>
            <InfoTip label="About account review progress">Completed and pending partition all SAP users, so no account is counted twice. Outdated reviews count as pending until they are reviewed again.</InfoTip>
          </div>
          {known && <p className="progress-summary"><strong className="progress-summary-value">{percent.toFixed(1)}%</strong><span className="progress-summary-caption">{reviewed!.toLocaleString()} of {total!.toLocaleString()} SAP users reviewed</span></p>}
          {known ? <StackedBar inline label="Account review progress" total={total!} segments={[
              { key: 'completed', label: 'Completed reviews', value: reviewed!, tone: 'success', active: activeFinding('reviewed'), onOpen: () => toggleTile({ finding: 'reviewed' }) },
              { key: 'pending', label: 'Pending reviews', value: pending!, tone: 'neutral', active: activeFinding('pending'), title: 'Accounts without a current completed review, including outdated reviews', onOpen: () => toggleTile({ finding: 'pending' }) },
            ]} />
            : <p className="ui-description">Review progress is unavailable until the User Access data and the review annotations are loaded.</p>}
        </section>
        <section aria-label="Review attention" className="review-attention">
          <h2>Review attention</h2>
          <div className="review-kpis">
            {ATTENTION_TILES.filter(([key]) => key !== 'outdated' || data.summary.outdated != null).map((entry) => tile(entry))}
            {tile(FINAL_TILE)}
          </div>
        </section>
      </div>
    )
  }
  const findingOptions = ['any', 'matched', 'directory_missing', 'directory_ambiguous', 'reviewed', 'pending', 'position_change', ...Object.keys(data?.finding_labels || {}), 'stale']
  const findingLabel = (key: string) => FINDING_NAMES[key] || data?.finding_labels[key] || key
  const clearAll = () => { setOffset(0); setSearch(''); setTerm(''); setFindings([]); setLicenses([]); setStates([]); setSort('username'); setDescending(false) }
  const queueParams = 'finding=position_change&sort=priority&limit=25'
  const queue = useQuery({
    queryKey: ['account-review', 'position-queue'],
    queryFn: () => apiRequest<Results>(`/api/account-review?${queueParams}`),
    enabled: (data?.summary.position_changes ?? 0) > 0,
  })
  const closeEditor=()=>{
    if(busy)return
    const dirty=editing&&(reviewer!==(editing.decision?.reviewer||'')||rationale!==(editing.decision?.rationale||'')||decision!==editing.review_state)
    if(dirty&&!window.confirm('Discard unsaved review changes?'))return
    setEditing(null)
  }
  useEffect(() => {
    if (editing || busy || result.isFetching || !wasEditing.current) return
    wasEditing.current = false
    const button = [
      ...document.querySelectorAll<HTMLButtonElement>('[data-review-user]'),
    ].find((el) => el.dataset.reviewUser === returnUser.current)
    if (button) button.focus()
    else
      document
        .querySelector<HTMLInputElement>('input[aria-label="Review finding"]')
        ?.focus()
  }, [editing, busy, result.isFetching])

  useEffect(() => {
    if (data && offset >= data.total && offset)
      setOffset(Math.max(0, Math.floor((data.total - 1) / 25) * 25))
  }, [data?.total, offset])
  const action = async (fn: () => Promise<void>) => {
    setBusy(true)
    setFeedback('')
    setActionError(false)
    try {
      await fn()
    } catch (e) {
      setActionError(true)
      setFeedback(e instanceof Error ? e.message : 'Review action failed.')
    } finally {
      setBusy(false)
    }
  }
  const exportCSV = () =>
    action(async () => {
      if (!data) return
      const started = generation.current
      const lines = [
        '\ufeff' +
          [
            'Username',
            'User group',
            'Full name',
            'SAP validity',
            'SAP lock status',
            'AD account status',
            'Directory match',
            'Findings',
            'License group classification',
            'Review state',
            'Reviewer',
            'Reviewed at',
            'Rationale',
            'Evidence version',
            'Reviewed evidence version',
            'Stale decision',
          ]
            .map(csvField)
            .join(',') +
          '\r\n',
      ]
      let bytes = new TextEncoder().encode(lines[0]).byteLength,
        count = 0
      for (let start = 0; start < data.total; start += 100) {
        const page = await apiRequest<Results>(
          `/api/account-review?${params}&offset=${start}&limit=100`,
        )
        if (
          started !== generation.current ||
          page.data_revision !== data.data_revision ||
          page.total !== data.total ||
          !page.items.length
        )
          throw Error('Review evidence changed. Refresh before exporting.')
        for (const row of page.items) {
          const line =
            [
              row.username,
              row.groups.join(' / '),
              row.name,
              row.sap_validity,
              row.lock_status,
              row.ad_status,
              row.match_status,
              row.findings.map((f) => page.finding_labels[f]).join(' / '),
              row.unlicensed ? 'Configured unlicensed group' : 'Not classified',
              row.review_state,
              row.decision?.reviewer,
              row.decision?.timestamp,
              row.decision?.rationale,
              row.evidence_version,
              row.decision?.evidence_version,
              row.stale ? 'Yes' : 'No',
            ]
              .map(csvField)
              .join(',') + '\r\n'
          bytes += new TextEncoder().encode(line).byteLength
          if (bytes > 32 * 1024 * 1024)
            throw Error('Export exceeds 32 MiB. Narrow the filters.')
          lines.push(line)
          count++
        }
      }
      const check = await apiRequest<Results>(
        `/api/account-review?${params}&limit=1`,
      )
      if (
        started !== generation.current ||
        check.data_revision !== data.data_revision ||
        count !== data.total
      )
        throw Error('Review evidence changed. Refresh before exporting.')
      const content = lines.join(''),
        filename = `sap-lens-account-review-review-${new Date().toISOString().slice(0, 10)}.csv`
      if (window.pywebview) {
        if (!window.pywebview.api.save_user_access_csv)
          throw Error('Update the desktop application to export CSV.')
        const saved = await window.pywebview.api.save_user_access_csv(
          applicationToken(),
          filename,
          content,
        )
        setFeedback(saved ? 'Review CSV saved.' : 'CSV export cancelled.')
        return
      }
      const url = URL.createObjectURL(
          new Blob([content], { type: 'text/csv;charset=utf-8' }),
        ),
        link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setFeedback('Review CSV exported.')
    })
  return (
    <section aria-label="Account Review" className="space-y-4">
      <PageHeader title="Account Review" icon={<PageIcon size={22} aria-hidden="true"/>} titleAction={<InfoTip label="About Account Review">Investigation evidence only. No SAP accounts are modified. Configured unlicensed groups do not prove license entitlement or savings.</InfoTip>}/>
      {data && (
        <>
          {renderOverview()}
          {!data.directory_available && (
            <p role="status">
              Directory enrichment unavailable. Enable and import Employee
              Directory to evaluate AD status and email matching; SAP-only
              review remains available.
            </p>
          )}
        </>
      )}
      {(data?.summary.position_changes ?? 0) > 0 && (
        <section aria-label="Position changes priority queue" className="grid min-w-0 gap-2 rounded-card border border-line bg-surface p-4">
          <h2 className="text-base font-semibold">Position changes · priority review</h2>
          <p className="ui-description">
            Department or job title differs between two Employee Directory imports. The previous values are the last known before the replacement and the current values were first seen when it was published; the real date of the change is unknown. A position change is a prompt to review, not evidence that access is inappropriate. Saving a review here uses the same Account Review decision and history.
          </p>
          {!queue.data ? <p role="status">Loading position changes…</p> : (
            <div className="access-table" role="region" aria-label="Position change review queue" tabIndex={0}>
              <table>
                <thead>
                  <tr>
                    <th>SAP username</th><th>Employee</th><th>Previous position</th><th>Current position</th><th>Priority</th><th><span className="sr-only">Review action</span></th>
                  </tr>
                </thead>
                <tbody>
                  {queue.data.items.map((row) => {
                    const change = row.position_change as PositionChange
                    return (
                      <tr key={row.username}>
                        <td><RoleIdentifier value={row.username} label="username" onOpen={() => onUser(row.username)} href={userHref(row.username)} openLabel={`Open SAP user ${row.username}`} openButtonProps={{ 'data-user': row.username }} /></td>
                        <td>{row.name || 'Unknown'}</td>
                        <td><PositionCell department={change.previous_department} title={change.previous_title} /></td>
                        <td><PositionCell department={change.current_department} title={change.current_title} changed={change.fields} /></td>
                        <td><span className="evidence-badge evidence-warning">{row.priority}</span></td>
                        <td><Button size="compact" className="settings-secondary-button" disabled={busy} onClick={() => startReview(row)} aria-label={`Review position change for ${row.username}`}><ClipboardCheck size={14} aria-hidden="true" />Review</Button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {queue.data && queue.data.total > queue.data.items.length && <p className="ui-description">Showing {queue.data.items.length} of {queue.data.total}. Use the Review finding filter to see all.</p>}
        </section>
      )}
      <FilterLayout label="Filters" activeCount={findings.length + licenses.length + states.length + (search ? 1 : 0)} onClear={clearAll} clearDisabled={!(findings.length || licenses.length || states.length || search) && sort === 'username' && !descending}
        toolbar={<PageToolbar>
          <SortControl label="Sort account reviews" value={sort} options={SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
          <Button className="settings-secondary-button" disabled={busy || !data?.loaded} onClick={() => void exportCSV()}>
            <Download size={16} />
            Export review CSV
          </Button>
        </PageToolbar>}
        sidebar={<div className="grid min-w-0 gap-3" role="search" aria-label="Review filters">
          <FilterSection title="Saved Filters">
            <SavedFilters showClear={false} view="review" state={{search,findings,licenses,states,sort,descending}} apply={s=>{if(typeof s.search==='string')setSearch(s.search);if(Array.isArray(s.findings))setFindings(s.findings.filter(item=>findingOptions.includes(item)));if(Array.isArray(s.licenses))setLicenses(s.licenses.filter(item=>['classified','exclude'].includes(item)));if(Array.isArray(s.states))setStates(s.states.filter(item=>(data?.review_states||[]).includes(item)));if(['username','name','sap_validity','lock_status','ad_status','review_state'].includes(String(s.sort)))setSort(String(s.sort));if(typeof s.descending==='boolean')setDescending(s.descending)}} clear={()=>{setSearch('');setFindings([]);setLicenses([]);setStates([]);setSort('username');setDescending(false)}}/>
          </FilterSection>
          <FilterSection title="Search">
            <SearchInput className={inputClass} aria-label="Search account reviews" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} onClear={() => setSearch('')} />
          </FilterSection>
          <FilterSection title="Review">
            <FormField label="Review finding">
              <MultiSelectFilter label="Review finding" values={findings} options={findingOptions} optionLabel={findingLabel} onChange={setFindings} placeholder="All accounts · type to search" />
            </FormField>
            <FormField label="License group classification">
              <MultiSelectFilter label="License group classification" values={licenses} options={['classified', 'exclude']} optionLabel={value => value === 'classified' ? 'Configured unlicensed groups' : 'Exclude unlicensed groups'} onChange={setLicenses} placeholder="All classifications" />
            </FormField>
            <FormField label="Review decision">
              <MultiSelectFilter label="Review decision" values={states} options={data?.review_states || []} onChange={setStates} placeholder="All decisions" />
            </FormField>
          </FilterSection>
        </div>}>
      {(findings.length > 0 || licenses.length > 0 || states.length > 0 || search) && <div className="active-filter-row" aria-label="Active review filters">
        {findings.map(value => <FilterChip key={`finding-${value}`} removeLabel={`Remove review finding ${findingLabel(value)}`} onRemove={() => setFindings(findings.filter(item => item !== value))}>Finding: {findingLabel(value)}</FilterChip>)}
        {licenses.map(value => <FilterChip key={`license-${value}`} removeLabel={`Remove license classification ${value === 'classified' ? 'Configured unlicensed groups' : 'Exclude unlicensed groups'}`} onRemove={() => setLicenses(licenses.filter(item => item !== value))}>{value === 'classified' ? 'Configured unlicensed groups' : 'Excluding unlicensed groups'}</FilterChip>)}
        {states.map(value => <FilterChip key={`state-${value}`} removeLabel={`Remove review decision ${value}`} onRemove={() => setStates(states.filter(item => item !== value))}>Decision: {value}</FilterChip>)}
        {search && <FilterChip removeLabel="Remove account search filter" onRemove={() => { setSearch(''); setTerm('') }}>Search: {search}</FilterChip>}
      </div>}
      <div className="results-toolbar ui-toolbar"><strong>{data?.total.toLocaleString() ?? '…'} accounts</strong></div>
      <QueryState
        loading={result.isLoading || (dataLoading && !data?.loaded)}
        error={result.error}
      />
      {feedback && (
        <p
          role={actionError ? 'alert' : 'status'}
          className={actionError ? 'text-[var(--error)]' : undefined}
        >
          {feedback}
        </p>
      )}
      {data && !data.loaded && !dataLoading && (
        <p>No User Access CSV loaded. Configure the source in Settings.</p>
      )}
      {data?.loaded && (
        <>
          <div
            className="access-table review-table"
            tabIndex={0}
            role="region"
            aria-label="Account review results"
          >
            <table>
              <thead>
                <tr>
                  {[
                    'SAP username',
                    'Name',
                    'SAP User Group',
                    'SAP validity',
                    'SAP lock status',
                    'AD account status',
                    'Directory match',
                    'Review classification & evidence',
                    'Decision',
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.username}>
                    <td>
                      <RoleIdentifier
                        value={row.username}
                        label="username"
                        onOpen={() => onUser(row.username)}
                        href={userHref(row.username)}
                        openLabel={row.username}
                        openButtonProps={{
                          disabled: busy,
                          'data-user': row.username,
                        }}
                      />
                    </td>
                    <td>{row.name || 'Unknown'}</td>
                    <td>{row.groups.join(', ') || 'Unknown'}</td>
                    <td>
                      <AccountStatus value={row.sap_validity} />
                      {row.evidence&&row.evidence.account_total>row.evidence.accounts.length&&<small>More source intervals in User Details</small>}
                    </td>
                    <td>
                      <AccountStatus kind="lock" value={row.lock_status} />
                    </td>
                    <td>
                      <AccountStatus kind="ad" value={row.ad_status} />
                    </td>
                    <td>{matchLabel(row.match_status)}</td>
                    <td>
                      {row.findings.map((f) => (
                        <p key={f}>{data.finding_labels[f]}</p>
                      ))}
                      {row.unlicensed && (
                        <p className="evidence-badge evidence-neutral">
                          Configured unlicensed group
                        </p>
                      )}
                      {row.position_change && <p><strong>Position change{row.position_change.open ? '' : ' (reviewed)'}:</strong> {changeText(row.position_change)}</p>}
                      {!row.findings.length && !row.position_change && <p>No automated findings</p>}
                    </td>
                    <td>
                      <Button
                        className="settings-secondary-button"
                        disabled={busy}
                        data-review-user={row.username}
                        onClick={() => startReview(row)}
                      >
                        {row.review_state}
                      </Button>
                      {row.stale && (
                        <p className="text-[var(--warning)]">
                          Evidence changed — review again
                        </p>
                      )}
                      {row.decision && (
                        <small>
                          {row.decision.reviewer} ·{' '}
                          {formatTimestamp(row.decision.timestamp)}
                        </small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && <p>No accounts match these review filters.</p>}
          <Pagination
            offset={offset}
            total={data.total}
            limit={25}
            onChange={setOffset}
            label="Account review pages"
          />
        </>
      )}
      </FilterLayout>
      {editing && (
        <Dialog title={`Review account · ${editing.username}`} onClose={closeEditor}><section
          className="review-dialog"
          aria-label={`Review decision for ${editing.username}`}
        >
          <section aria-label="SAP identity" className="review-dialog-section"><h3>SAP identity</h3>
            <MetadataList items={[
              {label:'SAP username',value:<RoleIdentifier value={editing.username} label="username"/>},
              {label:'Name',value:editing.name||'Name unavailable'},
              {label:'SAP User Group',value:editing.groups.join(', ')||'Group unavailable'},
              {label:'Directory match',value:matchLabel(editing.match_status)},
            ]}/>
            <div className="ui-toolbar"><Button onClick={()=>{if(reviewer!==(editing.decision?.reviewer||'')||rationale!==(editing.decision?.rationale||'')||decision!==editing.review_state){if(!window.confirm('Discard unsaved review changes and investigate this user?'))return}setEditing(null);onUser(editing.username)}}><ArrowUpRight size={16} aria-hidden="true"/>Investigate SAP user</Button></div>
          </section>
          {editing.position_change&&<section aria-label="Position change that triggered this review" className="review-dialog-section review-dialog-trigger"><h3>Organizational position changes</h3>
            <table className="review-change-table"><thead><tr><th scope="col"><span className="sr-only">Field</span></th><th scope="col">Previous (last known)</th><th scope="col">Current</th></tr></thead><tbody>
              <tr><th scope="row">Department</th><td>{editing.position_change.previous_department||'—'}</td><td data-changed={editing.position_change.fields.includes('department')||undefined}>{editing.position_change.current_department||'—'}</td></tr>
              <tr><th scope="row">Job title</th><td>{editing.position_change.previous_title||'—'}</td><td data-changed={editing.position_change.fields.includes('title')||undefined}>{editing.position_change.current_title||'—'}</td></tr>
              <tr><th scope="row">Employee Directory snapshot</th><td>{editing.position_change.previous_imported_at?`Imported ${formatTimestamp(editing.position_change.previous_imported_at)}`:'Import time not recorded'}</td><td>First detected {formatTimestamp(editing.position_change.detected_at)}</td></tr>
            </tbody></table>
            <p className="ui-description">The organizational change itself happened at an unknown time between the two imports. A position change prompts a review; it is not evidence that access is inappropriate.</p></section>}
          {actionError&&feedback&&<p role="alert">{feedback}</p>}
          <section aria-label="Review decision" className="review-dialog-section"><h3>Review decision</h3>
          <div className="review-dialog-fields">
          <Filter label="Reviewer">
            <input
              className={inputClass}
              disabled={busy}
              maxLength={120}
              placeholder="Your name (self-declared)"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </Filter>
          <Filter label="Decision">
            <Select
              className={inputClass}
              aria-label="Decision"
              disabled={busy}
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
            >
              {data?.review_states.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </Select>
          </Filter>
          </div>
          <Filter label="Rationale">
            <textarea
              className={inputClass}
              disabled={busy}
              maxLength={2000}
              rows={4}
              placeholder="Why this decision follows from the current evidence"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Filter>
          <p className="text-xs">
            Review decisions are local annotations: the reviewer name is
            self-declared, not an authenticated approval, and nothing is sent to
            or changed in SAP or Active Directory.
          </p>
          <div className="review-decision-actions"><Button
            variant="primary"
            disabled={busy || !reviewer.trim() || !rationale.trim()}
            onClick={() =>
              void action(async () => {
                await apiRequest(
                  `/api/account-review/decision/${encodeURIComponent(editing.username)}`,
                  'POST',
                  {
                    state: decision,
                    reviewer: reviewer.trim(),
                    rationale: rationale.trim(),
                    evidence_version: editing.evidence_version,
                  },
                )
                await qc.invalidateQueries({
                  predicate: (q) =>
                    ['account-review', 'review-history', 'dashboard'].includes(
                      String(q.queryKey[0]),
                    ),
                })
                setEditing(null)
                setFeedback('Review decision saved locally.')
              })
            }
          >
            <Save size={16} />
            Save review decision
          </Button>
          <Button
            className="settings-secondary-button"
            disabled={busy}
            onClick={closeEditor}
          >
            Cancel review changes
          </Button></div>
          </section>
          <section aria-label="Review history" className="review-dialog-section"><h3>Previous decisions</h3>{history.isError&&<p role="alert">Review history could not be loaded. Existing annotations are retained.</p>}{history.isLoading&&<p role="status">Loading review history…</p>}{history.data&&!history.data.total&&<p>No previous decisions recorded.</p>}{history.data?.items.map((event,index)=><article key={`${event.timestamp}-${index}`} className="review-history-entry"><div><strong>{event.state}</strong><span>{event.reviewer} · {formatTimestamp(event.timestamp)}</span></div><p>{event.rationale}</p></article>)}<Pagination label="Review history pages" offset={historyOffset} total={history.data?.total||0} limit={25} onChange={setHistoryOffset}/></section>
        </section></Dialog>
      )}
    </section>
  )
}
