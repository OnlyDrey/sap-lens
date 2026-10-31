import {useEffect,useRef,useState,type Ref,type RefObject} from 'react'
import {useQuery} from '@tanstack/react-query'
import {RefreshCw,Eye,FileDiff,Info,Loader2,Trash2} from 'lucide-react'
import {apiRequest,applicationToken} from '@/api/client'
import type {Configuration,ImportProfile} from '@/api/configuration'
import type {CSVSource,SourceActivation} from '@/api/sources'
import {useApplicationData} from '@/state/ApplicationData'
import {Button} from '@/components/Shared/Button'
import {Dialog} from '@/components/Shared/Dialog'
import {DataTable} from '@/components/Shared/Presentation'
import {RefreshReportDialog,type RefreshSummary} from '@/components/Shared/RefreshReport'
import {Pagination} from '@/components/Access/Shared'
import {SourceFileField} from './ImportControls'
import {BrowserSourceUpload} from './BrowserSourceUpload'
import {SodSourceInspection} from './SodSourceInspection'
import {SourceMode} from './SourceMode'
import {SourceDetailsDialog,SourceHealthSummary,useSourceEvidence} from './SourceStatus'
import {DirectoryPreview} from './DirectoryPreview'

const names={roles:'Role Catalogue',users:'User Access',employees:'Employee Directory',sod:'SoD Matrix'}
export function SourceManager({source,draft,onMode,onActivated,onClear,onFeatures,inputRef,onCandidate,candidatePath}:{
 source:CSVSource;draft:Configuration;onMode:(mode:'static'|'dynamic')=>void;onActivated:(result:SourceActivation)=>void;
 onClear:()=>Promise<void>;onFeatures:()=>void;onCandidate:(path:string)=>void;candidatePath?:string;inputRef?:Ref<HTMLInputElement>
}) {
 const savedPath=source==='roles'?draft.data_csv_path:source==='users'?draft.user_csv_path:source==='sod'?draft.sod_csv_path||'':draft.employee_csv_path||''
 const [path,setPath]=useState(candidatePath??savedPath),[picking,setPicking]=useState(false),[pending,setPending]=useState(false),[feedback,setFeedback]=useState(''),[error,setError]=useState('')
 const [preview,setPreview]=useState(false),[technical,setTechnical]=useState(false),[changes,setChanges]=useState(false),[hint,setHint]=useState('')
 const uploadInput=useRef<HTMLInputElement>(null)
 const lastAttempt=useRef(savedPath),mounted=useRef(true)
 const {loading,activateSource,importPhase,report}=useApplicationData(),evidence=useSourceEvidence(source)
 const history=useQuery({queryKey:['refresh-history'],queryFn:()=>apiRequest<{items:(Omit<RefreshSummary,'sources'>&{sources?:RefreshSummary['sources']})[]}>('/api/data-sources/history')})
 const latest=report?.id?report:history.data?.items[0]?{...history.data.items[0],sources:history.data.items[0].sources||[]}:null
 const busy=picking||pending||loading,mode=draft.source_modes?.[source]||(source==='employees'||source==='sod'?'static':'dynamic')
 useEffect(()=>{setPath(candidatePath??savedPath);lastAttempt.current=candidatePath??savedPath},[savedPath,source])
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
 const activate=async(selected:string,selectedMode=mode)=>{
  const chosen=selected.trim();if(!chosen)return
  lastAttempt.current=chosen;setPath(chosen);onCandidate(chosen);setError('');setFeedback('');setPending(true)
  const profile:ImportProfile|undefined=source==='roles'?draft.import_profiles.find(p=>p.id===draft.active_import):source==='users'?draft.user_import_profiles.find(p=>p.id===draft.active_user_import):source==='sod'?draft.sod_import:undefined
  try{
   const result=await activateSource(source,{path:chosen,mode:selectedMode,revision:draft.revision,profile})
   // The Settings owner remains mounted when source tabs change; rebase there.
   onActivated(result)
   if(mounted.current){const change=result.refresh.sources.find(row=>row.source===source);setFeedback(`Completed · ${result.records.toLocaleString()} source records from ${chosen.split(/[\\/]/).pop()} · ${change?.added||0} added, ${change?.removed||0} removed, ${change?.modified||0} modified.`)}
  }catch(cause){if(mounted.current){setError(cause instanceof Error?cause.message:'CSV activation failed.')}}  // the attempted path stays in the field for correction or column mapping; the configured file and its data are never replaced by a failed attempt
  finally{if(mounted.current)setPending(false)}
 }
 return <section className="settings-card space-y-3" aria-label={`${names[source]} source management`}>
  <h2 className="settings-subheading">Source file</h2>
  <p className="ui-description">Selecting a file automatically validates and imports the complete dataset. Invalid or empty files never replace active data. Cancel settings does not undo a completed import.</p>
  <BrowserSourceUpload source={source} disabled={picking||pending} fileInput={uploadInput} onUploaded={selected=>activate(selected,'static')}/>
  <SourceFileField label={source==='roles'?'CSV file location':source==='users'?'User CSV file location':source==='sod'?'SoD Matrix CSV location':'Employee Directory CSV location'} value={path} onChange={value=>{setPath(value);onCandidate(value)}} inputRef={inputRef} disabled={busy} browseDisabled={picking||pending} native={!!window.pywebview?.api.choose_csv} browseLabel="Browse CSV" placeholder="Absolute local or server-visible CSV path" onCommit={force=>{if(force||path.trim()!==lastAttempt.current)void activate(path)}} onBrowse={()=>{
   setError('');setHint('')
   if(window.pywebview?.api.choose_csv){
    setPicking(true);void window.pywebview.api.choose_csv(applicationToken()).then(selected=>selected?activate(selected):undefined).catch(()=>setError('The native file dialog could not open. Enter an absolute CSV path and press Enter.')).finally(()=>{if(mounted.current)setPicking(false)})
   }else if(uploadInput.current)uploadInput.current.click()
   else{(inputRef as RefObject<HTMLInputElement>|undefined)?.current?.focus();setHint('Native file browsing is only available in the desktop app. Enter the absolute path of a CSV file this application can read and press Enter; the current file stays active until it validates.')}
  }}/>
  {hint&&<p role="status" className="ui-description">{hint}</p>}
  <SourceMode value={mode} disabled={busy} onChange={onMode}/>
  {evidence.source?<SourceHealthSummary source={evidence.source}/>:<p role="status">Checking current source status…</p>}
  {(pending||loading)&&<p role="status" className="ui-toolbar"><Loader2 size={16} className="animate-spin" aria-hidden="true"/>{importPhase||'Reading and validating sources…'}</p>}
  {feedback&&<p role="status">{feedback}</p>}
  {error&&<p role="alert">Failed — {error} No source data was replaced.{savedPath?` The active file is unchanged: ${savedPath.split(/[\\/]/).pop()}.`:''}</p>}
  {source!=='roles'&&evidence.source?.enabled===false&&evidence.source.loaded&&<p className="ui-description">Imported data is retained while this feature is disabled. <Button variant="ghost" onClick={onFeatures}>Open Feature Settings</Button></p>}
  <div className="ui-toolbar">
   <Button disabled={busy||!path.trim()} onClick={()=>void activate(path)} title="Explicitly revalidate the selected file, including Static sources; only a valid non-empty replacement is activated."><RefreshCw size={16} aria-hidden="true"/>Refresh source</Button>
   <Button disabled={!evidence.source?.loaded} onClick={()=>setPreview(true)}><Eye size={16} aria-hidden="true"/>Preview data</Button>
   <Button disabled={!latest?.id} onClick={()=>setChanges(true)} title="View the latest retained source change report."><FileDiff size={16} aria-hidden="true"/>View changes</Button>
   <Button disabled={!evidence.source} onClick={()=>setTechnical(true)}><Info size={16} aria-hidden="true"/>Technical source details</Button>
   <Button disabled={busy||!savedPath} onClick={()=>{if(window.confirm('Clear this source and its loaded data? The original CSV is not deleted.')){setError('');setPending(true);void onClear().then(()=>{if(mounted.current){setPath('');setFeedback('Source data cleared.')}}).catch(cause=>{if(mounted.current)setError(cause instanceof Error?cause.message:'Source could not be cleared.')}).finally(()=>{if(mounted.current)setPending(false)})}}}><Trash2 size={16} aria-hidden="true"/>Clear source data</Button>
  </div>
  {technical&&evidence.source&&<SourceDetailsDialog source={evidence.source} onClose={()=>setTechnical(false)}/>}
  {changes&&latest&&<RefreshReportDialog report={latest} mode="changes" onClose={()=>setChanges(false)}/>}
  {preview&&source==='sod'&&<SodSourceInspection onClose={()=>setPreview(false)}><section aria-label="Imported SoD records" className="space-y-2"><h3 className="text-base font-semibold">Imported records</h3><SnapshotRows source={source}/></section></SodSourceInspection>}
  {preview&&source!=='sod'&&<Dialog title={`${names[source]} snapshot preview`} onClose={()=>setPreview(false)}><p className="ui-description">Current validated snapshot; the original CSV is not reread.</p>{source==='employees'?<section aria-label="Directory import preview"><DirectoryPreview snapshot path={savedPath||'snapshot'} digest={draft.employee_snapshot_id||''} revision={draft.revision}/></section>:<SnapshotRows source={source}/>}</Dialog>}
 </section>
}
function SnapshotRows({source}:{source:CSVSource}) {
 const [offset,setOffset]=useState(0)
 const result=useQuery({queryKey:['source-preview',source,offset],queryFn:()=>apiRequest<{columns:string[];items:Record<string,string>[];total:number;limit:number}>(`/api/data-sources/${source}/preview?offset=${offset}`)})
 if(result.isError)return <p role="alert">Snapshot preview could not be loaded.</p>
 if(!result.data)return <p role="status">Loading snapshot preview…</p>
 const {columns,items,total,limit}=result.data
 return <><p>{total.toLocaleString()} source records</p><DataTable caption="Imported source records"><thead><tr>{columns.map(column=><th key={column}>{column}</th>)}</tr></thead><tbody>{items.map((row,index)=><tr key={index}>{columns.map(column=><td key={column}>{row[column]}</td>)}</tr>)}</tbody></DataTable><Pagination label="Source preview pages" offset={offset} total={total} limit={limit} onChange={setOffset}/></>
}
