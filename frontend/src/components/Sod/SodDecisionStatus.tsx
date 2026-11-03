import type {DecisionSummary,DecisionEvent,ReviewCoverage} from '@/api/sod'
import {Popover} from '@/components/Shared/Popover'
import {StatusBadge} from '@/components/Shared/Presentation'
import {RoleIdentifier} from '@/components/Shared/RoleIdentifier'
import {SodPill,useSodMetadata} from '@/lib/sodAppearance'
import {formatDate,formatTimestamp} from '@/lib/dateFormat'
import {LifecycleBadge} from './SodShared'

/** One decision-first view; authoritative summaries are separate from immutable events and completion. */
export function SodDecisionStatus({kind,label,status,summary,event,coverage,user,context,activities=[],risks=[],roles=[],assignmentId,validFrom,validTo,name}:{
 kind:'assignment'|'activity'|'acceptance';label:string;status:string;summary?:DecisionSummary;event:DecisionEvent|null;coverage?:ReviewCoverage;
 user:string;context:string;activities?:string[];risks?:string[];roles?:{id:string;role:string}[];assignmentId?:string;validFrom?:string|null;validTo?:string|null;name?:string
}) {
 const metadata=useSodMetadata(),formal=kind==='acceptance'
 // An older/missing summary is deliberately conservative: a coverage flag cannot grant approval.
 const shown=summary||{label:formal?'Acceptance pending':coverage?.reviewed?'Decision pending':'Not reviewed',tone:formal||coverage?.reviewed?'warning' as const:'neutral' as const,explicit:false,stale:status==='Outdated',basis:coverage?.provenance||'No current decision',assignment_decisions:{}}
 const display=name||(context==='current'?(kind==='activity'?metadata.activities[label]?.name:formal?metadata.risks[label]?.name:undefined):undefined)
 const title=`Review method for ${label}`
 return <Popover label={title} triggerLabel={title} preferredWidth={440} triggerSize="compact" triggerVariant="ghost" trigger={<StatusBadge tone={shown.tone}>{shown.label}</StatusBadge>}>
  <div className="grid min-w-0 gap-2">
   <div className="flex min-w-0 flex-wrap items-center gap-2">{kind==='assignment'?<RoleIdentifier value={label}/>:<SodPill kind={formal?'risk':'activity'} value={label} details={false}/>}<StatusBadge tone={shown.tone}>{shown.label}</StatusBadge></div>
   {display&&<p className="text-sm font-semibold break-words">{display}</p>}
   <dl className="grid min-w-0 gap-2 text-xs">
    <Meta label="SAP user" value={user}/><Meta label="Review period" value={context==='current'?'Current dataset':context}/>
    <Meta label={formal?'Formal acceptance':'Access decision'} value={shown.label}/>
    <Meta label="Review completion" value={coverage?.reviewed?'Reviewed':'Not reviewed'}/>
    <Meta label="Review method" value={shown.basis}/>
    <Meta label="Decision basis" value={shown.explicit?'Explicit':shown.stale?'Previous evidence':'Coverage only; no explicit decision'}/>
    <Meta label="Evidence status" value={shown.stale?'Needs review':status==='Pending'?'No current decision':'Current evidence'}/>
    {event&&<><Meta label={shown.stale?'Previous reviewer':'Reviewer'} value={event.reviewer}/><Meta label="Recorded" value={formatTimestamp(event.timestamp)}/>
     {formal&&<><Meta label="Approver" value={event.approver}/><Meta label="Justification" value={event.justification}/><Meta label="Controls" value={event.controls}/></>}</>}
    {assignmentId&&<><Meta label="Assignment ID" value={assignmentId}/><Meta label="Validity" value={`${formatDate(validFrom)} → ${formatDate(validTo)}`}/></>}
   </dl>
   {!!Object.keys(shown.assignment_decisions).length&&<section aria-label="Supporting assignment decisions"><h4 className="text-xs font-semibold">Supporting assignment decisions</h4><div className="flex flex-wrap gap-2">{Object.entries(shown.assignment_decisions).map(([decision,count])=><span key={decision} className="inline-flex items-center gap-1 text-xs"><LifecycleBadge value={decision}/>{count} assignment{count===1?'':'s'}</span>)}</div></section>}
   {!!activities.length&&<section aria-label="Related activities"><h4 className="text-xs font-semibold">Related activities</h4><span className="id-pill-list">{activities.map(id=><SodPill key={id} kind="activity" value={id} details={false}/>)}</span></section>}
   {!!risks.length&&<section aria-label="Related risks"><h4 className="text-xs font-semibold">Related risks</h4><span className="id-pill-list">{risks.map(id=><SodPill key={id} kind="risk" value={id} details={false}/>)}</span></section>}
   {!!roles.length&&<section aria-label="Related assignments"><h4 className="text-xs font-semibold">Related assignments</h4><div className="flex flex-wrap gap-1">{roles.slice(0,8).map(row=><RoleIdentifier key={row.id} value={row.role}/>)}</div>{roles.length>8&&<p className="text-xs text-muted">{roles.length-8} additional assignments are available in Roles.</p>}</section>}
   {formal&&<p className="text-xs text-muted">Access review coverage does not grant formal acceptance. Acceptance never changes detected conflicts.</p>}
   {coverage?.removal_planned&&<p className="text-xs text-muted">Removal planned; this is not verified remediation.</p>}
  </div>
 </Popover>
}
function Meta({label,value}:{label:string;value?:string|null}){return value?<div className="grid min-w-0 grid-cols-[minmax(6rem,1fr)_minmax(0,2fr)] gap-2"><dt className="text-muted">{label}</dt><dd className="min-w-0 break-words">{value}</dd></div>:null}
