import {ExportCSVButton} from '@/components/Shared/ExportCSVButton'
import {useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Save,ShieldCheck,Database} from 'lucide-react'
import {apiRequest,applicationToken} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {FormField,Input,SearchInput,Checkbox} from '@/components/Shared/Controls'
import {Select} from '@/components/Shared/Select'
import {Card,DataTable,StatusBadge,Toolbar,LoadingState,EmptyState,EvidenceDisclosure} from '@/components/Shared/Presentation'
import {Dialog} from '@/components/Shared/Dialog'
import {ColorPalette} from '@/components/Shared/ColorPalette'
import {IdPill} from '@/components/Shared/IdPill'
import {ContentTabs} from '@/components/Shared/Navigation'
import {Pagination} from '@/components/Access/Shared'
import {formatTimestamp} from '@/lib/dateFormat'

type Metadata={enabled:boolean;display_name:string;business_category:string;notes:string;description_review_status:string;explanation_en:string;explanation_no:string;consequence_en:string;consequence_no:string;mitigating_controls_en:string;mitigating_controls_no:string;review_guidance_en:string;review_guidance_no:string;color:string}
type Mapping={activity:string;tcode:string;ttext:string}
type Risk={risk_id:string;source:{criticality:string;risk_type:string;source_text:string;activity1:string;activity2:string;activities:Record<'ACTVT1'|'ACTVT2',Mapping[]>;supported:boolean;evaluation_policy:string|null};local:Metadata;new:boolean;source_changed:boolean;description_review_status:string;current:boolean;definition_version:string;modified:string|null}
type Catalogue={revision:number;items:Risk[];total:number;offset:number;limit:number;summary:Record<string,number>;source:{loaded:boolean;records:number;risks:number;version:string|null;imported_at:string|null;checked_at:string|null}}
const explanationFields=[['explanation_en','Business explanation',12000],['consequence_en','Risk consequence',8000],['mitigating_controls_en','Mitigating controls',12000],['review_guidance_en','Review guidance',8000]] as const
export function SodRiskSettings({onConfigure}:{onConfigure:()=>void}) {
 const [tab,setTab]=useState('risks')
 return <ContentTabs label="SoD configuration" value={tab} onChange={setTab} items={[{value:'risks',label:'Risks'},{value:'activities',label:'Activities'}]}>{tab==='risks'?<RiskTab onConfigure={onConfigure}/>:<ActivityTab/>}</ContentTabs>
}
function RiskTab({onConfigure}:{onConfigure:()=>void}) {
 const qc=useQueryClient(),[search,setSearch]=useState(''),[enabled,setEnabled]=useState(''),[current,setCurrent]=useState('current'),[status,setStatus]=useState(''),[criticality,setCriticality]=useState(''),[riskType,setRiskType]=useState(''),[category,setCategory]=useState(''),[offset,setOffset]=useState(0),[editing,setEditing]=useState<Risk|null>(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
 const params=new URLSearchParams({search,enabled,current,status,criticality,type:riskType,category,offset:String(offset),limit:'25'})
 const query=useQuery({queryKey:['sod-catalogue',params.toString()],queryFn:()=>apiRequest<Catalogue>(`/api/sod/catalogue?${params}`)})
 const refresh=async()=>{await qc.invalidateQueries({predicate:q=>String(q.queryKey[0]).startsWith('sod')})}
 const bulk=async(value:boolean)=>{
  if(!query.data||(!value&&!window.confirm('Disable all current SoD risks? Historical findings and review data will be preserved.')))return
  setBusy(true);setError('');setMessage('')
  try{const result=await apiRequest<{updated:number}>('/api/sod/catalogue/bulk','POST',{expected_revision:query.data.revision,enabled:value,confirm:!value});await refresh();setMessage(`${result.updated} current risk configurations updated.`)}catch(cause){setError(cause instanceof Error?cause.message:'Risk settings could not be saved.')}finally{setBusy(false)}
 }
 const exportCsv=async()=>{
  setBusy(true);setError('')
  try{const response=await fetch(`/api/sod/catalogue/export?${params}`,{headers:{'X-SAP-Lens':applicationToken()},cache:'no-store'});if(!response.ok)throw Error('Catalogue export failed. Reload and retry.');const content=await response.text(),filename=`sap-lens-sod-catalogue-${new Date().toISOString().slice(0,10)}.csv`;
   if(window.pywebview){if(!window.pywebview.api.save_sod_csv)throw Error('Update the desktop application for catalogue export.');await window.pywebview.api.save_sod_csv(applicationToken(),filename,content)}else{const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  }catch(cause){setError(cause instanceof Error?cause.message:'Catalogue export failed.')}finally{setBusy(false)}
 }
 return <section className="grid min-w-0 gap-4" aria-label="SoD Risk Configuration">
  <Toolbar><ShieldCheck size={20} aria-hidden="true"/><h2>SoD Risk Catalogue</h2><ExportCSVButton loading={busy} disabled={!query.data?.total||query.isFetching} onClick={()=>void exportCsv()} title="All filtered risks, including bilingual guidance and source transaction mappings."/><Button onClick={onConfigure}><Database size={16} aria-hidden="true"/>Configure SoD source</Button></Toolbar>
  <p className="ui-description">Imported risk definitions remain separate from local business guidance. New supported risks are enabled by default and require description review.</p>
  <EvidenceDisclosure title="About SoD evaluation evidence">The explicit sod-two-sided-v1 policy supports structurally complete source TYPE S definitions. Both activity sides are required. Other types remain visible but are not evaluated. Transaction-derived evidence indicates potential conflicts, not verified effective SAP authorization. The source does not include an ACTIVE field.</EvidenceDisclosure>
  {query.data&&<p className="ui-description">{query.data.source.loaded?`${query.data.source.risks} source risks · ${query.data.source.records} mappings`:'No validated SoD matrix loaded'} · Last import: {formatTimestamp(query.data.source.imported_at)} · Last check: {formatTimestamp(query.data.source.checked_at)}</p>}
  <Card aria-label="SoD catalogue filters"><div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
   <FormField label="Search SoD risks"><SearchInput aria-label="Search SoD risks" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0)}} onClear={()=>{setSearch('');setOffset(0)}}/></FormField>
   <FormField label="Risk enablement"><Select value={enabled} onChange={event=>{setEnabled(event.target.value);setOffset(0)}}><option value="">All states</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></Select></FormField>
   <FormField label="Source presence"><Select value={current} onChange={event=>{setCurrent(event.target.value);setOffset(0)}}><option value="current">Current source</option><option value="historical">Historical only</option><option value="">Current and historical</option></Select></FormField>
   <FormField label="Description status"><Select value={status} onChange={event=>{setStatus(event.target.value);setOffset(0)}}><option value="">All statuses</option><option value="new">New</option><option value="changed">Source changed</option><option value="needs_review">Needs description review</option><option value="reviewed">Reviewed</option><option value="unsupported">Unsupported type</option></Select></FormField>
   <FormField label="Source criticality"><Input value={criticality} maxLength={64} placeholder="Exact source value" onChange={event=>{setCriticality(event.target.value);setOffset(0)}}/></FormField>
   <FormField label="Source risk type"><Input value={riskType} maxLength={64} placeholder="Exact source value" onChange={event=>{setRiskType(event.target.value);setOffset(0)}}/></FormField>
   <FormField label="Business area filter"><Input value={category} maxLength={120} placeholder="Exact local category" onChange={event=>{setCategory(event.target.value);setOffset(0)}}/></FormField>
  </div><Toolbar><Button disabled={busy||!query.data?.source.loaded} onClick={()=>void bulk(true)}>Enable all current risks</Button><Button disabled={busy||!query.data?.source.loaded} onClick={()=>void bulk(false)}>Disable all current risks</Button><Button variant="ghost" onClick={()=>{setSearch('');setEnabled('');setCurrent('current');setStatus('');setCriticality('');setRiskType('');setCategory('');setOffset(0)}}>Clear filters</Button></Toolbar></Card>
  {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  {query.isError?<p role="alert">{query.error instanceof Error?query.error.message:'Risk catalogue is unavailable.'}</p>:!query.data?<LoadingState/>:<><p role="status">{query.data.total} matching risks</p>{query.data.total?<DataTable caption="SoD risk configurations" tableClassName="sod-config-table"><thead><tr><th>Risk</th><th>Business area</th><th>Status</th><th>Review</th><th>Modified</th><th>Actions</th></tr></thead><tbody>{query.data.items.map(risk=><tr key={risk.risk_id}><td><IdPill kind="risk" value={risk.risk_id} color={risk.local.color}/><p>{risk.local.display_name||risk.source.source_text}</p><p className="sod-meta">Criticality {risk.source.criticality} · type {risk.source.risk_type}</p></td><td>{risk.local.business_category||'Not specified'}</td><td><StatusBadge tone={risk.local.enabled&&risk.current&&risk.source.supported?'success':'neutral'}>{risk.local.enabled?'Enabled':'Disabled'}</StatusBadge>{!risk.current&&<p className="sod-meta">Historical · excluded from current analysis</p>}{!risk.source.supported&&<p className="sod-meta">Unsupported type · not evaluated</p>}</td><td><StatusBadge tone={risk.description_review_status==='Reviewed'?'success':'warning'}>{risk.description_review_status}</StatusBadge>{risk.new&&<p className="sod-meta">New</p>}{risk.source_changed&&<p className="sod-meta">Source changed</p>}</td><td>{formatTimestamp(risk.modified)}</td><td><Button size="compact" onClick={()=>setEditing(risk)} aria-label={`Edit SoD risk ${risk.risk_id}`}>Edit</Button></td></tr>)}</tbody></DataTable>:<EmptyState>{query.data.source.loaded?'No risks match these filters.':'Configure a SoD matrix source to inspect imported risks and maintain local guidance.'}</EmptyState>}<Pagination label="SoD risk pages" offset={offset} total={query.data.total} limit={query.data.limit} onChange={setOffset}/></>}
  {editing&&query.data&&<RiskEditor risk={editing} revision={query.data.revision} onClose={()=>setEditing(null)} onSaved={async()=>{setEditing(null);setMessage('Risk configuration saved. Imported source values were preserved.');await refresh()}}/>}
 </section>
}
function RiskEditor({risk,revision,onClose,onSaved}:{risk:Risk;revision:number;onClose:()=>void;onSaved:()=>Promise<void>}) {
 const [metadata,setMetadata]=useState<Metadata>({...risk.local,description_review_status:risk.description_review_status}),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const update=(key:keyof Metadata,value:string|boolean)=>setMetadata(previous=>({...previous,[key]:value}))
 // Norwegian text from earlier versions is kept untouched in metadata; only English is edited here.
 const save=async()=>{setBusy(true);setError('');try{await apiRequest(`/api/sod/catalogue/${encodeURIComponent(risk.risk_id)}`,'POST',{expected_revision:revision,definition_version:risk.definition_version,metadata});await onSaved()}catch(cause){setError(cause instanceof Error?cause.message:'Risk configuration could not be saved.')}finally{setBusy(false)}}
 return <Dialog title={`SoD risk ${risk.risk_id}`} onClose={onClose} footer={<><Button disabled={busy} onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={()=>void save()}><Save size={16} aria-hidden="true"/>Save changes</Button></>}>
  <section className="grid gap-3" aria-label="Imported risk definition"><h3>Imported source definition</h3><p>{risk.source.source_text}</p><p className="sod-meta">Criticality {risk.source.criticality} · type {risk.source.risk_type} · {risk.current?'Current source':'Historical source'}. Identifiers, relationships and transaction mappings come from the import and cannot be edited.</p>{(['ACTVT1','ACTVT2'] as const).map(slot=><section key={slot}><h4>{slot} · {slot==='ACTVT1'?risk.source.activity1:risk.source.activity2}</h4><DataTable caption={`${slot} transaction mappings`}><thead><tr><th>Transaction</th><th>Description</th></tr></thead><tbody>{risk.source.activities[slot].map(mapping=><tr key={mapping.tcode}><td>{mapping.tcode}</td><td>{mapping.ttext||'Description unavailable'}</td></tr>)}</tbody></DataTable></section>)}</section>
  <section className="grid gap-3" aria-label="Local business metadata"><h3>Local business guidance</h3><Checkbox checked={metadata.enabled} onChange={event=>update('enabled',event.target.checked)}>Risk enabled</Checkbox>
   <div className="grid gap-3 sm:grid-cols-2"><FormField label="Display name"><Input value={metadata.display_name} maxLength={200} onChange={event=>update('display_name',event.target.value)}/></FormField><FormField label="Business area"><Input value={metadata.business_category} maxLength={120} onChange={event=>update('business_category',event.target.value)}/></FormField></div>
   <ColorPalette label="Risk color" value={metadata.color} onChange={value=>update('color',value)}/>
   {explanationFields.map(([key,label,max])=><FormField key={key} label={label}><textarea className="ui-control min-h-24" value={String(metadata[key])} maxLength={max} onChange={event=>update(key,event.target.value)}/></FormField>)}
   <FormField label="Local notes"><textarea className="ui-control min-h-24" value={metadata.notes} maxLength={8000} onChange={event=>update('notes',event.target.value)}/></FormField>
   <FormField label="Description review status"><Select value={metadata.description_review_status} onChange={event=>update('description_review_status',event.target.value)}><option>Needs description review</option><option>Reviewed</option></Select></FormField></section>
  {error&&<p role="alert">{error}</p>}
 </Dialog>
}
type ActivityMeta={display_name:string;business_category:string;explanation_en:string;review_guidance_en:string;notes:string;color:string}
type ActivityRow={activity:string;risks:string[];tcodes:string[];current:boolean;local:ActivityMeta;modified:string|null}
type ActivityList={items:ActivityRow[];total:number;offset:number;limit:number;revision:number}
function ActivityTab() {
 const qc=useQueryClient(),[search,setSearch]=useState(''),[current,setCurrent]=useState('current'),[offset,setOffset]=useState(0),[editing,setEditing]=useState<ActivityRow|null>(null),[message,setMessage]=useState('')
 const params=new URLSearchParams({search,current,offset:String(offset),limit:'25'})
 const query=useQuery({queryKey:['sod-catalogue-activities',params.toString()],queryFn:()=>apiRequest<ActivityList>(`/api/sod/catalogue-activities?${params}`)})
 return <section className="grid min-w-0 gap-4" aria-label="SoD activity configuration">
  <p className="ui-description">Activities are defined by the imported SoD matrix. Local names, explanations and colors help reviewers; they never change which conflicts are detected.</p>
  <Toolbar className="sod-config-toolbar"><SearchInput aria-label="Search SoD activities" placeholder="Search activities" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0)}} onClear={()=>{setSearch('');setOffset(0)}}/>
   <Select aria-label="Activity source presence" value={current} onChange={event=>{setCurrent(event.target.value);setOffset(0)}}><option value="current">Current source</option><option value="historical">Historical only</option><option value="">Current and historical</option></Select></Toolbar>
  {message&&<p role="status">{message}</p>}
  {query.isError?<p role="alert">{query.error instanceof Error?query.error.message:'Activities are unavailable.'}</p>:!query.data?<LoadingState/>:<><p role="status">{query.data.total} matching activities</p>{query.data.total?<DataTable caption="SoD activity configurations" tableClassName="sod-config-table"><thead><tr><th>Activity</th><th>Business area</th><th>Risks</th><th>Transactions</th><th>Modified</th><th>Actions</th></tr></thead><tbody>{query.data.items.map(row=><tr key={row.activity}><td><IdPill kind="activity" value={row.activity} color={row.local.color}/><p>{row.local.display_name||'No local name'}</p>{!row.current&&<p className="sod-meta">Historical · not in current source</p>}</td><td>{row.local.business_category||'Not specified'}</td><td><span className="id-pill-list">{row.risks.slice(0,6).map(risk=><IdPill key={risk} kind="risk" value={risk}/>)}</span>{row.risks.length>6&&<p className="sod-meta">+{row.risks.length-6} more</p>}</td><td className="sod-meta">{row.tcodes.length} transactions</td><td>{formatTimestamp(row.modified)}</td><td><Button size="compact" onClick={()=>setEditing(row)} aria-label={`Edit SoD activity ${row.activity}`}>Edit</Button></td></tr>)}</tbody></DataTable>:<EmptyState>No activities match. Configure a SoD matrix source to list its activities.</EmptyState>}<Pagination label="SoD activity pages" offset={offset} total={query.data.total} limit={query.data.limit} onChange={setOffset}/></>}
  {editing&&query.data&&<ActivityEditor row={editing} revision={query.data.revision} onClose={()=>setEditing(null)} onSaved={async()=>{setEditing(null);setMessage('Activity configuration saved. Imported mappings were preserved.');await qc.invalidateQueries({predicate:q=>String(q.queryKey[0]).startsWith('sod')})}}/>}
 </section>
}
function ActivityEditor({row,revision,onClose,onSaved}:{row:ActivityRow;revision:number;onClose:()=>void;onSaved:()=>Promise<void>}) {
 const [metadata,setMetadata]=useState<ActivityMeta>(row.local),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const update=(key:keyof ActivityMeta,value:string)=>setMetadata(previous=>({...previous,[key]:value}))
 const save=async()=>{setBusy(true);setError('');try{await apiRequest(`/api/sod/catalogue-activities/${encodeURIComponent(row.activity)}`,'POST',{expected_revision:revision,metadata});await onSaved()}catch(cause){setError(cause instanceof Error?cause.message:'Activity configuration could not be saved.')}finally{setBusy(false)}}
 return <Dialog title={`SoD activity ${row.activity}`} onClose={onClose} footer={<><Button disabled={busy} onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={()=>void save()}><Save size={16} aria-hidden="true"/>Save changes</Button></>}>
  <section className="grid gap-2" aria-label="Imported activity definition"><h3>Imported source definition</h3><p className="sod-meta">The activity identifier, its risks and its transaction mappings come from the import and cannot be edited.</p><p>Risks: {row.risks.join(', ')}</p><p>Transactions: {row.tcodes.join(', ')}</p></section>
  <section className="grid gap-3" aria-label="Local activity guidance"><h3>Local business guidance</h3>
   <div className="grid gap-3 sm:grid-cols-2"><FormField label="Display name"><Input value={metadata.display_name} maxLength={200} onChange={event=>update('display_name',event.target.value)}/></FormField><FormField label="Business area"><Input value={metadata.business_category} maxLength={120} onChange={event=>update('business_category',event.target.value)}/></FormField></div>
   <ColorPalette label="Activity color" value={metadata.color} onChange={value=>update('color',value)}/>
   <FormField label="Business explanation"><textarea className="ui-control min-h-24" value={metadata.explanation_en} maxLength={12000} onChange={event=>update('explanation_en',event.target.value)}/></FormField>
   <FormField label="Review guidance"><textarea className="ui-control min-h-24" value={metadata.review_guidance_en} maxLength={8000} onChange={event=>update('review_guidance_en',event.target.value)}/></FormField>
   <FormField label="Local notes"><textarea className="ui-control min-h-24" value={metadata.notes} maxLength={8000} onChange={event=>update('notes',event.target.value)}/></FormField></section>
  {error&&<p role="alert">{error}</p>}
 </Dialog>
}
