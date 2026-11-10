import {EntityNavigation,EntityHeader,filteredEntityIds,type EditorNavigation,type EntityLocation} from './SodEntityNavigation'
import {SodReferenceLibrary} from './SodReferenceLibrary'
import {useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {Save,ShieldAlert,ShieldCheck,ShieldOff,Info,Pencil,ListTree,Activity,Sparkles} from 'lucide-react'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {FormField,SearchInput,Checkbox} from '@/components/Shared/Controls'
import {Select} from '@/components/Shared/Select'
import {DataTable,StatusBadge,Toolbar,LoadingState,EmptyState} from '@/components/Shared/Presentation'
import {Dialog} from '@/components/Shared/Dialog'
import {ColorControl} from './Controls'
import {IdPill} from '@/components/Shared/IdPill'
import {SodMetadataField} from './SodMetadataField'
import {useSodMetadata,SodPill,SodEntityNavigation} from '@/lib/sodAppearance'
import {ContentTabs} from '@/components/Shared/Navigation'
import {Pagination} from '@/components/Access/Shared'
import {PillButton,SourceMeta,RiskSourceDialog,TransactionsDialog} from './SodSourceDetails'
import {EnabledBadge} from '@/components/Shared/StatusBadges'
import {formatTimestamp} from '@/lib/dateFormat'

type Metadata={enabled:boolean;display_name:string;business_category:string;notes:string;description_review_status:string;explanation_en:string;explanation_no:string;consequence_en:string;consequence_no:string;mitigating_controls_en:string;mitigating_controls_no:string;review_guidance_en:string;review_guidance_no:string;color:string}
type Mapping={activity:string;tcode:string;ttext:string}
type Risk={risk_id:string;display_name:string;source:{criticality:string;risk_type:string;source_text:string;activity1:string;activity2:string;activities:Record<'ACTVT1'|'ACTVT2',Mapping[]>;supported:boolean;evaluation_policy:string|null};local:Metadata;new:boolean;source_changed:boolean;description_review_status:string;current:boolean;definition_version:string;modified:string|null}
type Catalogue={revision:number;items:Risk[];total:number;offset:number;limit:number;summary:Record<string,number>;source:{loaded:boolean;records:number;risks:number;version:string|null;imported_at:string|null;checked_at:string|null}}
const riskActivities=(risk:Risk)=>[...new Set(Object.values(risk.source.activities).flat().map(row=>row.activity))].sort()
const relatedRisks=(row:ActivityRow)=>row.current?row.current_risks:row.risks
const validColor=(value:string)=>value===''||/^#[0-9a-fA-F]{6}$/.test(value)
const explanationFields=[['explanation_en','Business explanation',12000],['consequence_en','Risk consequence',8000],['mitigating_controls_en','Mitigating controls',12000],['review_guidance_en','Review guidance',8000]] as const
export function SodRiskSettings() {
 const qc=useQueryClient(),[tab,setTab]=useState('risks'),[history,setHistory]=useState<EntityLocation[]>([]),[message,setMessage]=useState('')
 const open=(entry:EntityLocation)=>{setMessage('');setHistory([entry])}
 return <><SodReferenceLibrary/>{message&&<p role="status">{message}</p>}<ContentTabs label="SoD configuration" value={tab} onChange={setTab} items={[{value:'risks',label:'Risks',icon:<ShieldAlert size={16} aria-hidden="true"/>},{value:'activities',label:'Activities',icon:<Activity size={16} aria-hidden="true"/>}]}>{tab==='risks'?<RiskTab onOpen={open}/>:<ActivityTab onOpen={open}/>}</ContentTabs>
 {history.length>0&&<DetailNavigator entry={history[history.length-1]} canBack={history.length>1} onBack={()=>setHistory(previous=>previous.slice(0,-1))} onMove={entry=>setHistory(previous=>[...previous.slice(-19),entry])} onClose={()=>setHistory([])} onSaved={async()=>{await qc.invalidateQueries({predicate:q=>String(q.queryKey[0]).startsWith('sod')});setHistory([]);setMessage('Configuration saved. Imported mappings were preserved.')}}/>}</>
}
function DetailNavigator({entry,canBack,onBack,onMove,onClose,onSaved}:{entry:EntityLocation;canBack:boolean;onBack:()=>void;onMove:(entry:EntityLocation)=>void;onClose:()=>void;onSaved:()=>Promise<void>}) {
 const entity=useQuery({queryKey:['sod-configuration-entity',entry.kind,entry.id],queryFn:()=>apiRequest<{item:Risk|ActivityRow;revision:number}>(`/api/sod/${entry.kind==='risk'?'catalogue':'catalogue-activities'}/${encodeURIComponent(entry.id)}`),refetchOnWindowFocus:false})
 const list=useQuery({queryKey:['sod-configuration-navigation',entry.scope],queryFn:()=>filteredEntityIds(entry.scope),staleTime:Infinity,retry:false})
 const ids=list.isError?[]:list.data||[],position=ids.indexOf(entry.id)
 const navigation:EditorNavigation={back:canBack?onBack:undefined,previous:position>0?()=>onMove({...entry,id:ids[position-1]}):undefined,next:position>=0&&position<ids.length-1?()=>onMove({...entry,id:ids[position+1]}):undefined,position:position>=0?`${position+1} of ${ids.length}`:'Loading list…',error:list.error instanceof Error?list.error.message:undefined,onEntity:(kind,id)=>{
  if(kind===entry.kind&&id===entry.id)return
  const related=entity.data?(entry.kind==='risk'?riskActivities(entity.data.item as Risk):relatedRisks(entity.data.item as ActivityRow)):[]
  onMove({kind,id,scope:kind===entry.kind?entry.scope:{kind,ids:related.includes(id)?related:[id]}})
 }}
 if(!entity.data)return <Dialog title={`SoD ${entry.kind} ${entry.id}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>{entity.error?<p role="alert">{entity.error instanceof Error?entity.error.message:'Entity unavailable.'}</p>:<LoadingState/>}</Dialog>
 return entry.kind==='risk'?<RiskEditor key={`risk:${entry.id}`} risk={entity.data.item as Risk} revision={entity.data.revision} navigation={navigation} onClose={onClose} onSaved={onSaved}/>:<ActivityEditor key={`activity:${entry.id}`} row={entity.data.item as ActivityRow} revision={entity.data.revision} navigation={navigation} onClose={onClose} onSaved={onSaved}/>
}
function RiskTab({onOpen}:{onOpen:(entry:EntityLocation)=>void}) {
 const qc=useQueryClient(),[search,setSearch]=useState(''),enabled='',current='',status='',criticality='',riskType='',category='',[offset,setOffset]=useState(0),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
 const params=new URLSearchParams({search,enabled,current,status,criticality,type:riskType,category,offset:String(offset),limit:'25'})
 const query=useQuery({queryKey:['sod-catalogue',params.toString()],queryFn:()=>apiRequest<Catalogue>(`/api/sod/catalogue?${params}`)})
 const refresh=async()=>{await qc.invalidateQueries({predicate:q=>String(q.queryKey[0]).startsWith('sod')})}
 const bulk=async(value:boolean)=>{
  if(!query.data||(!value&&!window.confirm('Disable all current SoD risks? Historical findings and review data will be preserved.')))return
  setBusy(true);setError('');setMessage('')
  try{const result=await apiRequest<{updated:number}>('/api/sod/catalogue/bulk','POST',{expected_revision:query.data.revision,enabled:value,confirm:!value});await refresh();setMessage(`${result.updated} current risk configurations updated.`)}catch(cause){setError(cause instanceof Error?cause.message:'Risk settings could not be saved.')}finally{setBusy(false)}
 }
 return <section className="grid min-w-0 gap-4" aria-label="SoD Risk Configuration">
  {query.data&&<p className="ui-description">{query.data.source.loaded?`${query.data.source.risks} source risks · ${query.data.source.records} mappings`:'No validated SoD matrix loaded'} · Last import: {formatTimestamp(query.data.source.imported_at)} · Last check: {formatTimestamp(query.data.source.checked_at)}</p>}
  <Toolbar className="sod-config-toolbar"><SearchInput aria-label="Search SoD risks" placeholder="Search SoD risks" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0)}} onClear={()=>{setSearch('');setOffset(0)}}/>
   <Button disabled={busy||!query.data?.source.loaded} onClick={()=>void bulk(true)}><ShieldCheck size={16} aria-hidden="true"/>Enable all current risks</Button><Button disabled={busy||!query.data?.source.loaded} onClick={()=>void bulk(false)}><ShieldOff size={16} aria-hidden="true"/>Disable all current risks</Button></Toolbar>
  {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  {query.isError?<p role="alert">{query.error instanceof Error?query.error.message:'Risk catalogue is unavailable.'}</p>:!query.data?<LoadingState/>:<><p role="status">{query.data.total} matching risks</p>{query.data.total?<DataTable caption="SoD risk configurations" tableClassName="sod-config-table"><thead><tr><th>Risk</th><th>Related Activities</th><th>Status</th><th>Description Review</th><th>Modified</th><th>Actions</th></tr></thead><tbody>{query.data.items.map(risk=><tr key={risk.risk_id}><td><div className="sod-id-line"><IdPill kind="risk" value={risk.risk_id} color={risk.local.color}/>{risk.new&&<NewBadge/>}</div><p>{risk.display_name||'Missing display name'}</p><SourceMeta criticality={risk.source.criticality} riskType={risk.source.risk_type}/></td><td><span className="id-pill-list">{riskActivities(risk).map(id=><PillButton key={id} kind="activity" value={id} label={`Open SoD activity ${id}`} onOpen={()=>onOpen({kind:'activity',id,scope:{kind:'activity',ids:riskActivities(risk)}})}/>)}</span></td><td><EnabledBadge enabled={risk.local.enabled} tone={risk.local.enabled&&risk.current&&risk.source.supported?'success':'neutral'}/>{!risk.current&&<p className="sod-meta">Historical · excluded from current analysis</p>}{!risk.source.supported&&<p className="sod-meta">Unsupported type · not evaluated</p>}</td><td><StatusBadge tone={risk.description_review_status==='Reviewed'?'success':'warning'}>{risk.description_review_status}</StatusBadge>{risk.source_changed&&<p className="sod-meta">Source changed</p>}</td><td>{formatTimestamp(risk.modified)}</td><td><div className="sod-row-actions"><Button size="compact" onClick={()=>onOpen({kind:'risk',id:risk.risk_id,scope:{kind:'risk',query:params.toString(),revision:query.data!.revision,sourceVersion:query.data!.source.version}})} aria-label={`Edit SoD risk ${risk.risk_id}`}><Pencil size={14} aria-hidden="true"/>Edit</Button></div></td></tr>)}</tbody></DataTable>:<EmptyState>{query.data.source.loaded?'No risks match these filters.':'Configure a SoD matrix source to inspect imported risks and maintain local guidance.'}</EmptyState>}<Pagination label="SoD risk pages" offset={offset} total={query.data.total} limit={query.data.limit} onChange={setOffset}/></>}
 </section>
}
/** Compact amber marker beside the Risk ID of a risk that arrived with the latest import; the row itself keeps the normal background. */
const NewBadge=()=><StatusBadge tone="warning" className="sod-new-badge"><Sparkles size={12} aria-hidden="true"/>New</StatusBadge>
function RiskEditor({risk,revision,onClose,onSaved,navigation}:{risk:Risk;revision:number;onClose:()=>void;onSaved:()=>Promise<void>;navigation:EditorNavigation}) {
 const [metadata,setMetadata]=useState<Metadata>({...risk.local,description_review_status:risk.description_review_status}),[source,setSource]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const description=useSodMetadata().risks[risk.risk_id]
 const [baseline]=useState({revision,definition:risk.definition_version})
 const update=(key:keyof Metadata,value:string|boolean)=>setMetadata(previous=>({...previous,[key]:value}))
 // Norwegian text from earlier versions is kept untouched in metadata; only English is edited here.
 const [original]=useState(()=>JSON.stringify(metadata))
 const request=(action:()=>void)=>{if(!busy&&(JSON.stringify(metadata)===original||window.confirm('Discard unsaved changes before navigating?')))action()}
 const save=async()=>{setBusy(true);setError('');try{await apiRequest(`/api/sod/catalogue/${encodeURIComponent(risk.risk_id)}`,'POST',{expected_revision:baseline.revision,definition_version:baseline.definition,metadata});await onSaved()}catch(cause){setError(cause instanceof Error?cause.message:'Risk configuration could not be saved.')}finally{setBusy(false)}}
 return <SodEntityNavigation.Provider value={(kind,id)=>request(()=>navigation.onEntity(kind,id))}><Dialog title={`SoD risk ${risk.risk_id}`} onClose={()=>request(onClose)} footer={<><Button disabled={busy} onClick={()=>request(onClose)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!validColor(metadata.color)} onClick={()=>void save()}><Save size={16} aria-hidden="true"/>Save changes</Button></>}>
  <EntityNavigation navigation={navigation} request={request}/>
  <EntityHeader kind="risk" id={risk.risk_id} name={description?.name} color={metadata.color} actions={<Button size="compact" onClick={()=>setSource(true)} aria-label={`Source details for risk ${risk.risk_id}`}><Info size={14} aria-hidden="true"/>Source details</Button>} metadata={<><SourceMeta criticality={risk.source.criticality} riskType={risk.source.risk_type}/><EnabledBadge enabled={metadata.enabled}/><StatusBadge>{risk.current?'Current source':'Historical source'}</StatusBadge></>}/>

  <section aria-label="Related Activities"><h3>Related Activities</h3><span className="id-pill-list">{riskActivities(risk).map(id=><SodPill key={id} kind="activity" value={id}/>)}</span></section>
  <section className="grid gap-3" aria-label="Local business metadata"><h3>Effective business guidance</h3>
   <div className="sod-editor-grid">
    <SodMetadataField label="Display name" field="name" value={metadata.display_name} entry={description} maxLength={200} onChange={value=>update('display_name',value)}/>
    <SodMetadataField label="Business area" field="business_process" value={metadata.business_category} entry={description} maxLength={120} onChange={value=>update('business_category',value)}/>
    {explanationFields.map(([key,label,max])=><div key={key} className="sod-editor-wide"><SodMetadataField label={label} field={{explanation_en:'description',consequence_en:'impact',mitigating_controls_en:'controls',review_guidance_en:'guidance'}[key]} value={String(metadata[key])} entry={description} maxLength={max} multiline onChange={value=>update(key,value)}/></div>)}
    <div className="sod-editor-wide"><SodMetadataField label="Local notes" field="notes" value={metadata.notes} entry={description} maxLength={8000} multiline onChange={value=>update('notes',value)}/></div></div>
  </section><section className="grid gap-2" aria-label="Risk settings"><h3>Settings</h3><div className="sod-editor-grid"><div className="sod-editor-wide"><Checkbox checked={metadata.enabled} onChange={event=>update('enabled',event.target.checked)}>Risk enabled</Checkbox></div><ColorControl optional label="Risk color" value={metadata.color} onChange={value=>update('color',value.toLowerCase())} onReset={()=>update('color','')} preview={<IdPill kind="risk" value={risk.risk_id} color={metadata.color}/>}/><FormField label="Description review status"><Select value={metadata.description_review_status} onChange={event=>update('description_review_status',event.target.value)}><option>Needs description review</option><option>Reviewed</option></Select></FormField></div>
   <p className="sod-meta">Description review status records whether the wording was reviewed; it is not a risk acceptance and never changes what is detected.</p></section>
  {source&&<RiskSourceDialog risk={risk} onClose={()=>setSource(false)}/>}
  {error&&<p role="alert">{error}</p>}
 </Dialog></SodEntityNavigation.Provider>
}
type ActivityMeta={display_name:string;business_category:string;explanation_en:string;review_guidance_en:string;notes:string;color:string}
type ActivityRow={activity:string;display_name:string;current_risks:string[];risks:string[];tcodes:string[];mappings:Mapping[];current:boolean;local:ActivityMeta;modified:string|null}
type ActivityList={source_version:string|null;items:ActivityRow[];total:number;offset:number;limit:number;revision:number}
function ActivityTab({onOpen}:{onOpen:(entry:EntityLocation)=>void}) {
 const [search,setSearch]=useState(''),current='',[offset,setOffset]=useState(0),[transactionsOf,setTransactionsOf]=useState<ActivityRow|null>(null)
 const params=new URLSearchParams({search,current,offset:String(offset),limit:'25'})
 const query=useQuery({queryKey:['sod-catalogue-activities',params.toString()],queryFn:()=>apiRequest<ActivityList>(`/api/sod/catalogue-activities?${params}`)})
 return <section className="grid min-w-0 gap-4" aria-label="SoD activity configuration">
  <p className="ui-description">Activities are defined by the imported SoD matrix. Display names, explanations and colors help reviewers; they never change which conflicts are detected.</p>
  <Toolbar className="sod-config-toolbar"><SearchInput aria-label="Search SoD activities" placeholder="Search activities" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0)}} onClear={()=>{setSearch('');setOffset(0)}}/></Toolbar>
  {query.isError?<p role="alert">{query.error instanceof Error?query.error.message:'Activities are unavailable.'}</p>:!query.data?<LoadingState/>:<><p role="status">{query.data.total} matching activities</p>{query.data.total?<DataTable caption="SoD activity configurations" tableClassName="sod-config-table"><thead><tr><th>Activity</th><th>Related Risks</th><th>Transactions</th><th>Modified</th><th>Actions</th></tr></thead><tbody>{query.data.items.map(row=><tr key={row.activity}><td><div className="sod-id-line"><IdPill kind="activity" value={row.activity} color={row.local.color}/>{!row.current&&<StatusBadge className="sod-historical-badge" title="Not in the current source">Historical</StatusBadge>}</div><p>{row.display_name||'Missing display name'}</p></td><td><span className="id-pill-list">{relatedRisks(row).slice(0,6).map(risk=><PillButton key={risk} kind="risk" value={risk} label={`Open SoD risk ${risk}`} onOpen={()=>onOpen({kind:'risk',id:risk,scope:{kind:'risk',ids:relatedRisks(row)}})}/>)}</span>{relatedRisks(row).length>6&&<Button size="compact" variant="ghost" aria-label={`View all related risks for ${row.activity}`} onClick={()=>onOpen({kind:'activity',id:row.activity,scope:{kind:'activity',query:params.toString(),revision:query.data!.revision,sourceVersion:query.data!.source_version}})}>+{relatedRisks(row).length-6} more</Button>}</td><td><Button size="compact" aria-label={`Show ${row.tcodes.length} transactions for ${row.activity}`} title="Inspect the transactions behind this activity" onClick={()=>setTransactionsOf(row)}><ListTree size={14} aria-hidden="true"/>{row.tcodes.length.toLocaleString()} {row.tcodes.length===1?'transaction':'transactions'}</Button></td><td>{formatTimestamp(row.modified)}</td><td><Button size="compact" onClick={()=>onOpen({kind:'activity',id:row.activity,scope:{kind:'activity',query:params.toString(),revision:query.data!.revision,sourceVersion:query.data!.source_version}})} aria-label={`Edit SoD activity ${row.activity}`}><Pencil size={14} aria-hidden="true"/>Edit</Button></td></tr>)}</tbody></DataTable>:<EmptyState>No activities match. Configure a SoD matrix source to list its activities.</EmptyState>}<Pagination label="SoD activity pages" offset={offset} total={query.data.total} limit={query.data.limit} onChange={setOffset}/></>}
  {transactionsOf&&<TransactionsDialog title={`${transactionsOf.activity} transactions`} mappings={transactionsOf.mappings} onClose={()=>setTransactionsOf(null)}/>}
 </section>
}
function ActivityEditor({row,revision,onClose,onSaved,navigation}:{row:ActivityRow;revision:number;onClose:()=>void;onSaved:()=>Promise<void>;navigation:EditorNavigation}) {
 const [metadata,setMetadata]=useState<ActivityMeta>(row.local),[transactions,setTransactions]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const description=useSodMetadata().activities[row.activity]
 const [baseline]=useState(revision)
 const update=(key:keyof ActivityMeta,value:string)=>setMetadata(previous=>({...previous,[key]:value}))
 const [original]=useState(()=>JSON.stringify(metadata))
 const request=(action:()=>void)=>{if(!busy&&(JSON.stringify(metadata)===original||window.confirm('Discard unsaved changes before navigating?')))action()}
 const save=async()=>{setBusy(true);setError('');try{await apiRequest(`/api/sod/catalogue-activities/${encodeURIComponent(row.activity)}`,'POST',{expected_revision:baseline,metadata});await onSaved()}catch(cause){setError(cause instanceof Error?cause.message:'Activity configuration could not be saved.')}finally{setBusy(false)}}
 return <SodEntityNavigation.Provider value={(kind,id)=>request(()=>navigation.onEntity(kind,id))}><Dialog title={`SoD activity ${row.activity}`} onClose={()=>request(onClose)} footer={<><Button disabled={busy} onClick={()=>request(onClose)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!validColor(metadata.color)} onClick={()=>void save()}><Save size={16} aria-hidden="true"/>Save changes</Button></>}>
  <EntityNavigation navigation={navigation} request={request}/>
  <EntityHeader kind="activity" id={row.activity} name={description?.name} color={metadata.color} actions={<Button size="compact" aria-label={`Show ${row.tcodes.length} transactions for ${row.activity}`} onClick={()=>setTransactions(true)}><ListTree size={14} aria-hidden="true"/>{row.tcodes.length.toLocaleString()} {row.tcodes.length===1?'transaction':'transactions'}</Button>}><div className="flex flex-wrap items-center gap-2"><h3>Related Risks</h3><span className="id-pill-list">{relatedRisks(row).map(risk=><SodPill key={risk} kind="risk" value={risk}/>)}</span></div></EntityHeader>

  <section className="grid gap-3" aria-label="Local activity guidance"><h3>Effective business guidance</h3>
   <div className="sod-editor-grid"><SodMetadataField label="Display name" field="name" value={metadata.display_name} entry={description} maxLength={200} onChange={value=>update('display_name',value)}/><SodMetadataField label="Business area" field="business_process" value={metadata.business_category} entry={description} maxLength={120} onChange={value=>update('business_category',value)}/>
    <ColorControl optional label="Activity color" value={metadata.color} onChange={value=>update('color',value.toLowerCase())} onReset={()=>update('color','')} preview={<IdPill kind="activity" value={row.activity} color={metadata.color}/>}/>
    <div className="sod-editor-wide"><SodMetadataField label="Business explanation" field="description" value={metadata.explanation_en} entry={description} maxLength={12000} multiline onChange={value=>update('explanation_en',value)}/></div>
    <div className="sod-editor-wide"><SodMetadataField label="Review guidance" field="guidance" value={metadata.review_guidance_en} entry={description} maxLength={8000} multiline onChange={value=>update('review_guidance_en',value)}/></div>
    <div className="sod-editor-wide"><SodMetadataField label="Local notes" field="notes" value={metadata.notes} entry={description} maxLength={8000} multiline onChange={value=>update('notes',value)}/></div></div></section>
  {transactions&&<TransactionsDialog title={`${row.activity} transactions`} mappings={row.mappings} onClose={()=>setTransactions(false)}/>}
  {error&&<p role="alert">{error}</p>}
 </Dialog></SodEntityNavigation.Provider>
}
