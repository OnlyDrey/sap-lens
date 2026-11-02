import {Pagination} from '@/components/Access/Shared'
import {useEffect,useRef,useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {sod,scopeParams,type Filters,type AssignmentPick,type AssignmentSelection,type BulkAction} from '@/api/sod'
import {Dialog} from '@/components/Shared/Dialog'
import {Button} from '@/components/Shared/Button'
import {Checkbox,FormField} from '@/components/Shared/Controls'
import {Select} from '@/components/Shared/Select'
import {DataTable,ErrorState,LoadingState,StatusBadge,Toolbar} from '@/components/Shared/Presentation'
import {SAPUserLink} from '@/components/Shared/SAPUserLink'
import {RoleIdentifier} from '@/components/Shared/RoleIdentifier'
import {SodFilters} from './SodShared'
import {BulkReviewDialog} from './SodBulkReview'

/** Selection is explicit and retained across filters; preview uses canonical assignment selection, never visible-page rows. */
export function SodQueueBulk({context,filters:initial,onClose}:{context:string;filters:Filters;onClose:()=>void}){
 const [offset,setOffset]=useState(0)
 const [filters,setFilters]=useState<Filters>({...initial,role_match:'exact',review_status:'all'}),[selected,setSelected]=useState(new Map<string,AssignmentPick>()),[includeReviewed,setIncludeReviewed]=useState(false),[action,setAction]=useState<BulkAction>('Keep'),[confirm,setConfirm]=useState(false),[notice,setNotice]=useState('')
 const version=useRef(''),params=scopeParams(context,filters)
 const result=useQuery({queryKey:['sod-bulk-preview',params.toString()],queryFn:()=>sod<AssignmentSelection>('/api/sod/explorer/access_list/selection',params)})
 const queryKey=params.toString()
 useEffect(()=>setOffset(0),[queryKey])
 const data=result.data,stamp=data?`${context}:${data.generation}:${data.revision}`:''
 useEffect(()=>{if(!stamp)return;if(version.current&&version.current!==stamp){setSelected(new Map());setNotice('Source evidence or decisions changed. Review the preview and select again.')}version.current=stamp},[stamp])
 const toggle=(row:AssignmentPick)=>setSelected(previous=>{const next=new Map(previous);if(next.has(row.key))next.delete(row.key);else next.set(row.key,row);return next})
 const protectedPick=(row:AssignmentPick)=>row.has_review??['Keep','Removal required'].includes(row.decision)
 const all=[...selected.values()],same=(row:AssignmentPick)=>action==='Keep'&&row.decision==='Keep'||action==='Remove'&&row.decision==='Removal required',eligible=all.filter(row=>(includeReviewed||!protectedPick(row))&&!same(row)),excluded=all.length-eligible.length
 const preview=new Map((data?.items||[]).map(row=>[row.key,row]));for(const row of all)if(!preview.has(row.key))preview.set(row.key,row)
 const previewRows=[...preview.values()]
 if(confirm&&data)return <BulkReviewDialog atomic action={action} picks={eligible} info={data} onClose={onClose} onApplied={()=>{}}/>
 return <Dialog title="Bulk role assignment review" onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!data?.reviewable||result.isFetching||result.isError||!eligible.length||eligible.length>1000} onClick={()=>setConfirm(true)}>Continue to confirmation ({eligible.length})</Button></>}>
  <p className="ui-description">Select assignments explicitly. Group selections are exact; role matching uses the chosen mode. Decisions are local annotations and do not change SAP.</p>
  <FormField label="Role matching mode"><Select value={String(filters.role_match)} onChange={event=>setFilters({...filters,role_match:event.target.value})}><option value="exact">Exact assigned role names</option><option value="prefix">Role prefixes</option><option value="wildcard">Explicit wildcard role patterns</option></Select></FormField>
  <SodFilters view="sod_queue" filters={filters} setFilters={value=>setFilters({...value,role_match:['exact','prefix','wildcard'].includes(String(value.role_match))?value.role_match:'exact',review_status:'all'})} fields={['group','username','role','role_suffix']}>
   {result.isError?<ErrorState error={result.error} onRetry={()=>void result.refetch()}/>:!data?<LoadingState/>:<>
    <Toolbar><span>{data.matching_users??new Set(data.items.map(row=>row.user)).size} matching users · {data.total} matching assignments · {new Set(all.map(row=>row.user)).size} selected users · {all.length} selected assignments</span><Button disabled={data.truncated||result.isFetching} onClick={()=>setSelected(previous=>new Map([...previous,...data.items.map(row=>[row.key,row] as const)]))}>Select all {data.total} matching assignments</Button><Button variant="ghost" onClick={()=>setSelected(new Map())}>Clear assignment selection</Button></Toolbar>
    {data.truncated&&<p role="alert">This scope exceeds {data.limit} preview records. Narrow the filters before selecting all; no truncated set is applied automatically.</p>}
    {eligible.length>1000&&<p role="alert">Choose at most 1000 assignments per confirmed operation.</p>}
    {notice&&<p role="status">{notice}</p>}
    <FormField label="Proposed decision"><Select value={action} onChange={event=>setAction(event.target.value as BulkAction)}><option value="Keep">Keep / approve retention</option><option value="Remove">Recommend removal</option></Select></FormField>
    <Checkbox checked={includeReviewed} onChange={event=>setIncludeReviewed(event.target.checked)}>Include previously reviewed assignments</Checkbox>
    <p className="ui-description">{eligible.filter(row=>!protectedPick(row)).length} unreviewed · {all.filter(protectedPick).length} previously reviewed · {eligible.length} proposed updates · {excluded} excluded. Unchanged assignments are not written. Replacing earlier reviews requires an additional confirmation. Current evidence, context and revision are revalidated atomically.</p>
    <DataTable caption="Bulk assignment preview"><thead><tr><th>Select</th><th>SAP user</th><th>User Group</th><th>Assigned role</th><th>Current</th><th>Proposed</th></tr></thead><tbody>{previewRows.slice(offset,offset+50).map(row=><tr key={row.key}><td><Checkbox aria-label={`Select bulk assignment ${row.ref} for ${row.user}`} checked={selected.has(row.key)} onChange={()=>toggle(row)}><span className="sr-only">Select assignment</span></Checkbox></td><td><SAPUserLink username={row.user}/></td><td>{row.user_group}</td><td><RoleIdentifier value={row.ref}/></td><td>{row.decision}{row.previous_decision&&row.previous_decision!==row.decision&&<small className="block text-secondary">Previous: {row.previous_decision}</small>}</td><td>{!selected.has(row.key)?'Not selected':!includeReviewed&&protectedPick(row)?'Excluded — existing decision':(action==='Remove'&&row.decision==='Removal required'||action===row.decision)?<StatusBadge>Unchanged</StatusBadge>:action==='Remove'?'Removal recommended':'Keep'}</td></tr>)}</tbody></DataTable><Pagination label="Bulk preview pages" offset={offset} total={previewRows.length} limit={50} onChange={setOffset}/><p className="ui-description">Preview pages do not limit explicit selection. Select all matching uses the full server-filtered scope.</p>
   </>}
  </SodFilters>
 </Dialog>
}
