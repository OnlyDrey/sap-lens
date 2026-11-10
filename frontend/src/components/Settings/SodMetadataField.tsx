import { Button } from '@/components/Shared/Button'
import { FormField, Input } from '@/components/Shared/Controls'
import type { SodDescription } from '@/lib/sodAppearance'

const origins = { imported: 'Active SoD import', reference: 'Reference workbook', local: 'Local override' }
/** Display inherited text without copying it into local state or creating an override on save. */
export function SodMetadataField({ label, field, value, entry, maxLength, multiline=false, onChange }: {
  label:string; field:string; value:string; entry?:SodDescription; maxLength:number; multiline?:boolean; onChange:(value:string)=>void
}) {
  const inherited=entry?.inherited?.[field]||'', reference=entry?.reference?.[field]||'', shown=value||inherited
  const change=(next:string)=>onChange(next===inherited?'':next)
  return <div className="grid min-w-0 gap-1">
    <FormField label={label}>{multiline
      ? <textarea className="ui-control min-h-24" value={shown} maxLength={maxLength} onChange={event=>change(event.target.value)}/>
      : <Input value={shown} maxLength={maxLength} onChange={event=>change(event.target.value)}/>}</FormField>
    <div className="flex flex-wrap items-center gap-2"><small className="ui-description">Source: {value?'Local override':entry?.inherited_origin?.[field]?origins[entry.inherited_origin[field]]:'No value available'}</small>{!!value&&<Button variant="ghost" size="compact" onClick={()=>onChange('')} aria-label={`Reset ${label} to inherited value`}>Reset to inherited</Button>}</div>
    {!!reference&&reference!==shown&&<p className="ui-description break-words">Reference workbook: {reference}</p>}
  </div>
}
