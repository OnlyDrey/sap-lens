import { useId, useMemo, useState, type ReactNode, type Ref } from 'react'
import { FolderOpen, FileCheck2 } from 'lucide-react'
import { FormField, Input, SearchInput } from '@/components/Shared/Controls'
import { Button } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { DataTable, StatusBadge } from '@/components/Shared/Presentation'

/** Shared presentation only: selection and activation remain owned by each importer. */
export function SourceFileField({ label, value, onChange, onBrowse, browseLabel, disabled=false, native=false, inputRef, placeholder }: {
 label:string;value:string;onChange:(value:string)=>void;onBrowse:()=>void;browseLabel:string;disabled?:boolean;native?:boolean;inputRef?:Ref<HTMLInputElement>;placeholder?:string
}) {
 return <div className="source-file-row"><FormField label={label}><Input ref={inputRef} disabled={disabled} title={value} value={value} maxLength={4096} placeholder={placeholder} onChange={event=>onChange(event.target.value)}/></FormField><Button disabled={disabled||!native} title={native?browseLabel:'Native browsing is available in the desktop app. In server mode, upload a CSV or enter a permitted server path.'} onClick={onBrowse}><FolderOpen size={16} aria-hidden="true"/>{browseLabel}</Button></div>
}
export function MappingField({field,label,value,columns,onChange,disabled=false,accessibleLabel,required=false}: {
 field:string;label:string;value:string;columns:string[];onChange:(value:string)=>void;disabled?:boolean;accessibleLabel?:string;required?:boolean
}) {
 const id=useId(),normalize=(text:string)=>text.toLowerCase().replace(/[^a-z0-9]/g,'')
 const detected=columns.find(column=>normalize(column)===normalize(field))
 const state=value?(columns.includes(value)?'Manual mapping':'Mapped column missing'):detected?`Detected: ${detected}`:'Not detected — automatic mapping'
 return <div className="ui-field mapping-field"><label htmlFor={id}>{label}{required&&!label.toLowerCase().includes('required')&&<span className="mapping-required">Required</span>}</label><small className="ui-description">SAP field: <code>{field}</code></small><Combobox id={id} label={accessibleLabel||field} disabled={disabled} value={value} options={[...columns,...(value?[value]:[])]} onChange={onChange} placeholder="Automatic mapping" clearLabel="Automatic mapping" allowCustom={false}/><small className={`mapping-state ${value&&!columns.includes(value)?'text-[var(--warning)]':'text-[var(--muted)]'}`}>{state}</small></div>
}
export function ImportPreview({fileName,metrics,warnings=[],errors=[],samples=[],children}: {
 fileName?:string;metrics:{label:string;value:number}[];warnings?:string[];errors?:string[];samples?:Record<string,string>[];children?:ReactNode
}) {
 const [search,setSearch]=useState('')
 const columns=[...new Set(samples.flatMap(row=>Object.keys(row)))]
 const visible=useMemo(()=>samples.filter(row=>Object.values(row).some(value=>String(value).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))),[samples,search])
 return <section className="import-preview space-y-3" aria-label="Import preview"><header className="ui-toolbar"><FileCheck2 size={18} aria-hidden="true"/><strong>{fileName||'Selected CSV'}</strong><StatusBadge tone={errors.length?'error':'success'}>{errors.length?'Validation failed':'Preview validated'}</StatusBadge></header><dl className="preview-metrics">{metrics.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.value.toLocaleString()}</dd></div>)}</dl>{errors.length>0&&<div role="alert"><h3>Errors</h3><ul>{errors.map(item=><li key={item}>{item}</li>)}</ul></div>}{warnings.length>0&&<details><summary>{warnings.length} validation {warnings.length===1?'warning':'warnings'}</summary><ul>{warnings.map(item=><li key={item}>{item}</li>)}</ul></details>}{samples.length>0&&<><SearchInput aria-label="Search validated preview" placeholder="Search preview rows…" value={search} onChange={event=>setSearch(event.target.value)} onClear={()=>setSearch('')}/><p className="ui-description" role="status">{visible.length} of {samples.length} validated preview rows · Import totals above describe the full validated CSV.</p><DataTable caption="CSV preview records"><thead><tr>{columns.map(key=><th key={key} scope="col">{key}</th>)}</tr></thead><tbody>{visible.map((row,index)=><tr key={index}>{columns.map(key=><td key={key}><details className="preview-cell"><summary title={row[key]}>{row[key]||'—'}</summary><p>{row[key]||'No value'}</p></details></td>)}</tr>)}</tbody></DataTable>{!visible.length&&<p>No preview rows match.</p>}</>}{children}<p className="ui-description">Preview only. Loaded data is unchanged until you confirm the import.</p></section>
}
