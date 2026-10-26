import {Download} from 'lucide-react'
import {Button,type ButtonProps} from './Button'
export function ExportCSVButton(props:ButtonProps) {
 return <Button variant="outline" {...props}><Download size={16} aria-hidden="true"/>Export CSV</Button>
}
