import {useState} from 'react'
import {apiRequest} from '@/api/client'
import {Button} from '@/components/Shared/Button'
import {Toolbar} from '@/components/Shared/Presentation'
import {FormField} from '@/components/Shared/Controls'
import {Select} from '@/components/Shared/Select'
import {Dialog} from '@/components/Shared/Dialog'
import {NorwegianDateInput,parseNorwegianDate} from '@/components/Shared/NorwegianDateInput'
import {formatDate} from '@/lib/dateFormat'
const decisions=['Pending review','Accepted with mitigating controls','Access removal required','Not applicable / false positive','Further investigation required']
const blank={decision:'Pending review',reviewer:'',rationale:'',comments:'',mitigating_controls:'',action_owner:'',target_date:null as string|null,action_status:'Not started',completion_notes:''}
type Annotation=typeof blank
type Event={event_id:string;timestamp:string;evidence_version:string;annotation:Annotation}
export type Row={finding_id:string;finding:{subject:string;risk_id:string;evidence_version:string};decision:string;event:Event|null;history_count:number;stale:boolean;lifecycle:string;presence:string}
export function ReviewEditor({row,revision,generation,onClose,onSaved,saveReview}:{row:Row;revision:number;generation:string;onClose:()=>void;onSaved:()=>Promise<void>;saveReview?:(value:Annotation)=>Promise<unknown>}){
 const [value,setValue]=useState<Annotation>({...blank,...row.event?.annotation}),[due,setDue]=useState(formatDate(value.target_date,'')),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const save=async()=>{setBusy(true);setError('');try{const parsed=due?parseNorwegianDate(due):null;if(due&&!parsed)throw Error('Target date must use DD.MM.YYYY.');if(saveReview)await saveReview({...value,target_date:parsed});else await apiRequest(`/api/sod/reviews/${row.finding_id}`,'POST',{expected_revision:revision,expected_generation:generation,evidence_version:row.finding.evidence_version,annotation:{...value,target_date:parsed}});await onSaved()}catch(e){setError(e instanceof Error?e.message:'Review could not be saved.')}finally{setBusy(false)}}
 return <Dialog title={`Review ${row.finding.subject} · ${row.finding.risk_id}`} onClose={onClose}><p className="ui-description">Self-reported reviewer; not authenticated identity. Every save creates an immutable history event.</p><FormField label="Decision"><Select value={value.decision} onChange={e=>setValue({...value,decision:e.target.value})}>{decisions.map(x=><option key={x}>{x}</option>)}</Select></FormField>{(['reviewer','rationale','comments','mitigating_controls','action_owner','completion_notes'] as const).map(key=><FormField key={key} label={{reviewer:'Reviewer (self-reported)',rationale:'Justification',comments:'Comments',mitigating_controls:'Mitigating controls',action_owner:'Action owner',completion_notes:'Completion notes'}[key]}><textarea className="ui-control" value={value[key]} maxLength={key==='reviewer'||key==='action_owner'?120:key==='mitigating_controls'?8000:4000} onChange={e=>setValue({...value,[key]:e.target.value})}/></FormField>)}<FormField label="Target date"><NorwegianDateInput label="Action target date" value={due} onChange={setDue}/></FormField><FormField label="Action status"><Select value={value.action_status} onChange={e=>setValue({...value,action_status:e.target.value})}>{['Not started','In progress','Completed','Not applicable'].map(x=><option key={x}>{x}</option>)}</Select></FormField>{error&&<p role="alert">{error}</p>}<Toolbar><Button variant="primary" loading={busy} onClick={()=>void save()}>Save review decision</Button><Button onClick={onClose}>Cancel</Button></Toolbar></Dialog>
}
