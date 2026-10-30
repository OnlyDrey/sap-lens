import {Download} from 'lucide-react'
import {Button,type ButtonProps} from './Button'
/** `label` names a secondary export on a page that also has the main one (for example the heatmap export beside a page export). */
export function ExportCSVButton({label='Export CSV',...props}:ButtonProps&{label?:string}) {
 return <Button variant="outline" {...props}><Download size={16} aria-hidden="true"/>{label}</Button>
}
