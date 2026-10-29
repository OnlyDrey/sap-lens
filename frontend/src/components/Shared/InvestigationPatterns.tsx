import type { ReactNode } from 'react'
import { Activity, CircleCheck, CircleAlert, CircleHelp } from 'lucide-react'
import { StatusBadge } from './Presentation'
export function StatusCard({label,value,tone='neutral',children}: {label:string;value:ReactNode;tone?:'neutral'|'success'|'warning'|'error'|'info';children?:ReactNode}) {
 const Icon=tone==='success'?CircleCheck:tone==='warning'||tone==='error'?CircleAlert:tone==='info'?Activity:CircleHelp
 return <div className="compact-health" data-tone={tone}><span className="status-card-label"><Icon size={16} aria-hidden="true"/>{label}</span><strong>{value}</strong>{children}</div>
}
export function FilterPanel({label,children,className=''}:{label:string;children:ReactNode;className?:string}) {
 return <section aria-label={label} className="ui-filter-panel"><h2>{label}</h2><div className={className}>{children}</div></section>
}
export function ResultsToolbar({children}:{children:ReactNode}) {return <div className="results-toolbar ui-toolbar">{children}</div>}
export function PreviewStatus({validated,inspecting}:{validated:boolean;inspecting?:boolean}) {
 return <StatusBadge tone={inspecting?'info':validated?'success':'neutral'}>{inspecting?'Inspecting selected file…':validated?'Preview validated':'Not yet validated'}</StatusBadge>
}
/** Compact, clickable summary count that applies a filter to the list below it. */
export function FilterTile({label,value,tone='neutral',active,onClick}:{label:string;value:ReactNode;tone?:'neutral'|'warning';active:boolean;onClick:()=>void}) {
 return <button type="button" className="filter-tile" data-tone={tone} aria-pressed={active} onClick={onClick}><span className="filter-tile-label">{label}</span><strong>{value}</strong></button>
}
