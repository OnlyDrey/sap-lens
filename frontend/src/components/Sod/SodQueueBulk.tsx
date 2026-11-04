import {Pagination} from '@/components/Access/Shared'
import {useEffect,useRef,useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {sod,scopeParams,type Filters,type AssignmentPick,type AssignmentSelection,type BulkAction} from '@/api/sod'
import {Dialog} from '@/components/Shared/Dialog'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField,Input} from '@/components/Shared/Controls'
import {Select} from '@/components/Shared/Select'
import {DataTable,ErrorState,LoadingState,StatusBadge,Toolbar} from '@/components/Shared/Presentation'
import {SAPUserLink} from '@/components/Shared/SAPUserLink'
import {RoleIdentifier} from '@/components/Shared/RoleIdentifier'
import {Kpi} from '@/components/Shared/Kpi'
import {PageCheckbox,RowCheckbox} from '@/components/Shared/BulkSelection'
import {bulkSelectionScope,hasPriorReview,selectAssignmentPage,isEligibleAssignment} from '@/lib/sodBulkSelection'
import {SodFilters} from './SodShared'
import {BulkReviewDialog} from './SodBulkReview'

/** Selection is explicit and retained across filters; preview uses canonical assignment selection, never visible-page rows. */
export function SodQueueBulk({context,filters:initial,onClose,embedded=false,onFiltersChange,selectMatching=false,onSelectionConsumed}:{context:string;filters:Filters;onClose:()=>void;embedded?:boolean;selectMatching?:boolean;onSelectionConsumed?:()=>void;onFiltersChange?:(value:Filters)=>void}){
 const [offset,setOffset]=useState(0)
 const [filters,setFilters]=useState<Filters>({...initial,assignment_scope:'all',role_match:initial.role_match||'exact',review_status:'all'}),[selected,setSelected]=useState(new Map<string,AssignmentPick>()),[includeReviewed,setIncludeReviewed]=useState(false),[action,setAction]=useState<BulkAction>('Keep'),[confirm,setConfirm]=useState(false),[notice,setNotice]=useState('')
 const initialKey=JSON.stringify(initial)
 useEffect(()=>{if(embedded){const incoming=JSON.parse(initialKey) as Filters;setFilters({...incoming,assignment_scope:'all',role_match:incoming.role_match||'exact',review_status:'all'})}},[initialKey,embedded])
 const updateFilters=(value:Filters)=>{const next={...value,assignment_scope:'all',role_match:value.role_match||'exact',review_status:'all'};setFilters(next);onFiltersChange?.(next)}
 const version=useRef(''),params=scopeParams(context,filters)
 const result=useQuery({queryKey:['sod-bulk-preview',params.toString()],queryFn:()=>sod<AssignmentSelection>('/api/sod/explorer/access_list/selection',params)})
 const queryKey=params.toString()
 useEffect(()=>setOffset(0),[queryKey])
 const data=result.data,stamp=data?`${context}:${data.generation}:${data.revision}`:''
 useEffect(()=>{if(!stamp)return;if(version.current&&version.current!==stamp){setSelected(new Map());setNotice('Source evidence or decisions changed. Review the preview and select again.')}version.current=stamp},[stamp])
 useEffect(()=>{
  if(!selectMatching||!data||result.isFetching)return
  if(data.truncated)setNotice('The matching scope exceeds the preview limit. Narrow it before selecting all; nothing was selected automatically.')
  else setSelected(new Map(data.items.filter(row=>isEligibleAssignment(row,action,includeReviewed,data.reviewable)).map(row=>[row.key,row])))
  onSelectionConsumed?.()
 },[selectMatching,data,result.isFetching,onSelectionConsumed,action,includeReviewed])
 const toggle=(row:AssignmentPick)=>setSelected(previous=>{const next=new Map(previous);if(next.has(row.key))next.delete(row.key);else next.set(row.key,row);return next})
 const protectedPick=hasPriorReview
 const all=[...selected.values()],selection=bulkSelectionScope(data?.items||[],selected,action,includeReviewed,data?.reviewable??false)
 const eligible=selection.executable,excluded=all.length-eligible.length,outside=selection.outside.length
 const previewRows=data?.items||[],pageRows=previewRows.slice(offset,offset+50),pageEligible=pageRows.filter(row=>isEligibleAssignment(row,action,includeReviewed,data?.reviewable??false))
 const pageSelected=pageEligible.filter(row=>selected.has(row.key)).length
 const summary=[['SAP users',[filters.username,...(Array.isArray(filters.usernames)?filters.usernames:[])]],['SAP User Groups',[filters.group,...(Array.isArray(filters.groups)?filters.groups:[])]],['Roles',[filters.role,...['roles','role_exact','role_families'].flatMap(key=>Array.isArray(filters[key])?filters[key] as string[]:[])]],['Suffixes',[filters.role_suffix,...(Array.isArray(filters.role_suffixes)?filters.role_suffixes:[])]],['Validity',[filters.validity||'active']]].map(([label,values])=>`${label}: ${(values as string[]).filter(Boolean).join(', ')||'All'}`).join(' · ')
 if(confirm&&data)return <BulkReviewDialog scopeSummary={summary} atomic action={action} picks={eligible} info={data} onClose={embedded?()=>setConfirm(false):onClose} onApplied={()=>{if(embedded)setSelected(new Map())}}/>
 return <BulkReviewFrame embedded={embedded} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!data?.reviewable||result.isFetching||result.isError||!eligible.length||eligible.length>1000} onClick={()=>setConfirm(true)}>Continue to confirmation ({eligible.length})</Button></>}>
  <p className="ui-description">All eligible imported assignments are included, including roles without detected SoD conflicts. Select assignments explicitly. Group selections are exact; role matching uses the chosen mode. Decisions are local annotations and do not change SAP.</p>
  <SodFilters view="sod_queue" filters={filters} setFilters={value=>updateFilters({...value,role_match:['exact','prefix','wildcard','search'].includes(String(value.role_match))?value.role_match:'exact',review_status:'all'})} fields={['group','username','role','role_suffix','validity','risk','activity','tcode','category']} extra={<details className="grid gap-2"><summary className="cursor-pointer text-sm">Advanced role matching · {filters.role_match==='search'?'Legacy search':String(filters.role_match)}</summary><FormField label="Role matching mode"><Select value={String(filters.role_match)} onChange={event=>updateFilters({...filters,role_match:event.target.value})}>{filters.role_match==='search'&&<option value="search">Legacy saved search matching</option>}<option value="exact">Exact assigned role names</option><option value="prefix">Role prefixes</option><option value="wildcard">Explicit wildcard role patterns</option></Select></FormField>
  {['prefix','wildcard'].includes(String(filters.role_match))&&<FormField label="Explicit role pattern"><Input value={String(filters.role||'')} placeholder={filters.role_match==='prefix'?'Role prefix':'Anchored wildcard pattern'} onChange={event=>updateFilters({...filters,role:event.target.value})}/></FormField>}</details>}>
   {result.isError?<ErrorState error={result.error} onRetry={()=>void result.refetch()}/>:!data?<LoadingState/>:<>
    <div className="grid grid-cols-3 gap-2" aria-label="Bulk review scope"><Kpi label="Users" value={data.matching_users??new Set(data.items.map(row=>row.user)).size}/><Kpi label="Assignments" value={data.total}/><Kpi label="Eligible" value={data.eligible_counts?.[action][includeReviewed?'include_reviewed':'unreviewed']??data.items.filter(row=>isEligibleAssignment(row,action,includeReviewed,data.reviewable)).length}/></div>
    <Toolbar><span role="status">{new Set(all.map(row=>row.user)).size} selected users · {all.length} selected assignments · {outside} selected outside current filters</span>{selection.matching.length>pageEligible.length&&<Button disabled={data.truncated||result.isFetching} onClick={()=>setSelected(previous=>selectAssignmentPage(previous,selection.matching,true))}>Select all {selection.matching.length} matching eligible assignments</Button>}<Button variant="ghost" disabled={!all.length} onClick={()=>setSelected(new Map())}>Clear assignment selection</Button></Toolbar>
    {!!outside&&<details className="rounded-md border border-line p-2"><summary>{outside} selected outside current filters — excluded from this operation</summary><Button size="compact" onClick={()=>setSelected(previous=>new Map([...previous].filter(([key])=>!selection.outside.some(row=>row.key===key))))}>Clear outside selections</Button><ul>{selection.outside.slice(0,10).map(row=><li key={row.key}>{row.user} · {row.ref}</li>)}</ul>{outside>10&&<p>and {outside-10} more excluded selections</p>}</details>}
    {data.truncated&&<p role="alert">This scope exceeds {data.limit} preview records. Narrow the filters before selecting all; no truncated set is applied automatically.</p>}
    {eligible.length>1000&&<p role="alert">Choose at most 1000 assignments per confirmed operation.</p>}
    {notice&&<p role="status">{notice}</p>}
    <FormField label="Proposed decision"><Select value={action} onChange={event=>setAction(event.target.value as BulkAction)}><option value="Keep">Keep / approve retention</option><option value="Remove">Recommend removal</option><option value="Investigate">Investigate</option></Select></FormField>
    <Checkbox checked={includeReviewed} onChange={event=>setIncludeReviewed(event.target.checked)}>Include previously reviewed assignments</Checkbox>
    <p className="ui-description">{eligible.filter(row=>!protectedPick(row)).length} unreviewed · {all.filter(protectedPick).length} previously reviewed · {eligible.length} proposed updates · {excluded} excluded. Unchanged assignments are not written. Replacing earlier reviews requires an additional confirmation. Current evidence, context and revision are revalidated atomically.</p>
    <DataTable caption="Bulk assignment preview"><thead><tr><th><PageCheckbox label="Select eligible assignments on current page" selected={pageSelected} total={pageEligible.length} onChange={choose=>setSelected(previous=>selectAssignmentPage(previous,pageEligible,choose))}/></th><th>SAP user</th><th>User Group</th><th>Assigned role</th><th>Current</th><th>Proposed</th></tr></thead><tbody>{pageRows.map(row=><tr key={row.key}><td><RowCheckbox disabled={!isEligibleAssignment(row,action,includeReviewed,data.reviewable)} label={`Select bulk assignment ${row.ref} for ${row.user}`} checked={selected.has(row.key)} onChange={()=>{if(isEligibleAssignment(row,action,includeReviewed,data.reviewable))toggle(row)}}/></td><td><SAPUserLink reviewSupported={false} username={row.user}/></td><td>{row.user_group}</td><td><RoleIdentifier value={row.ref}/></td><td>{row.decision}{row.previous_decision&&row.previous_decision!==row.decision&&<small className="block text-secondary">Previous: {row.previous_decision}</small>}</td><td>{!selected.has(row.key)?'Not selected':!includeReviewed&&protectedPick(row)?'Excluded — existing decision':(action==='Remove'&&row.decision==='Removal required'||action===row.decision)?<StatusBadge>Unchanged</StatusBadge>:action==='Remove'?'Removal recommended':action==='Investigate'?'Investigate':'Keep'}</td></tr>)}</tbody></DataTable><Pagination label="Bulk preview pages" offset={offset} total={previewRows.length} limit={50} onChange={setOffset}/><p className="ui-description">Preview pages do not limit explicit selection. Select all matching uses the full server-filtered scope.</p>
   </>}
  </SodFilters>
 </BulkReviewFrame>
}


function BulkReviewFrame({embedded,children,footer,onClose}:{embedded:boolean;children:import('react').ReactNode;footer:import('react').ReactNode;onClose:()=>void}){
 return embedded?<section aria-label="Bulk role assignment review" className="grid min-w-0 gap-3"><h2 className="text-base font-semibold">Bulk role assignment review</h2>{children}<Toolbar>{footer}</Toolbar></section>:<Dialog title="Bulk role assignment review" onClose={onClose} footer={footer}>{children}</Dialog>
}
