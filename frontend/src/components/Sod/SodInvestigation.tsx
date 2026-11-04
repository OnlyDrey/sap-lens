import {useSodReviewSwitchGuard} from '@/hooks/useSodReviewNavigation'
import {SodDecisionStatus} from './SodDecisionStatus'
import {ContentTabList} from '@/components/Shared/Navigation'
import {apiRequest} from '@/api/client'
import { sentenceCase } from '@/lib/labels'
import { useRoleDescriptions } from '@/hooks/useRoleModules'
import { useModuleDefinitions } from '@/components/Modules/ModuleRegistry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { DisclosureChevron } from '@/components/Shared/DisclosureChevron'
import { Layers, ShieldCheck, ListChecks, Check, ClipboardCheck, FlaskConical, History, Search, Trash2, Wrench } from 'lucide-react'
import { emptyFilters, scopeParams, sod, sodPost, type ActivityDetail, type AssignmentRow, type DecisionEvent, type OverviewAssignment, type Subject, type ReviewCoverage,type RemediationVerification } from '@/api/sod'
import { useViewHistory, userHref } from '@/hooks/useViewHistory'
import { SidePanel } from '@/components/Shared/SidePanel'
import { Button, IconButton } from '@/components/Shared/Button'
import { Card, ErrorState, EmptyState, LoadingState, StatusBadge, Toolbar } from '@/components/Shared/Presentation'
import { Checkbox, FormField, Input } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { RoleModuleBadge } from '@/components/Shared/RoleModuleBadge'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { NorwegianDateInput, parseNorwegianDate } from '@/components/Shared/NorwegianDateInput'
import { formatDate, formatTimestamp } from '@/lib/dateFormat'
import { SodPill } from '@/lib/sodAppearance'
import { AlertNote, invalidateSod, KIND_LABEL, LifecycleBadge, RoleCodeList } from './SodShared'
import { ActionDialog } from './SodRemediation'

type Kind = 'activity' | 'assignment' | 'acceptance' | 'risk'
export interface Item { key: string; user: string; ref: string; evidence_version: string }
export interface FormState { kind: Kind; items: Item[]; heading: string; decision?: string }
const OPTIONS: Record<Kind, { value: string; label: string }[]> = {
  activity: [{ value: 'Approved', label: 'Approved: the user needs this activity' },{value:'Conditional',label:'Approved with conditions (retained review model)'}, { value: 'Investigate', label: 'Investigate: further assessment is required' }, { value: 'Remove', label: 'Remove: the user should not have this activity' }, { value: 'Pending', label: 'Reset to pending' }],
  assignment: [{ value: 'Keep', label: 'Keep this role assignment' }, { value: 'Remove', label: 'Remove this role assignment' }, { value: 'Investigate', label: 'Investigate: further investigation is required' }, { value: 'Pending', label: 'Reset to pending' }],
  risk:[{value:'Approved',label:'Approved: the risk is acceptable for this review'},{value:'Remove',label:'Remove: remediation is required'},{value:'Investigate',label:'Investigate: further assessment is required'},{value:'Pending',label:'Reset to pending'}],
  acceptance: [{ value: 'Accepted', label: 'Accept the risk' }, { value: 'Rejected', label: 'Reject the risk' }, { value: 'Pending', label: 'Reset to pending' }],
}
const QUICK_RATIONALE = 'Reviewed in Role Assignment Review'
const reviewerKey = 'sap-lens-sod-reviewer'
const rememberedReviewer = () => { try { return sessionStorage.getItem(reviewerKey) || '' } catch { return '' } }

const DECIDED = new Set(['Approved', 'Keep', 'Accepted', 'Conditional', 'Removal required', 'Rejected'])
const progressOf = (rows: { decision?: string; acceptance?: string; review_coverage?: ReviewCoverage }[]) => rows.filter((row) => row.review_coverage?.reviewed ?? DECIDED.has((row.decision ?? row.acceptance) as string)).length

/** Unified review workspace for one SAP user: three independent review sections, history on demand and read-only supporting evidence. */
type InvestigationProps = {context:string;user:string;risk?:string;activity?:string;onClose:()=>void;onScope?:(subject:{user:string})=>void}

export function SodInvestigation(props:InvestigationProps){
 const [reviewTab,setReviewTab]=useState<Kind>('assignment')
 const {user,risk,activity,onClose}=props
 return <SidePanel title={`${user}${risk ? ` · ${risk}` : activity ? ` · ${activity}` : ''}`} onClose={onClose}>
  {/* The panel and tab persist; forms, selections and pending callbacks belong to one evidence scope. */}
  <InvestigationContent key={JSON.stringify([props.context,user])} {...props} reviewTab={reviewTab} setReviewTab={setReviewTab}/>
 </SidePanel>
}

function InvestigationContent({context,user,risk,activity,onScope,reviewTab,setReviewTab}:InvestigationProps & {reviewTab:Kind;setReviewTab:(tab:Kind)=>void}) {
  const qc = useQueryClient(),
    { change } = useViewHistory(),
    [form, setForm] = useState<FormState | null>(null),
    [picked, setPicked] = useState<Record<Kind, string[]>>({ activity: [], assignment: [], acceptance: [],risk:[] }),
    [selection, setSelection] = useState<string[]>([]),
    [simulation, setSimulation] = useState<null | { before: string[]; after: string[]; resolved: string[]; lost_activities: string[]; warnings: string[]; eliminates_all: boolean }>(null),
    [error, setError] = useState(''),
    [action, setAction] = useState<null | { assignment: AssignmentRow }>(null),
    [quickReviewer, setQuickReviewer] = useState(rememberedReviewer),
    [quickRationale, setQuickRationale] = useState(''),
    [quickBusy, setQuickBusy] = useState<Map<string,string>>(new Map()),
    [quickError, setQuickError] = useState(''),
    formRef = useRef<HTMLDivElement>(null)
  useSodReviewSwitchGuard(!!form)
  const params = scopeParams(context, emptyFilters, { user, ...(risk ? { risk } : {}), ...(activity ? { activity } : {}) })
  const query = useQuery({ queryKey: ['sod-subject', params.toString()], queryFn: () => sod<Subject>('/api/sod/subject', params) })
  const runtime=useQuery({queryKey:['review-runtime-identity'],queryFn:()=>apiRequest<{username:string;role:string}>('/api/runtime'),retry:false})
  const authenticated=!!runtime.data?.username
  const reviewer=runtime.data?.username||quickReviewer
  const tabId=useId()
  const data = query.data
  const ok = !!data?.reviewable
  useEffect(() => { if (form) formRef.current?.scrollIntoView?.({ block: 'nearest' }) }, [form])
  const simulate = async (removed: string[]) => {
    setError('')
    try { setSimulation(await sodPost('/api/sod/simulate', { context, user, removed })) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Simulation failed.') }
  }
  /** One-click review. Each assignment is decided on its own: requests run one after another, so each reads the revision the previous
   * save produced, and the row changes only after the server confirmed it. A busy marker belongs to one row, never to the panel. */
  const queue = useRef<Promise<void>>(Promise.resolve())
  const pendingRows=useRef(new Set<string>())
  const quickDecide = (row: OverviewAssignment, decision: 'Keep' | 'Remove' | 'Investigate') => {
    if(pendingRows.current.has(row.id))return
    setQuickError('')
    if (!reviewer.trim()) { setQuickError('Enter a reviewer name above before recording a decision. It is self-reported and stored with each decision.'); return }
    pendingRows.current.add(row.id)
    setQuickBusy(previous=>new Map(previous).set(row.id,decision))
    const savedReviewer = reviewer.trim(), justification = quickRationale.trim() || QUICK_RATIONALE
    const save = async () => {
      let confirmed=false
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          const current = qc.getQueryData<Subject>(['sod-subject', params.toString()]) ?? data
          if (!current) return
          try {
            const recorded=await sodPost<{revision:number;confirmed_assignments?:Record<string,Pick<OverviewAssignment,'decision'|'event'|'decision_summary'|'review_coverage'>>}>('/api/sod/decisions/assignment', { context: current.context, expected_revision: current.revision, expected_generation: current.generation, items: [item(row.id, row.role, row.evidence_version)],
              decision, reviewer:savedReviewer, approver: '', justification, controls: '', expires: null })
            const patch=recorded.confirmed_assignments?.[row.id]
            confirmed=!!patch
            qc.setQueryData<Subject>(['sod-subject',params.toString()],previous=>previous&&previous.generation===current.generation&&previous.revision<=recorded.revision?{...previous,revision:recorded.revision,overview:{...previous.overview,assignments:previous.overview.assignments.map(item=>item.id===row.id&&patch?{...item,...patch}:item)}}:previous)
            break
          } catch (cause) {
            // Another save moved the shared revision: reload it once and retry this one assignment.
            if (attempt === 0 && cause instanceof Error && /decisions changed/i.test(cause.message)) {
              await invalidateSod(qc,['sod-subject',params.toString()])
              const fresh=qc.getQueryData<Subject>(['sod-subject',params.toString()])?.overview.assignments.find(item=>item.id===row.id)
              if(!fresh||fresh.evidence_version!==row.evidence_version||fresh.event?.event_id!==row.event?.event_id){cause.message='This assignment changed in another session. Review its current evidence and decision before choosing again.';throw cause}
              continue
            }
            throw cause
          }
        }
        try { sessionStorage.setItem(reviewerKey, savedReviewer) } catch { /* optional convenience */ }
        if(confirmed)void invalidateSod(qc,['sod-subject',params.toString()]).catch(()=>{})
        else await invalidateSod(qc,['sod-subject',params.toString()])
      } catch (cause) {
        setQuickError(`${decision === 'Keep' ? 'Keep' : decision === 'Investigate' ? 'Investigate' : 'Removal recommendation'} for ${row.role} was not saved. ${cause instanceof Error ? cause.message : 'Try again.'}`)
      } finally {
        pendingRows.current.delete(row.id)
        setQuickBusy(previous=>{const next=new Map(previous);next.delete(row.id);return next})
      }
    }
    queue.current = queue.current.then(save)
  }
  const toggle = (id: string) => { setSimulation(null); setSelection((previous) => (previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id])) }
  const pick = (kind: Kind, key: string) => setPicked((previous) => ({ ...previous, [kind]: previous[kind].includes(key) ? previous[kind].filter((value) => value !== key) : [...previous[kind], key] }))
  const item = (key: string, ref: string, version: string): Item => ({ key, user, ref, evidence_version: version })
  const overview = data?.overview
  const roleTexts = useRoleDescriptions(), areaCodes = Object.keys(useModuleDefinitions())
  const describe = (names: string[]) => { for (const name of names) { const text = roleTexts.get(name); if (text) return presentRoleDescription(text, areaCodes).description } return undefined }
  const tcodesOf = new Map<string, string[]>()
  for (const block of data?.activities || []) for (const entry of block.assignments) tcodesOf.set(entry.id, [...new Set([...(tcodesOf.get(entry.id) || []), ...entry.tcodes])].sort())
  // A matrix cell opens only that user-risk or user-activity and the evidence behind it; the user row opens everything.
  const scoped = !!(risk || activity)
  const allActivities = overview?.activities || [], allAssignments = overview?.assignments || [], allRisks = overview?.risks || []
  const activities = !scoped ? allActivities : allActivities.filter((row) => (risk ? row.risks.includes(risk) : row.activity === activity))
  const assignments = !scoped ? allAssignments : allAssignments.filter((row) => (risk ? row.risks.includes(risk) : row.activities.includes(activity as string)))
  const risks = !scoped ? allRisks : allRisks.filter((row) => (risk ? row.risk_id === risk : activities.some((item) => item.risks.includes(row.risk_id))))
  const total = activities.length + assignments.length + risks.length
  const done = progressOf(activities) + progressOf(assignments) + progressOf(risks)
  const batch = (kind: Kind, heading: string, rows: Item[]) => setForm({ kind, items: rows, heading })
  const focus = (name: string, kind: 'activity' | 'risk') => (kind === 'activity' ? activity === name : risk === name)
  return (
    <>
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : !data || !overview ? <LoadingState /> : <>
        <section className="sod-section" aria-label="Subject summary">
          <Toolbar>
            <RoleIdentifier value={user} label="SAP username" onOpen={() => change({ page: 'users', accessMode: 'directory', user, userContext: {}, detailRole: null, settings: false })} openLabel={`Open SAP user ${user}`} href={userHref(user)} />
            {data.groups.map((group) => <StatusBadge key={group}>{group}</StatusBadge>)}
            {data.frozen && <StatusBadge tone="info">Frozen snapshot, read only</StatusBadge>}
            {!data.frozen && !data.reviewable && <StatusBadge>Read only</StatusBadge>}
          </Toolbar>
          {data.account && <p className="ui-description flex flex-wrap items-center gap-x-2 gap-y-1"><span>Directory match</span><StatusBadge tone={data.account.directory_match === 'matched' ? 'success' : ['ambiguous', 'unmatched'].includes(data.account.directory_match) ? 'warning' : 'neutral'}>{sentenceCase(data.account.directory_match)}</StatusBadge><span>AD {data.account.ad_status}{data.account.lock_status ? ` · SAP ${data.account.lock_status}` : ''}</span></p>}
          {scoped && <p className="ui-description" role="status">Showing only {risk ? `risk ${risk}` : `activity ${activity}`} and the evidence behind it.{onScope && <> <Button variant="ghost" onClick={() => onScope({ user })}>Show all review items for {user}</Button></>}</p>}
          <p className="ui-description">Access review coverage can derive from current role or activity decisions. Formal risk acceptance and verified remediation remain separate; planned removals never change detected conflicts.</p>
        </section>


        <FormField label={authenticated?'Reviewer (authenticated)':'Reviewer (self-reported)'}><Input value={reviewer} readOnly={authenticated} maxLength={120} placeholder="Your name" onChange={event=>{setQuickReviewer(event.target.value);try{sessionStorage.setItem(reviewerKey,event.target.value)}catch{/* optional convenience */}}}/></FormField>
        <ContentTabList label="Subject review sections" value={reviewTab} onChange={value=>setReviewTab(value as Kind)} idPrefix={tabId} panelId={value=>`${tabId}-panel-${value}`} items={[
          {value:'assignment',label:`Roles ${progressOf(assignments)}/${assignments.length}`,icon:<Layers size={16} aria-hidden="true"/>},
          {value:'activity',label:`Activities ${progressOf(activities)}/${activities.length}`,icon:<ListChecks size={16} aria-hidden="true"/>},
          {value:'risk',label:`Risks ${progressOf(risks)}/${risks.length}`,icon:<ShieldCheck size={16} aria-hidden="true"/>}]}/>
        {form && <div ref={formRef} hidden={reviewTab!==(form.kind==='acceptance'?'risk':form.kind)}><DecisionForm key={form.heading} form={form} sharedReviewer={reviewer} subject={data} onCancel={() => setForm(null)} onSaved={async () => { setForm(null); setPicked({ activity: [], assignment: [], acceptance: [],risk:[] }); await invalidateSod(qc,['sod-subject',params.toString()]) }} /></div>}
        <div role="tabpanel" id={`${tabId}-panel-assignment`} aria-labelledby={`${tabId}-assignment`} hidden={reviewTab!=='assignment'}>        <ReviewSection title="Role Assignment Review" kind="assignment" done={progressOf(assignments)} total={assignments.length} ok={ok} picked={picked.assignment} keys={assignments.map((row) => row.id)} onPickAll={(keys) => setPicked((previous) => ({ ...previous, assignment: keys }))}
          note="Reviewed with the other activities each role supplies, so one assignment can serve several approved activities."
          onBatch={() => batch('assignment', `Batch role assignment review (${picked.assignment.length})`, assignments.filter((row) => picked.assignment.includes(row.id)).map((row) => item(row.id, row.role, row.evidence_version)))}>
          {ok && <FormField label="Rationale (optional)"><Input value={quickRationale} maxLength={400} placeholder={QUICK_RATIONALE} onChange={(event) => setQuickRationale(event.target.value)} /></FormField>}
          {quickError && <p role="alert" className="text-[var(--error)]">{quickError}</p>}
          {assignments.map((row) => (
            <AssignmentReviewRow key={row.id} user={user} context={context} row={row} description={context==='current'?describe(row.catalogue_roles):undefined} ok={ok} checked={picked.assignment.includes(row.id)} onCheck={() => pick('assignment', row.id)} pendingAction={quickBusy.get(row.id)}
              onDecide={(decision) => quickDecide(row, decision)} onOpenRole={() => change({ detailRole: row.catalogue_roles[0] || row.role })}
              onTrack={row.decision === 'Removal required' ? () => setAction({ assignment: { id: row.id, role: row.role, valid_from: row.valid_from, valid_to: row.valid_to, user_group: row.user_group, interval_status: row.interval_status, tcodes: [], other_activities: row.activities, risks: row.risks, catalogue_roles: row.catalogue_roles, evidence_version: row.evidence_version, decision: row.decision, event: row.event } }) : undefined}
              history={<DecisionHistory kind="assignment" context={context} keyId={row.id} label="Assignment review history" />} transactions={tcodesOf.get(row.id) || []} />
          ))}
        </ReviewSection>

</div>
        <div role="tabpanel" id={`${tabId}-panel-activity`} aria-labelledby={`${tabId}-activity`} hidden={reviewTab!=='activity'}>        <ReviewSection title="Activity Review" kind="activity" done={progressOf(activities)} total={activities.length} ok={ok} picked={picked.activity} keys={activities.map((row) => row.key)} onPickAll={(keys) => setPicked((previous) => ({ ...previous, activity: keys }))}
          onBatch={() => batch('activity', `Batch activity review (${picked.activity.length})`, activities.filter((row) => picked.activity.includes(row.key)).map((row) => item(row.key, row.activity, row.evidence_version)))}>
          {activities.map((row) => (
            <ReviewRow key={row.key} focused={focus(row.activity, 'activity')} label={row.activity} checked={picked.activity.includes(row.key)} onCheck={ok ? () => pick('activity', row.key) : undefined}
              compact title={<SodPill kind="activity" value={row.activity} />} summary={<><span className="id-pill-list" aria-label={`Risks supplied by ${row.activity}`}>{row.risks.map(risk => <SodPill key={risk} kind="risk" value={risk} />)}</span><StatusBadge tone={row.duplicate_coverage ? 'info' : 'neutral'}><span title={row.duplicate_coverage ? 'Several role assignments supply this activity' : 'Role assignments supplying this activity'}>{row.roles} role assignment{row.roles === 1 ? '' : 's'}{row.duplicate_coverage ? ' · overlapping' : ''}</span></StatusBadge></>} event={row.event} decisionDetails={<SodDecisionStatus kind="activity" label={row.activity} status={row.decision} summary={row.decision_summary} event={row.event} coverage={row.review_coverage} user={user} context={context} activities={[row.activity]} risks={row.risks} roles={allAssignments.filter(assignment=>assignment.activities.includes(row.activity))}/>}
              actions={ok && <IconButton label={`Review activity ${row.activity}`} tooltip="Record an activity review" variant={row.decision === 'Pending' ? 'primary' : 'secondary'} onClick={() => setForm({ kind: 'activity', heading: `Activity review · ${row.activity}`, items: [item(row.key, row.activity, row.evidence_version)] })}><ClipboardCheck size={16} aria-hidden="true" /></IconButton>}
              history={<DecisionHistory kind="activity" context={context} keyId={row.key} label="Activity review history" />} />
          ))}
        </ReviewSection>

</div>
        <div role="tabpanel" id={`${tabId}-panel-risk`} aria-labelledby={`${tabId}-risk`} hidden={reviewTab!=='risk'}>
         <ReviewSection title="Risk Review" kind="risk" done={progressOf(risks)} total={risks.length} ok={ok} picked={picked.risk} keys={risks.map(row=>row.finding_id)} onPickAll={keys=>setPicked(previous=>({...previous,risk:keys}))}
          note="Normal risk approval is separate from formal acceptance. Remove requires remediation planning; no role is removed automatically."
          onBatch={()=>batch('risk',`Batch risk review (${picked.risk.length})`,risks.filter(row=>picked.risk.includes(row.finding_id)).map(row=>item(row.finding_id,row.risk_id,row.evidence_version)))}>
          {risks.map(row=><ReviewRow key={row.finding_id} focused={focus(row.risk_id,'risk')} label={row.risk_id} checked={picked.risk.includes(row.finding_id)} onCheck={ok?()=>pick('risk',row.finding_id):undefined}
            title={<SodPill kind="risk" value={row.risk_id}/>} meta={row.display_name||row.source_text||'No description in the SoD matrix'} event={row.risk_review_event||null}
            decisionDetails={<SodDecisionStatus kind="risk" label={row.risk_id} status={row.risk_review||'Pending'} summary={row.risk_review_summary} event={row.risk_review_event||null} coverage={row.review_coverage} user={user} context={context} name={row.display_name} activities={allActivities.filter(activity=>activity.risks.includes(row.risk_id)).map(activity=>activity.activity)} roles={allAssignments.filter(assignment=>assignment.risks.includes(row.risk_id))} formalAcceptance={{status:row.acceptance,event:row.event}}/>}
            actions={ok&&<><Button onClick={()=>setForm({kind:'risk',heading:`Risk review · ${row.risk_id}`,items:[item(row.finding_id,row.risk_id,row.evidence_version)]})} aria-label={`Review risk ${row.risk_id}`}><ClipboardCheck size={16} aria-hidden="true"/>Review</Button><IconButton variant="ghost" tooltip="Formal acceptance (separate approval)" onClick={()=>setForm({kind:'acceptance',heading:`Risk acceptance · ${row.risk_id}`,items:[item(row.finding_id,row.risk_id,row.evidence_version)]})} label={`Decide risk acceptance ${row.risk_id}`}><ShieldCheck size={16} aria-hidden="true"/></IconButton></>}
            history={<><DecisionHistory kind="risk" context={context} keyId={row.finding_id} label="Risk review history"/><DecisionHistory kind="acceptance" context={context} keyId={row.finding_id} label="Risk acceptance history"/></>}/>) }
         </ReviewSection>
         {ok&&!!picked.risk.length&&<Button variant="secondary" onClick={()=>batch('acceptance',`Batch risk acceptance (${picked.risk.length})`,risks.filter(row=>picked.risk.includes(row.finding_id)).map(row=>item(row.finding_id,row.risk_id,row.evidence_version)))}>Formal acceptance for selected risks ({picked.risk.length})</Button>}
        </div>
        {!!data.risk?.legacy_decisions.length && <AlertNote>{data.risk.legacy_decisions.length} legacy risk decision(s) recorded before activity-level review are retained as history and were not converted to a risk acceptance.</AlertNote>}

        {total === 0 && <EmptyState>No conflict-relevant evidence for this user.</EmptyState>}

        <details className="sod-section" aria-label="Supporting evidence" open={!!(risk || activity)}>
          <summary><h3 className="inline">Supporting evidence and removal impact</h3></summary>
          {data.activities.map((row) => <ActivityBlock key={row.key} row={row} selection={selection} toggle={toggle} impact={data.impact?.per_assignment || {}} onRole={(name) => change({ detailRole: name })} />)}
          {data.impact && <section className="sod-section" aria-label="Remediation impact">
            <h3><Wrench size={14} className="mr-1 inline" aria-hidden="true" />Remediation impact</h3>
            <p className="ui-description">Several remediation options can be valid. This is a what-if over a copy of the evidence; it never changes SAP or imported data, and a removal recommendation is not confirmed removal.</p>
            {data.impact.options.map((option) => (
              <Card key={option.slot}>
                <p><strong>{option.slot === 'ACTVT1' ? 'Activity 1' : 'Activity 2'} ({option.activities.join(', ')})</strong>: remove all {option.assignments.length} supplying assignment(s) (<RoleCodeList roles={option.roles} />) to {option.resolves_risk ? 'resolve this risk' : 'reduce evidence'}{option.also_resolves?.length ? `; also resolves ${option.also_resolves.join(', ')}` : ''}</p>
                {option.warnings.map((warning) => <AlertNote key={warning}>{warning}</AlertNote>)}
                <Button onClick={() => { setSelection(option.assignments); void simulate(option.assignments) }}><FlaskConical size={16} aria-hidden="true" />Simulate this option</Button>
              </Card>
            ))}
          </section>}
          <section className="sod-section" aria-label="What-if simulation">
            <h3><FlaskConical size={14} className="mr-1 inline" aria-hidden="true" />What-if removal</h3>
            <p className="ui-description">{selection.length ? `${selection.length} assignment(s) selected.` : 'Select role assignments above to simulate removing them.'}</p>
            <Button disabled={!selection.length} onClick={() => void simulate(selection)}>Simulate removal</Button>
            {error && <p role="alert">{error}</p>}
            {simulation && <Card aria-label="Simulation result">
              <p>Before: {simulation.before.join(', ') || 'none'} · After: {simulation.after.join(', ') || 'none'}</p>
              <p>Resolved by this change: {simulation.resolved.join(', ') || 'none'}{simulation.eliminates_all ? ' (all detected risks for this user)' : ''}</p>
              <p>Activities no longer supplied: {simulation.lost_activities.join(', ') || 'none'}</p>
              {simulation.warnings.map((warning) => <AlertNote key={warning}>{warning}</AlertNote>)}
            </Card>}
          </section>
          {data.related_risks.length > 0 && <p className="ui-description">Related risks for this user: {data.related_risks.join(', ')}</p>}
        </details>
      </>}
      {action && data && <ActionDialog context={context} revision={data.revision} user={user} assignment={action.assignment} risk={risk} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await invalidateSod(qc) }} />}
      {data&&<p className="text-xs" role="status">{done} of {total} reviews completed · evaluation {formatDate(data.as_of)}</p>}
    </>
  )
}

function ReviewSection({ title, kind, done, total, ok, picked, keys, onPickAll, note, onBatch, children }: { title: string; kind: Kind; done: number; total: number; ok: boolean; picked: string[]; keys: string[]; onPickAll: (keys: string[]) => void; note?: string; onBatch: () => void; children: ReactNode }) {
  return (
    <section className="sod-section sod-review-section" aria-label={title} data-kind={kind}>
      <Toolbar><h3>{title}</h3><StatusBadge tone={total > 0 && done === total ? 'success' : 'neutral'}>{done}/{total} reviewed</StatusBadge>
        {ok && keys.length > 1 && <Checkbox checked={picked.length === keys.length} onChange={(event) => onPickAll(event.target.checked ? keys : [])} aria-label={`Select all visible in ${title}`}>Select all visible</Checkbox>}
        {ok && picked.length > 0 && <Button variant="primary" onClick={onBatch}>Review selected ({picked.length})</Button>}</Toolbar>
      {note && <p className="ui-description">{note}</p>}
      {total === 0 ? <p className="ui-description">Nothing to review in this section.</p> : <ul className="sod-review-list" aria-label={`${title} items`}>{children}</ul>}
    </section>
  )
}

/** Collapsed: checkbox, copyable role, review status, icon decisions and an expand control. Expanded: transactions and activities, SAP User Group, validity, history and further actions. */
function AssignmentReviewRow({ user,context,row, description, ok, checked, onCheck, pendingAction, onDecide, onOpenRole, onTrack, history, transactions }: { user:string;context:string;row: OverviewAssignment; description?: string; ok: boolean; checked: boolean; onCheck: () => void; pendingAction?: string; onDecide: (decision: 'Keep' | 'Remove' | 'Investigate') => void; onOpenRole: () => void; onTrack?: () => void; history: ReactNode; transactions: string[] }) {
  const busy=!!pendingAction
  const [open, setOpen] = useState(false), kept = row.decision === 'Keep', removed = row.decision === 'Removal required', investigating = row.decision === 'Investigate'
  const detailId = useId()
  return (
    <li data-assignment-id={row.id} className="sod-review-row sod-assignment-row" data-expanded={open || undefined}>
      <div className="sod-assignment-compact">
        {ok && <Checkbox checked={checked} onChange={onCheck} aria-label={`Select ${row.role}`}><span className="sr-only">Select</span></Checkbox>}
        <div className="sod-assignment-role"><RoleIdentifier value={row.role} onOpen={onOpenRole} openLabel={`Open catalogue role ${row.catalogue_roles[0] || row.role}`} />{description && <p className="sod-assignment-description" title={description}>{description}</p>}</div>
        <SodDecisionStatus kind="assignment" label={row.role} status={row.decision} summary={row.decision_summary} event={row.event} coverage={row.review_coverage} user={user} context={context} assignmentId={row.id} validFrom={row.valid_from} validTo={row.valid_to} verification={row.remediation_verification} activities={row.activities} risks={row.risks} name={description}/>
        {ok && <span className="sod-decision-icons" role="group" aria-label={`Decision for ${row.role}`}>
          <IconButton label={`Keep ${row.role}`} tooltip="Keep this role assignment" variant={kept ? 'primary' : 'secondary'} aria-pressed={kept} loading={pendingAction==='Keep'} disabled={busy} onClick={() => onDecide('Keep')}><Check size={16} aria-hidden="true" /></IconButton>
          <IconButton label={`Investigate ${row.role}`} tooltip="Mark for further investigation (not a final decision)" variant={investigating ? 'primary' : 'secondary'} aria-pressed={investigating} loading={pendingAction==='Investigate'} disabled={busy} onClick={() => onDecide('Investigate')}><Search size={16} aria-hidden="true" /></IconButton>
          <IconButton label={`Remove ${row.role}`} tooltip="Recommend removing this role assignment (no change in SAP)" variant={removed ? 'destructive' : 'secondary'} aria-pressed={removed} loading={pendingAction==='Remove'} disabled={busy} onClick={() => onDecide('Remove')}><Trash2 size={16} aria-hidden="true" /></IconButton>
        </span>}
        <IconButton label={`${open ? 'Hide' : 'Show'} details for ${row.role}`} tooltip={open ? 'Hide evidence' : 'Show evidence'} variant="ghost" aria-expanded={open} aria-controls={detailId} onClick={() => setOpen(!open)}><DisclosureChevron open={open} /></IconButton>
      </div>
      {open && <div id={detailId} className="sod-assignment-details" role="group" aria-label={`Evidence for ${row.role}`}>
        <dl className="validity-dates">
          <div><dt>SAP User Group</dt><dd>{row.user_group || 'Unknown'}</dd></div>
          <div><dt>Validity</dt><dd>{row.interval_status && <AssignmentStatus value={row.interval_status} />} {formatDate(row.valid_from)} to {formatDate(row.valid_to)}</dd></div>
          <div><dt>Activities</dt><dd><span className="id-pill-list" aria-label={`Activities supplied by ${row.role}`}>{row.activities.map((name) => <SodPill key={name} kind="activity" value={name} />)}</span></dd></div>
          <div><dt>Risks</dt><dd><span className="id-pill-list">{row.risks.map((name) => <SodPill key={name} kind="risk" value={name} />)}</span></dd></div>
          {!!transactions.length && <div><dt>Transactions</dt><dd className="sod-assignment-tcodes">{transactions.join(', ')}</dd></div>}
        </dl>
        {row.event && <p className="text-xs text-muted">{row.event.decision === 'Remove' ? 'Removal recommended' : row.event.decision === 'Investigate' ? 'Marked for investigation' : row.event.decision} by {row.event.reviewer}, {formatTimestamp(row.event.timestamp)}: {row.event.justification}</p>}
        {onTrack && <div className="ui-toolbar"><Button size="compact" onClick={onTrack}>Track action</Button></div>}
        {history}
      </div>}
    </li>
  )
}

/** Compact rows keep identity, status, coverage and the decision action on one line; the latest decision text and the history sit behind an expand control. */
function ReviewRow({ label, title, meta, summary, compact, event, decisionDetails, actions, history, checked, onCheck, focused }: {
  label: string; title: ReactNode; meta?: ReactNode; summary?: ReactNode; compact?: boolean; decisionDetails:ReactNode; event: DecisionEvent | null; actions?: ReactNode; history: ReactNode; checked: boolean; onCheck?: () => void; focused?: boolean
}) {
  const [open, setOpen] = useState(false), detailId = useId()
  return (
    <li className="sod-review-row" data-focused={focused || undefined} data-compact={compact || undefined}>
      {/* Primary row: select, identifier, status and the decision action at the right edge; the description and the expandable history sit below it. */}
      <div className="sod-review-compact">
        {onCheck && <Checkbox checked={checked} onChange={onCheck} aria-label={`Select ${label}`}><span className="sr-only">Select</span></Checkbox>}
        <span className="min-w-0">{title}</span>
        {decisionDetails}
        <span className="sod-review-summary">{summary}</span>
        <div className="sod-review-actions sod-review-compact-actions">
          {actions}
          <IconButton label={`${open ? 'Hide' : 'Show'} details for ${label}`} tooltip={open ? 'Hide evidence and history' : 'Show evidence and history'} variant="ghost" aria-expanded={open} aria-controls={detailId} onClick={() => setOpen(!open)}><DisclosureChevron open={open} /></IconButton>
        </div>
      </div>
      {!compact && meta && <p className="text-xs text-muted sod-review-description">{meta}</p>}
      {open && <div id={detailId} className="sod-assignment-details" role="group" aria-label={`Evidence for ${label}`}>
        {event ? <p className="text-xs text-muted">{event.decision} by {event.reviewer}, {formatTimestamp(event.timestamp)}: {event.justification}{event.controls ? ` Conditions: ${event.controls}` : ''}</p> : <p className="text-xs text-muted">No decision recorded for this item yet.</p>}
        {history}
      </div>}
    </li>
  )
}

function ActivityBlock({ row, selection, toggle, impact, onRole }: {
  row: ActivityDetail; selection: string[]; toggle: (id: string) => void
  impact: Record<string, { resolves: string[]; remaining: string[]; lost_activities: string[]; affected_approved_activities: string[] }>
  onRole: (role: string) => void
}) {
  return (
    <section className="sod-section" aria-label={`Activity ${row.activity}`}>
      <Toolbar><h3>Activity {row.activity}</h3>{row.duplicate_coverage && <StatusBadge tone="info">Supplied by {row.assignments.length} assignments</StatusBadge>}</Toolbar>
      <p className="ui-description">Transactions: {row.tcodes.join(', ')} · Risks: {row.risks.join(', ')}</p>
      <ul className="grid gap-0" aria-label={`Role assignments supplying ${row.activity}`}>
        {row.assignments.map((assignment) => {
          const effect = impact[assignment.id]
          return (
            <li key={assignment.id} className="ui-list-row grid min-w-0 gap-2 p-3">
              <Toolbar>
                <Checkbox checked={selection.includes(assignment.id)} onChange={() => toggle(assignment.id)} aria-label={`Include ${assignment.role} in what-if removal`}>Simulate</Checkbox>
                <RoleModuleBadge catalogueRoles={assignment.catalogue_roles} />
                <RoleIdentifier value={assignment.role} onOpen={() => onRole(assignment.catalogue_roles[0] || assignment.role)} openLabel={`Open catalogue role ${assignment.catalogue_roles[0] || assignment.role} (evidence)`} />
              </Toolbar>
              <p className="text-xs text-muted">{assignment.user_group || 'No user group'} · {assignment.interval_status && <AssignmentStatus value={assignment.interval_status} />} {formatDate(assignment.valid_from)} → {formatDate(assignment.valid_to)}</p>
              <p className="text-xs">Transactions: {assignment.tcodes.join(', ')} · also supplies: {assignment.other_activities.join(', ') || 'no other relevant activity'} · contributes to {assignment.risks.join(', ')}</p>
              {effect && <p className="text-xs">Removing this alone: {effect.resolves.length ? `resolves ${effect.resolves.join(', ')}` : 'resolves no risk'}; {effect.remaining.length ? `still detected: ${effect.remaining.join(', ')}` : 'no detected risks remain'}.{effect.affected_approved_activities.length ? ` Would affect approved activities: ${effect.affected_approved_activities.join(', ')}.` : ''}</p>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function DecisionHistory({ kind, context, keyId, label }: { kind: Kind; context: string; keyId: string; label: string }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['sod-subject', 'history', kind, context, keyId], queryFn: () => sod<{ items: DecisionEvent[];verification?:RemediationVerification|null }>(`/api/sod/decisions/${kind}/history`, new URLSearchParams({ key: keyId, context })), enabled: open })
  return (
    <details onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer items-center gap-1 text-xs"><History size={12} aria-hidden="true" />{label}</summary>
      {open && (query.isError ? <p role="alert">History unavailable; original storage is retained.</p> : !query.data ? <LoadingState /> : !query.data.items.length ? <p className="text-xs text-muted">No decisions recorded.</p>
        : <>{query.data.verification&&<p className="text-xs">{query.data.verification.status}: {query.data.verification.reason}</p>}<ol className="grid gap-2 py-2">{query.data.items.map((event) => (
          <li key={event.event_id} className="text-xs">
            <LifecycleBadge value={event.decision === 'Remove' ? 'Removal required' : event.decision} /> {event.reviewer}{event.approver ? ` / approver ${event.approver}` : ''} · {formatTimestamp(event.timestamp)}
            <p>{event.justification}</p>
            {event.controls && <p>Conditions or controls: {event.controls}</p>}
            {event.expires && <p>Expires {formatDate(event.expires)}</p>}
            <p className="text-muted">Evidence version {event.evidence_version.slice(0, 12)} retained with this decision.</p>{event.bulk_operation_id&&<p className="text-xs text-muted">Bulk operation {event.bulk_operation_id} · Previous decision: {event.previous_decision||'Unreviewed'}</p>}
          </li>))}</ol></>)}
    </details>
  )
}

export function DecisionForm({ form, subject, sharedReviewer, onCancel, onSaved }: { sharedReviewer?: string; form: FormState; subject: Pick<Subject, 'context' | 'revision' | 'generation'>; onCancel: () => void; onSaved: () => Promise<void> }) {
  const options = OPTIONS[form.kind],
    [decision, setDecision] = useState(form.decision || options[0].value),
    [reviewer, setReviewer] = useState(rememberedReviewer),
    [approver, setApprover] = useState(''),
    [justification, setJustification] = useState(''),
    [controls, setControls] = useState(''),
    [expires, setExpires] = useState(''),
    [error, setError] = useState(''),
    [confirmed, setConfirmed] = useState(form.items.length < 2),
    [busy, setBusy] = useState(false)
  const effectiveReviewer=sharedReviewer??reviewer
  const needsControls = form.kind === 'activity' && decision === 'Conditional' || form.kind === 'acceptance' && decision === 'Accepted'
  const formal = form.kind === 'acceptance' && decision !== 'Pending'
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const date = expires ? parseNorwegianDate(expires) : null
      if (expires && !date) throw Error('Use DD.MM.YYYY for the expiration date.')
      await sodPost(`/api/sod/decisions/${form.kind}`, { context: subject.context, expected_revision: subject.revision, expected_generation: subject.generation, items: form.items, decision, reviewer: effectiveReviewer, approver, justification, controls, expires: date })
      try { sessionStorage.setItem(reviewerKey, effectiveReviewer) } catch { /* optional convenience */ }
      await onSaved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The decision could not be saved.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="sod-section" aria-label={form.heading}>
      <h3>{form.heading}</h3>
      <p className="ui-description">Names are self-reported, not verified identities or signatures. Every save adds an immutable history event with the evidence it was based on. This does not change SAP or the detected conflict.</p>
      <FormField label={`${KIND_LABEL[form.kind]} decision`}>
        <Select value={decision} onChange={(event) => setDecision(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</Select>
      </FormField>
      {sharedReviewer===undefined&&<FormField label="Reviewer (self-reported)"><Input value={reviewer} maxLength={120} onChange={(event) => setReviewer(event.target.value)} /></FormField>}
      {formal && <FormField label="Approver (must differ from reviewer)"><Input value={approver} maxLength={120} onChange={(event) => setApprover(event.target.value)} /></FormField>}
      <FormField label="Justification"><textarea className="ui-control min-h-20" value={justification} maxLength={4000} onChange={(event) => setJustification(event.target.value)} /></FormField>
      {(needsControls || form.kind === 'acceptance' && formal) && <FormField label={form.kind === 'activity' ? 'Conditions' : 'Compensating controls (optional)'}><textarea className="ui-control min-h-16" value={controls} maxLength={8000} onChange={(event) => setControls(event.target.value)} /></FormField>}
      {form.kind === 'acceptance' && decision === 'Accepted' && <NorwegianDateInput label="Acceptance expires (optional)" value={expires} onChange={setExpires} />}
      {form.items.length > 1 && <Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}>Record this decision for {form.items.length} selected {KIND_LABEL[form.kind].toLowerCase()} items, each with its own history entry</Checkbox>}
      {error && <p role="alert">{error}</p>}
      <Toolbar>
        <Button loading={busy} disabled={!confirmed || !effectiveReviewer.trim() || !justification.trim() || formal && !approver.trim() || form.kind === 'activity' && decision === 'Conditional' && !controls.trim()} onClick={() => void save()}>Save decision</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </Toolbar>
    </section>
  )
}
