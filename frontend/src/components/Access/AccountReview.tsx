import { Dialog } from '@/components/Shared/Dialog'
import { ReviewFindings, type ReviewEvidence } from '@/components/Shared/ReviewFindings'
import { PageHeader, MetadataList } from '@/components/Shared/Presentation'
import { ClipboardCheck as PageIcon } from 'lucide-react'
import { StatusCard, FilterPanel, ResultsToolbar } from '@/components/Shared/InvestigationPatterns'
import { SearchInput } from '@/components/Shared/Controls'
import { Button } from '@/components/Shared/Button'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { useApplicationData } from '@/state/ApplicationData'
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Save } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import { useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
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
          <div className="review-metric-groups">{[
            ['Account status',[['total','SAP accounts'],['mismatch','AD disabled / SAP valid and unlocked'],['missing','Missing or ambiguous directory matches']]],
            ['Review findings',[['requiring_review','Accounts requiring review'],['unlicensed','Classified unlicensed']]],
            ['Review progress',[['reviewed','Reviewed accounts'],['outdated','Outdated reviews']]],
          ].map(([title,metrics])=><section key={String(title)} aria-label={String(title)}><h2>{String(title)}</h2><div className="review-metrics">{(metrics as string[][]).map(([key,label])=><StatusCard key={key} label={label} value={data.summary[key]?.toLocaleString()??'Unavailable'} tone={['mismatch','missing','outdated'].includes(key)&&!!data.summary[key]?'warning':'neutral'}>{key==='outdated'&&<button className="text-link" onClick={()=>setFinding('stale')}>Review changed evidence</button>}</StatusCard>)}</div></section>)}</div>
          {!data.directory_available && (
            <p role="status">
              Directory enrichment unavailable. Enable and import Employee
              Directory to evaluate AD status and email matching; SAP-only
              review remains available.
            </p>
          )}
        </>
      )}
      <SavedFilters showClear={false} view="review" state={{search,finding:finding||'',license,state,sort,descending}} apply={s=>{if(typeof s.search==='string')setSearch(s.search);if(typeof s.finding==='string'&&['','any','stale','matched','reviewed','pending',...Object.keys(data?.finding_labels||{})].includes(s.finding))setFinding(s.finding);if(['','classified','exclude'].includes(String(s.license)))setLicense(String(s.license));if(['',...(data?.review_states||[])].includes(String(s.state)))setState(String(s.state));if(['username','name','sap_validity','lock_status','ad_status','review_state'].includes(String(s.sort)))setSort(String(s.sort));if(typeof s.descending==='boolean')setDescending(s.descending)}} clear={()=>{setSearch('');setFinding('');setLicense('');setState('');setSort('username');setDescending(false)}}/>
      <FilterPanel label="Review filters" className="review-filters">
        <Filter label="Search account reviews">
          <SearchInput
            className={inputClass}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </Filter>
        <Filter label="Review finding">
          <Select
            className={inputClass}
            aria-label="Review finding"
            value={finding || ''}
            onChange={(e) => setFinding(e.target.value)}
          >
            <option value="">All accounts</option>
            <option value="any">Accounts requiring review</option>
            <option value="matched">Reliably matched identities</option><option value="reviewed">Reviewed accounts</option><option value="pending">Pending reviews</option>
            {Object.entries(data?.finding_labels || {}).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
            <option value="stale">Outdated reviews · changed evidence</option>
          </Select>
        </Filter>
        <Filter label="License group classification">
          <Select
            className={inputClass}
            aria-label="License group classification"
            value={license}
            onChange={(e) => setLicense(e.target.value)}
          >
            <option value="">All classifications</option>
            <option value="classified">Configured unlicensed groups</option>
            <option value="exclude">Exclude unlicensed groups</option>
          </Select>
        </Filter>
        <Filter label="Review decision">
          <Select
            className={inputClass}
            aria-label="Review decision"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            <option value="">All decisions</option>
            {data?.review_states.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </Filter>

        <div className="sort-control"><Filter label="Sort account reviews">
          <Select
            className={inputClass}
            aria-label="Sort account reviews"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {[
              'username',
              'name',
              'sap_validity',
              'lock_status',
              'ad_status',
              'review_state',
            ].map((s) => (
              <option key={s} value={s}>
                {{username:'Username',name:'Name',sap_validity:'SAP Validity',lock_status:'Lock Status',ad_status:'AD Status',review_state:'Review State'}[s]}
              </option>
            ))}
          </Select>
        </Filter>
        <label className="filter-toggle">
          <input
            type="checkbox"
            checked={descending}
            onChange={(e) => setDescending(e.target.checked)}
          />
          Descending
        </label></div>
        <ClearFilterButton
          onClick={() => {
            setOffset(0)
            setSearch('')
            setTerm('')
            setFinding('')
            setLicense('')
            setState('')
            setSort('username')
            setDescending(false)
          }}
        >
          Clear filters
        </ClearFilterButton>

      </FilterPanel>
      <ResultsToolbar><strong>{data?.total.toLocaleString() ?? '…'} accounts</strong>        <Button
          className="settings-secondary-button"
          disabled={busy || !data?.loaded}
          onClick={() => void exportCSV()}
        >
          <Download size={16} />
          Export review CSV
        </Button></ResultsToolbar>
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
                    </td>
                    <td>
                      <AccountStatus kind="lock" value={row.lock_status} />
                    </td>
                    <td>
                      <AccountStatus kind="ad" value={row.ad_status} />
                    </td>
                    <td>{({matched:'Matched',duplicate_email:'Duplicate Email',missing_email:'Missing Email',ambiguous:'Ambiguous Match',unmatched:'Unmatched',disabled:'Disabled',unavailable:'Unavailable'} as Record<string,string>)[row.match_status] || row.match_status.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</td>
                    <td>
                      {row.findings.map((f) => (
                        <p key={f}>{data.finding_labels[f]}</p>
                      ))}
                      {row.unlicensed && (
                        <p className="evidence-badge evidence-neutral">
                          Configured unlicensed group
                        </p>
                      )}
                      {!row.findings.length && <p>No supported finding</p>}
                    </td>
                    <td>
                      <Button
                        className="settings-secondary-button"
                        disabled={busy}
                        data-review-user={row.username}
                        onClick={() => {
                          returnUser.current = row.username
                          setEditing(row)
                          setReviewer(row.decision?.reviewer || '')
                          setRationale(row.decision?.rationale || '')
                          setDecision(row.review_state)
                        }}
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
      {editing && (
        <Dialog title={`Review account · ${editing.username}`} onClose={closeEditor}><section
          className="settings-card space-y-3"
          aria-label={`Review decision for ${editing.username}`}
        >
          <h2>Review {editing.username}</h2><p>{editing.name||'Name unavailable'} · {editing.groups.join(', ')||'Group unavailable'}</p>
          <ReviewFindings row={editing} labels={data?.finding_labels||{}} onInvestigate={()=>{if(reviewer!==(editing.decision?.reviewer||'')||rationale!==(editing.decision?.rationale||'')||decision!==editing.review_state){if(!window.confirm('Discard unsaved review changes and investigate this user?'))return}setEditing(null);onUser(editing.username)}}/>
          {editing.decision&&<MetadataList items={[{label:'Previous decision',value:editing.decision.state},{label:'Previous reviewer',value:editing.decision.reviewer},{label:'Reviewed at',value:formatTimestamp(editing.decision.timestamp)},{label:'Previous rationale',value:editing.decision.rationale}]}/>}
          {actionError&&feedback&&<p role="alert">{feedback}</p>}
          <Filter label="Reviewer">
            <input
              className={inputClass}
              disabled={busy}
              maxLength={120}
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
          <Filter label="Rationale">
            <textarea
              className={inputClass}
              disabled={busy}
              maxLength={2000}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Filter>
          <p className="text-xs">
            Reviewer is a local self-declared annotation, not an authenticated
            approval. Nothing is sent to SAP.
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
          <section aria-label="Review history"><h3>Previous decisions</h3>{history.isError&&<p role="alert">Review history could not be loaded. Existing annotations are retained.</p>}{history.isLoading&&<p role="status">Loading review history…</p>}{history.data&&!history.data.total&&<p>No previous decisions recorded.</p>}{history.data?.items.map((event,index)=><article key={`${event.timestamp}-${index}`}><strong>{event.state}</strong><p>{event.reviewer} · {formatTimestamp(event.timestamp)}</p><p>{event.rationale}</p></article>)}<Pagination label="Review history pages" offset={historyOffset} total={history.data?.total||0} limit={25} onChange={setHistoryOffset}/></section>
        </section></Dialog>
      )}
    </section>
  )
}
