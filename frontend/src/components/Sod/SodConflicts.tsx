import {useEffect,useRef,useState} from 'react'
import { userHref } from '@/hooks/useViewHistory'
import { announceExport } from '@/lib/exportNotice'
import {useQuery} from '@tanstack/react-query'
import {Eye} from 'lucide-react'
import {apiRequest,applicationToken,fetchRoles} from '@/api/client'
import {useHistoryValue,useViewHistory,type SodFilterState} from '@/hooks/useViewHistory'
import {Card,DataTable,Toolbar,StatusBadge,LoadingState,EmptyState,EvidenceDisclosure} from '@/components/Shared/Presentation'
import {Button} from '@/components/Shared/Button'
import {FormField} from '@/components/Shared/Controls'
import {Combobox} from '@/components/Shared/Combobox'
import {FilterChip} from '@/components/Shared/FilterChip'
import {ExportCSVButton} from '@/components/Shared/ExportCSVButton'
import {RoleIdentifier} from '@/components/Shared/RoleIdentifier'
import {Dialog} from '@/components/Shared/Dialog'
import {AssignmentStatus} from '@/components/Shared/InvestigationNavigation'
import {AccountStatus} from '@/components/Shared/AccountStatus'
import {Pagination} from '@/components/Access/Shared'
import {formatDate} from '@/lib/dateFormat'
import {NorwegianDateInput,parseNorwegianDate} from '@/components/Shared/NorwegianDateInput'
import {RoleEntry} from '@/components/Shared/RoleEntry'
import {moduleOfRoles,useRoleModules} from '@/hooks/useRoleModules'
import {SodFilters,type FilterField} from './SodShared'
import {SodPill} from '@/lib/sodAppearance'
import {FilterSection} from '@/components/Shared/FilterLayout'
import type {Filters} from '@/api/sod'

type Evidence={actual_assigned_role?:string;matched_catalogue_pattern:string;matching_status?:string;single_role:string;assignment_kind:string;tcode:string;matrix_transaction:string;source_provenance:Record<string,string|null>[];activity_slot:string;activity:string;role_valid_from?:string;role_valid_to?:string;interval_status?:string;user_group?:string}
type Finding={finding_id:string;subject:string|string[];kind:'user'|'role'|'role_combination';risk_id:string;criticality:string;evaluation_policy:string;evidence:Record<'ACTVT1'|'ACTVT2',Evidence[]>;evidence_total:Record<'ACTVT1'|'ACTVT2',number>;current_potential:boolean;account:{accounts:{locked:boolean|null;valid_from?:string;valid_to?:string}[];directory_match:string;ad_status:string;sap_validity?:string;lock_status?:string}|null;evidence_version:string;risk:{display_name:string;source_text:string;business_category:string;risk_type:string}}
type Result={items:Finding[];total:number;offset:number;limit:number;generation:string;as_of:string;summary:{unfiltered:Record<string,number>;filtered:{findings:number;subjects:number}};coverage:{status:string;reason:string|null;eligible_assignment_records:number;mapped_assignment_records:number;unmapped_assignment_records:number;roles_available:boolean;supported_risks:number};methodology:{policy:string;evidence:string;historical:string;role_validity:string};sources:Record<string,unknown>}
const initial:SodFilterState={search:'',risk:'',criticality:'',risk_type:'',category:'',username:'',group:'',composite_role:'',single_role:'',tcode:'',account_status:'',sort:'subject',descending:false,validity:'active',as_of:'',selected_roles:[]}
const text=(state:SodFilterState,key:string)=>typeof state[key]==='string'?state[key] as string:''
function parameters(kind:string,state:SodFilterState){const params=new URLSearchParams({kind});for(const [key,value]of Object.entries(state)){if(Array.isArray(value))value.forEach(item=>params.append(key,item));else if(value!==''&&value!==undefined)params.set(key,String(value))}return params}

/** Catalogue role and role-combination conflicts; user-level investigation moved to the matrices and Access Explorer. */
export function ConflictView({kind}:{kind:'users'|'roles'}){
 const [historyFilters,setHistoryFilters]=useHistoryValue('sodFilters'),{change}=useViewHistory(),filters={...initial,...historyFilters?.[kind]},[offset,setOffset]=useState(0),[active,setActive]=useState<Finding|null>(null),[roleSearch,setRoleSearch]=useState(''),[busy,setBusy]=useState(false),[,setMessage]=useState(''),[,setFailed]=useState(false),[dateText,setDateText]=useState(formatDate(text(filters,'as_of'),'')),[dateError,setDateError]=useState(false)
 const controller=useRef<AbortController|null>(null),query=parameters(kind,filters),key=query.toString(),current=useRef(key);current.current=key
 const setFilters=(value:SodFilterState)=>{setOffset(0);setHistoryFilters(previous=>({...previous,[kind]:value}))}
 const update=(name:string,value:string|boolean|string[])=>setFilters({...filters,[name]:value})
 const result=useQuery({queryKey:['sod-analysis',key,offset],queryFn:()=>apiRequest<Result>(`/api/sod/analysis?${query}&offset=${offset}&limit=25`)})
 const roles=useQuery({queryKey:['sod-role-options',roleSearch],queryFn:()=>fetchRoles(undefined,roleSearch),enabled:kind==='roles'})
 const generation=result.data?.generation,currentGeneration=useRef(generation);currentGeneration.current=generation
 useEffect(()=>{setMessage('');return()=>controller.current?.abort()},[key,generation])
 useEffect(()=>setDateText(formatDate(text(filters,'as_of'),'')),[filters.as_of])
 const selectedRoles=Array.isArray(filters.selected_roles)?filters.selected_roles:[]
 const exportCsv=async()=>{
  if(controller.current||!result.data)return;const request=new AbortController(),started=key,captured=result.data;controller.current=request;setBusy(true);setMessage('');setFailed(false)
  try{
   const exportQuery=new URLSearchParams(query);exportQuery.set('expected_generation',captured.generation);const response=await fetch(`/api/sod/analysis/export?${exportQuery}`,{headers:{'X-SAP-Lens':applicationToken()},cache:'no-store',signal:request.signal});if(!response.ok)throw Error('SoD export failed. Refresh the source and retry.')
   if(response.headers.get('X-SAP-Lens-Data-Generation')!==captured.generation)throw Error('Source evidence changed. Refresh before exporting.')
   const filename=response.headers.get('Content-Disposition')?.match(/filename="(sap-lens-sod-(?:users|roles)-findings-\d{4}-\d{2}-\d{2}\.csv)"/)?.[1];if(!filename||!response.headers.get('Content-Type')?.startsWith('text/csv'))throw Error('Invalid SoD export response.')
   const reader=response.body?.getReader();if(!reader)throw Error('Export stream unavailable.');const parts:string[]=[],decoder=new TextDecoder('utf-8',{fatal:true});let bytes=0
   try{while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>32*1024*1024){await reader.cancel();throw Error('Export exceeds 32 MiB. Narrow the filters.')}parts.push(decoder.decode(value,{stream:true}))}parts.push(decoder.decode())}finally{reader.releaseLock()}
   if(current.current!==started||currentGeneration.current!==captured.generation||request.signal.aborted)throw Error('Export cancelled because filters or evidence changed.')
   const content='\ufeff'+parts.join('').replace(/^\ufeff/,'');let saved=true
   if(window.pywebview){if(!window.pywebview.api.save_sod_csv)throw Error('Update the desktop application for SoD CSV export.');saved=await window.pywebview.api.save_sod_csv(applicationToken(),filename,content)}else{const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
   announceExport(saved?{kind:'success',message:`${captured.total} findings exported with supporting evidence.`}:{kind:'info',message:'Export cancelled.'})
  }catch(cause){setFailed(true);announceExport({kind:'error',message:request.signal.aborted?'Export cancelled because the view changed.':cause instanceof Error?cause.message:'Export failed.'})}finally{if(controller.current===request){controller.current=null;setBusy(false)}}
 }
 const openUser=(username:string)=>change({page:'users',accessMode:'directory',user:username,userContext:{},detailRole:null,settings:false})
 const openRole=(name:string)=>change({detailRole:name})
 return <section className="grid min-w-0 gap-4" aria-label={kind==='users'?'SoD user conflicts':'SoD role conflicts'}>
  <EvidenceDisclosure title="About potential SoD conflicts">Both required activity sides must have transaction-derived role evidence. This is not proof of effective SAP authorization or actual transaction use. Account state is separate from assignment evidence. All-validity results do not prove concurrent historical access. Role coverage has no assignment validity.</EvidenceDisclosure>
  <SodFilters view={`sod_${kind}`} filters={filters as Filters} setFilters={value=>setFilters(value as SodFilterState)} defaults={initial as Filters} searchLabel="Search SoD findings" onReset={()=>setDateError(false)}
   fields={['risk','criticality','risk_type','category','composite_role','single_role','tcode',...(kind==='users'?['username','group','account_status','validity'] as FilterField[]:[])]}
   sorts={[{value:'subject',label:'Subject'},{value:'risk_id',label:'Risk ID'},{value:'criticality',label:'Source Criticality'},{value:'evidence_count',label:'Evidence Count'}]}
   actions={<ExportCSVButton loading={busy} disabled={!result.data?.total||result.isFetching||dateError} onClick={()=>void exportCsv()} title="Exports every filtered finding and all supporting evidence, across pages."/>}
   extra={<>
    {kind==='roles'&&<FilterSection title="Role combination"><FormField label="Add catalogue role to combination"><Combobox label="Add catalogue role to combination" value="" options={(roles.data||[]).map(role=>role.agr_name).filter(name=>!selectedRoles.includes(name))} onSearch={setRoleSearch} onChange={name=>{if(name&&selectedRoles.length<25)update('selected_roles',[...selectedRoles,name])}} allowCustom={false} loading={roles.isFetching} disabled={selectedRoles.length>=25}/></FormField>
     {!!selectedRoles.length&&<Toolbar aria-label="Selected role combination">{selectedRoles.map(name=><FilterChip key={name} removeLabel={`Remove combination role ${name}`} onRemove={()=>update('selected_roles',selectedRoles.filter(value=>value!==name))}>{name}</FilterChip>)}<p className="ui-description">Selected combinations are evaluated in addition to individual roles.</p></Toolbar>}</FilterSection>}
    <FilterSection title="Evaluation"><NorwegianDateInput label="Evaluation date" value={dateText} onChange={value=>{setDateText(value);const parsed=parseNorwegianDate(value);setDateError(parsed===null);if(parsed!==null)update('as_of',parsed)}}/>{dateError&&<p role="alert">Enter an evaluation date as DD.MM.YYYY, or clear it to use today.</p>}</FilterSection>
   </>}>
  {result.isError?<p role="alert">{result.error instanceof Error?result.error.message:'SoD findings are unavailable.'}</p>:!result.data?<LoadingState/>:<>{(kind==='users'&&result.data.coverage.status!=='available'||kind==='roles'&&!result.data.coverage.roles_available||!result.data.coverage.supported_risks)&&<Card><StatusBadge>Analysis unavailable or incomplete</StatusBadge><p>{kind==='users'&&result.data.coverage.reason==='mapping_disabled'?'User–Role Mapping is disabled. Re-enable it in Features to analyze retained assignment evidence.':'A supported SoD matrix and validated role catalogue are required; user analysis also requires User–Role Mapping data.'}</p><p className="ui-description">Unavailable evidence is not proof that no access or conflict exists.</p><Button onClick={()=>change({settings:true,settingsTarget:result.data?.coverage.reason==='mapping_disabled'?'features':'sod'})}>Review configuration</Button></Card>}
  <Toolbar><h2 className="text-base font-semibold">{result.data.total} potential {kind==='users'?'user':'role'} findings · {result.data.summary.filtered.subjects} subjects</h2></Toolbar><p className="ui-description">Evaluation date: {formatDate(result.data.as_of)} · Policy: {result.data.methodology.policy}{kind==='users'?` · ${result.data.coverage.mapped_assignment_records} / ${result.data.coverage.eligible_assignment_records} eligible assignment records mapped`:''}</p>
  {result.data.items.length?<DataTable caption="Potential SoD findings"><thead><tr><th>{kind==='users'?'SAP User':'Catalogue role / combination'}</th><th>Risk</th><th>Activity evidence</th>{kind==='users'&&<th>Account evidence</th>}<th>Investigation</th></tr></thead><tbody>{result.data.items.map(finding=><tr key={finding.finding_id}><td>{finding.kind==='user'?<RoleIdentifier value={String(finding.subject)} label="SAP username" onOpen={()=>openUser(String(finding.subject))} href={userHref(String(finding.subject))} openLabel={`Open SAP user ${finding.subject}`}/>:<div className="grid gap-2">{(Array.isArray(finding.subject)?finding.subject:[finding.subject]).map(name=><RoleIdentifier key={name} value={name} onOpen={()=>openRole(name)} openLabel={`Open role ${name}`}/>)}{finding.kind==='role_combination'&&<StatusBadge>Selected combination</StatusBadge>}</div>}</td><td><SodPill kind="risk" value={finding.risk_id}/><p>{finding.risk.display_name||finding.risk.source_text}</p></td><td><p>Activity 1: {finding.evidence_total.ACTVT1} paths</p><p>Activity 2: {finding.evidence_total.ACTVT2} paths</p>{kind==='users'&&<StatusBadge tone={finding.current_potential?'warning':'neutral'}>{finding.current_potential?'Potential current conflict':'Historical / unknown assignment evidence'}</StatusBadge>}</td>{kind==='users'&&<td><div className="grid gap-1"><span>SAP <AccountStatus value={finding.account?.sap_validity||'Unknown'}/></span><span>Lock <AccountStatus value={finding.account?.lock_status||'Unknown'} kind="lock"/></span><span>AD <AccountStatus value={finding.account?.ad_status||'Unknown'} kind="ad"/></span></div><p className="text-xs text-muted">Directory: {finding.account?.directory_match.replace(/_/g,' ')||'Unavailable'}</p></td>}<td><Button onClick={()=>setActive(finding)} aria-label={`Inspect SoD evidence ${finding.subject} ${finding.risk_id}`}><Eye size={16} aria-hidden="true"/>Inspect both activities</Button></td></tr>)}</tbody></DataTable>:<EmptyState>No potential conflicts match this scope. Results describe imported evidence only; incomplete source coverage cannot establish absence of access.</EmptyState>}<Pagination label="SoD findings pages" offset={offset} total={result.data.total} limit={result.data.limit} onChange={setOffset}/></>}
  {active&&result.data&&<FindingEvidence finding={active} generation={result.data.generation} query={query} onClose={()=>setActive(null)} onRole={openRole}/>}
 </SodFilters>
</section>
}
function FindingEvidence({finding,generation,query,onClose,onRole}:{finding:Finding;generation:string;query:URLSearchParams;onClose:()=>void;onRole:(role:string)=>void}){
 const subject=Array.isArray(finding.subject)?finding.subject.join(' + '):finding.subject
 return <Dialog title={`Potential SoD evidence · ${finding.risk_id}`} onClose={onClose}><div className="evidence-dialog">
  <ol className="evidence-trace" aria-label="Evidence trace"><li><span>SAP user</span><strong>{subject}</strong></li><li><span>Risk</span><strong>{finding.risk_id}</strong><small>{finding.risk.display_name||finding.risk.source_text}</small></li><li><span>Activities</span><strong>{(['ACTVT1','ACTVT2'] as const).map(side=>finding.evidence[side][0]?.activity).filter(Boolean).join(' + ')}</strong></li><li><span>Then per path</span><strong>Transaction → Role → Assignment</strong></li></ol>
  <p className="ui-description">Actual assigned roles, matched catalogue patterns and transaction provenance are distinct evidence. Both activity sides are shown; this does not establish effective authorization.</p>
  {(['ACTVT1','ACTVT2'] as const).map(side=><EvidenceSide key={side} finding={finding} generation={generation} query={query} side={side} onRole={name=>{onClose();onRole(name)}}/>)}</div></Dialog>
}
function EvidenceRole({entry,onRole}:{entry:Evidence;onRole:(role:string)=>void}){
 const code=moduleOfRoles(useRoleModules(),[entry.matched_catalogue_pattern])
 return <RoleEntry density="compact" moduleCode={code} title={entry.actual_assigned_role?'Assigned role':'Catalogue role'} identifier={entry.actual_assigned_role||entry.matched_catalogue_pattern} identifierLabel={entry.actual_assigned_role?'assigned role':'catalogue role'}>
  {entry.actual_assigned_role&&entry.actual_assigned_role!==entry.matched_catalogue_pattern&&<p className="text-xs text-muted">Matched catalogue role <button type="button" className="text-link" onClick={()=>onRole(entry.matched_catalogue_pattern)} aria-label={`Open catalogue role ${entry.matched_catalogue_pattern}`}>{entry.matched_catalogue_pattern}</button>{entry.matching_status&&<> · {entry.matching_status==='wildcard'?'Wildcard match':'Exact match'}</>}</p>}
  {entry.actual_assigned_role===entry.matched_catalogue_pattern&&<p className="text-xs"><button type="button" className="text-link" onClick={()=>onRole(entry.matched_catalogue_pattern)} aria-label={`Open catalogue role ${entry.matched_catalogue_pattern}`}>Open catalogue role</button>{entry.matching_status&&<> · {entry.matching_status==='wildcard'?'Wildcard match':'Exact match'}</>}</p>}
 </RoleEntry>
}
function EvidenceSide({finding,generation,query,side,onRole}:{finding:Finding;generation:string;query:URLSearchParams;side:'ACTVT1'|'ACTVT2';onRole:(role:string)=>void}){
 const [offset,setOffset]=useState(0),params=new URLSearchParams(query);params.set('finding_id',finding.finding_id);params.set('expected_generation',generation);params.set('side',side);params.set('offset',String(offset));params.set('limit','25')
 const result=useQuery({queryKey:['sod-evidence',params.toString()],queryFn:()=>apiRequest<{items:Evidence[];total:number;limit:number}>(`/api/sod/analysis/evidence?${params}`)})
 return <section className="my-4 grid min-w-0 gap-3" aria-label={`${side} evidence`}><h3>{side==='ACTVT1'?'Activity 1':'Activity 2'} — {finding.evidence[side][0]?.activity}</h3>{result.isError?<p role="alert">{result.error instanceof Error?result.error.message:'Evidence unavailable.'}</p>:!result.data?<LoadingState/>:<><p>{result.data.total} supporting paths</p><DataTable caption={`${side} supporting evidence`} density="compact"><thead><tr><th>Transaction</th><th>Single role</th><th>Assigned role / catalogue pattern</th><th>Assignment validity</th><th>Provenance</th></tr></thead><tbody>{result.data.items.map((entry,index)=><tr key={index}><td><RoleIdentifier value={entry.tcode} label="transaction"/>{entry.matrix_transaction!==entry.tcode&&<p className="text-xs text-muted">Matrix: {entry.matrix_transaction}</p>}</td><td><RoleIdentifier value={entry.single_role}/><p className="text-xs text-muted">{entry.assignment_kind}</p></td><td><EvidenceRole entry={entry} onRole={onRole}/></td><td>{entry.interval_status?<><AssignmentStatus value={entry.interval_status}/><dl className="validity-dates"><div><dt>Valid from</dt><dd>{formatDate(entry.role_valid_from)}</dd></div><div><dt>Valid to</dt><dd>{formatDate(entry.role_valid_to)}</dd></div></dl><p className="text-xs text-muted whitespace-nowrap">SAP User Group: {entry.user_group||'Unavailable'}</p></>:<span className="text-muted">Catalogue mapping · no assignment interval</span>}</td><td><details className="evidence-provenance"><summary>Technical provenance</summary>{entry.source_provenance.map((source,index)=><div key={index} className="mb-2">{Object.entries(source).filter(([,value])=>value).map(([key,value])=><p key={key} className="break-all text-xs"><span className="text-muted">{key}: </span>{value}</p>)}</div>)}</details></td></tr>)}</tbody></DataTable><Pagination label={`${side} evidence pages`} offset={offset} total={result.data.total} limit={result.data.limit} onChange={setOffset}/></>}</section>
}
