import { Check, MinusCircle } from 'lucide-react'
export function StatusPill({enabled,onToggle,label,disabled=false}:{enabled:boolean;onToggle?:()=>void;label?:string;disabled?:boolean}) {
 const Icon=enabled?Check:MinusCircle
 const content=<><Icon size={13} aria-hidden="true"/>{enabled?'Enabled':'Disabled'}</>
 const className=`status-pill ${enabled?'status-enabled':'status-disabled'}`
 return onToggle?<button type="button" className={className} role="switch" aria-label={label} aria-checked={enabled} disabled={disabled} onClick={onToggle}>{content}</button>:<span className={className}>{content}</span>
}
