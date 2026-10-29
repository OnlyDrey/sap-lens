import { Dialog } from '@/components/Shared/Dialog'
import { userHref } from '@/hooks/useViewHistory'
import { ReviewFindings, type ReviewEvidence } from '@/components/Shared/ReviewFindings'
import { PageHeader, MetadataList } from '@/components/Shared/Presentation'
import { ClipboardCheck as PageIcon } from 'lucide-react'
import { FilterTile } from '@/components/Shared/InvestigationPatterns'
import { FilterLayout, FilterSection, PageToolbar, SortControl } from '@/components/Shared/FilterLayout'
import { FormField } from '@/components/Shared/Controls'
import { SearchInput } from '@/components/Shared/Controls'
import { Button } from '@/components/Shared/Button'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { useApplicationData } from '@/state/ApplicationData'
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Download, Save } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import { useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { FilterChip } from '@/components/Shared/FilterChip'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { Select } from '@/components/Shared/Select'
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

/** Overview tiles: each applies its finding (and license classification) to the list. */
const TILE_GROUPS: [string, [string, string, { finding: string; license?: string }][]][] = [
  ['Account status', [['total', 'SAP accounts', { finding: '' }], ['mismatch', 'AD disabled / SAP valid and unlocked', { finding: 'ad_disabled_open' }], ['missing', 'Missing or ambiguous directory matches', { finding: 'directory_match' }]]],
  ['Review findings', [['requiring_review', 'Accounts requiring review', { finding: 'any' }], ['position_changes', 'Position changes', { finding: 'position_change' }], ['unlicensed', 'Classified unlicensed', { finding: '', license: 'classified' }]]],
  ['Review progress', [['reviewed', 'Reviewed accounts', { finding: 'reviewed' }], ['outdated', 'Outdated reviews', { finding: 'stale' }], ['pending', 'Pending reviews', { finding: 'pending' }]]],
]
const FINDING_NAMES: Record<string, string> = { any: 'Accounts requiring review', matched: 'Reliably matched identities', reviewed: 'Reviewed accounts', pending: 'Pending reviews', position_change: 'Position changes', stale: 'Outdated reviews' }

export function AccountReview({ onUser }: { onUser: (name: string) => void }) {
  const { loading: dataLoading } = useApplicationData()
  const [finding, setFinding] = useHistoryValue('reviewFinding')
  const {view,change}=useViewHistory()
  const retained=view.accountReviewFilters
  const [search, setSearch] = useState(retained?.search||''),
    [license, setLicense] = useState(retained?.license||''),
    [state, setState] = useState(retained?.state||''),
    [sort, setSort] = useState(retained?.sort||'username'),
    [descending, setDescending] = useState(retained?.descending||false),
    [offset, setOffset] = useState(0)
  useEffect(()=>change({accountReviewFilters:{search,license,state,sort,descending}},true),[search,license,state,sort,descending,change])
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
    [term, finding, license, state, sort, descending],
  )
  const params = new URLSearchParams({
    search: term,
    finding: finding || '',
    license_group: license,
    review_state: state,
    sort,
    descending: String(descending),
  })
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
  const clearAll = () => { setOffset(0); setSearch(''); setTerm(''); setFinding(''); setLicense(''); setState(''); setSort('username'); setDescending(false) }
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
        .querySelector<HTMLSelectElement>('select[aria-label="Review finding"]')
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
      <PageHeader title="Account Review" icon={<PageIcon size={22} aria-hidden="true"/>}/>
      <p className="text-sm text-[var(--muted)]">
        Investigation evidence only. No SAP accounts are modified. Configured
        unlicensed groups do not prove license entitlement or savings.
      </p>
      {data && (
        <>
          <div className="review-metric-groups">{TILE_GROUPS.map(([title,tiles])=><section key={title} aria-label={title}><h2>{title}</h2><div className="review-metrics">{tiles.map(([key,label,target])=>{
            const value=data.summary[key]
            const active=target.license?license===target.license&&!finding:!target.license&&(finding||'')===target.finding&&!license
            return <FilterTile key={key} label={label} value={value?.toLocaleString()??'Unavailable'} tone={['mismatch','missing','outdated'].includes(key)&&!!value?'warning':'neutral'} active={active} onClick={()=>{setFinding(target.finding);setLicense(target.license||'')}}/>})}</div></section>)}</div>
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
                    <th>SAP username</th><th>Employee</th><th>Previous department</th><th>Current department</th><th>Previous job title</th><th>Current job title</th><th>Previous snapshot</th><th>First detected</th><th>Status</th><th>Priority</th><th>Review action</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.data.items.map((row) => {
                    const change = row.position_change as PositionChange
                    return (
                      <tr key={row.username}>
                        <td><RoleIdentifier value={row.username} label="username" onOpen={() => onUser(row.username)} href={userHref(row.username)} openLabel={`Open SAP user ${row.username}`} openButtonProps={{ 'data-user': row.username }} /></td>
                        <td>{row.name || 'Unknown'}</td>
                        <td className={change.fields.includes('department') ? '' : 'text-muted'}>{change.previous_department || '—'}</td>
                        <td>{change.fields.includes('department') ? <strong>{change.current_department}</strong> : <span className="text-muted">{change.current_department || '—'} (unchanged)</span>}</td>
                        <td className={change.fields.includes('title') ? '' : 'text-muted'}>{change.previous_title || '—'}</td>
                        <td>{change.fields.includes('title') ? <strong>{change.current_title}</strong> : <span className="text-muted">{change.current_title || '—'} (unchanged)</span>}</td>
                        <td>{change.previous_imported_at ? formatTimestamp(change.previous_imported_at) : <span className="text-muted">Not recorded</span>}</td>
                        <td>{formatTimestamp(change.detected_at)}</td>
                        <td>{row.review_state}</td>
                        <td><span className="evidence-badge evidence-warning">{row.priority}</span></td>
                        <td><Button className="settings-secondary-button" disabled={busy} onClick={() => startReview(row)} aria-label={`Review position change for ${row.username}`}>Review</Button></td>
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
      <FilterLayout label="Filters" activeCount={[finding, license, state, search].filter(Boolean).length} onClear={clearAll} clearDisabled={!(finding || license || state || search) && sort === 'username' && !descending}
        toolbar={<PageToolbar>
          <SortControl label="Sort account reviews" value={sort} options={SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
          <Button className="settings-secondary-button" disabled={busy || !data?.loaded} onClick={() => void exportCSV()}>
            <Download size={16} />
            Export review CSV
          </Button>
        </PageToolbar>}
        sidebar={<div className="grid min-w-0 gap-3" role="search" aria-label="Review filters">
          <FilterSection title="Saved Filters">
            <SavedFilters showClear={false} view="review" state={{search,finding:finding||'',license,state,sort,descending}} apply={s=>{if(typeof s.search==='string')setSearch(s.search);if(typeof s.finding==='string'&&['','any','stale','matched','reviewed','pending','position_change',...Object.keys(data?.finding_labels||{})].includes(s.finding))setFinding(s.finding);if(['','classified','exclude'].includes(String(s.license)))setLicense(String(s.license));if(['',...(data?.review_states||[])].includes(String(s.state)))setState(String(s.state));if(['username','name','sap_validity','lock_status','ad_status','review_state'].includes(String(s.sort)))setSort(String(s.sort));if(typeof s.descending==='boolean')setDescending(s.descending)}} clear={()=>{setSearch('');setFinding('');setLicense('');setState('');setSort('username');setDescending(false)}}/>
          </FilterSection>
          <FilterSection title="Search">
            <SearchInput className={inputClass} aria-label="Search account reviews" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} onClear={() => setSearch('')} />
          </FilterSection>
          <FilterSection title="Review">
            <FormField label="Review finding">
              <Select className={inputClass} aria-label="Review finding" value={finding || ''} onChange={(e) => setFinding(e.target.value)}>
                <option value="">All accounts</option>
                <option value="any">Accounts requiring review</option>
                <option value="matched">Reliably matched identities</option><option value="reviewed">Reviewed accounts</option><option value="pending">Pending reviews</option><option value="position_change">Position changes (department or job title)</option>
                {Object.entries(data?.finding_labels || {}).map(([key, label]) => (<option key={key} value={key}>{label}</option>))}
                <option value="stale">Outdated reviews · changed evidence</option>
              </Select>
            </FormField>
            <FormField label="License group classification">
              <Select className={inputClass} aria-label="License group classification" value={license} onChange={(e) => setLicense(e.target.value)}>
                <option value="">All classifications</option>
                <option value="classified">Configured unlicensed groups</option>
                <option value="exclude">Exclude unlicensed groups</option>
              </Select>
            </FormField>
            <FormField label="Review decision">
              <Select className={inputClass} aria-label="Review decision" value={state} onChange={(e) => setState(e.target.value)}>
                <option value="">All decisions</option>
                {data?.review_states.map((s) => (<option key={s}>{s}</option>))}
              </Select>
            </FormField>
          </FilterSection>
        </div>}>
      {(finding || license || state || search) && <div className="active-filter-row" aria-label="Active review filters">
        {finding && <FilterChip removeLabel="Remove review finding filter" onRemove={() => setFinding('')}>Finding: {FINDING_NAMES[finding] || data?.finding_labels[finding] || finding}</FilterChip>}
        {license && <FilterChip removeLabel="Remove license classification filter" onRemove={() => setLicense('')}>{license === 'classified' ? 'Configured unlicensed groups' : 'Excluding unlicensed groups'}</FilterChip>}
        {state && <FilterChip removeLabel="Remove review decision filter" onRemove={() => setState('')}>Decision: {state}</FilterChip>}
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
          <section aria-label="SAP identity and organizational context" className="review-dialog-section"><h3>SAP identity and organizational context</h3>
            <MetadataList items={[
              {label:'SAP username',value:<RoleIdentifier value={editing.username} label="username"/>},
              {label:'Name',value:editing.name||'Name unavailable'},
              {label:'SAP User Group',value:editing.groups.join(', ')||'Group unavailable'},
              {label:'Directory match',value:matchLabel(editing.match_status)},
            ]}/>
          </section>
          {editing.position_change&&<section aria-label="Position change that triggered this review" className="review-dialog-section review-dialog-trigger"><h3>Position changes</h3>
            <table className="review-change-table"><thead><tr><th scope="col"><span className="sr-only">Field</span></th><th scope="col">Previous (last known)</th><th scope="col">Current</th></tr></thead><tbody>
              <tr><th scope="row">Department</th><td>{editing.position_change.previous_department||'—'}</td><td data-changed={editing.position_change.fields.includes('department')||undefined}>{editing.position_change.current_department||'—'}</td></tr>
              <tr><th scope="row">Job title</th><td>{editing.position_change.previous_title||'—'}</td><td data-changed={editing.position_change.fields.includes('title')||undefined}>{editing.position_change.current_title||'—'}</td></tr>
              <tr><th scope="row">Employee Directory snapshot</th><td>{editing.position_change.previous_imported_at?`Imported ${formatTimestamp(editing.position_change.previous_imported_at)}`:'Import time not recorded'}</td><td>First detected {formatTimestamp(editing.position_change.detected_at)}</td></tr>
            </tbody></table>
            <p className="ui-description">The organizational change itself happened at an unknown time between the two imports. A position change prompts a review; it is not evidence that access is inappropriate.</p></section>}
          <ReviewFindings positionTrigger={!!editing.position_change} row={editing} labels={data?.finding_labels||{}}/>
          <section aria-label="Investigation actions" className="review-dialog-section"><h3>Investigation actions</h3>
            <div className="ui-toolbar"><Button onClick={()=>{if(reviewer!==(editing.decision?.reviewer||'')||rationale!==(editing.decision?.rationale||'')||decision!==editing.review_state){if(!window.confirm('Discard unsaved review changes and investigate this user?'))return}setEditing(null);onUser(editing.username)}}><ArrowUpRight size={16} aria-hidden="true"/>Investigate SAP user</Button></div>
          </section>
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
