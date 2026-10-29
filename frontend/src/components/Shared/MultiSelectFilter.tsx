import { Combobox } from './Combobox'
import { FilterChip } from './FilterChip'

/** Searchable multi-select: pick values from a Combobox, keep them as removable chips. Values combine with OR; the caller owns the AND between filters. */
export function MultiSelectFilter({ label, values, options, onChange, onSearch, loading, hasMore, optionLabel = (value: string) => value, placeholder = 'All · type to search', maxSelected = 50 }: {
  label: string; values: string[]; options: string[]; onChange: (values: string[]) => void; onSearch?: (query: string) => void
  loading?: boolean; hasMore?: boolean; optionLabel?: (value: string) => string; placeholder?: string; maxSelected?: number
}) {
  return (
    <div className="grid min-w-0 gap-2">
      <Combobox label={label} value="" options={options.filter(option => !values.includes(option))} allowCustom={false} serverFiltered onSearch={onSearch} loading={loading} hasMore={hasMore} optionLabel={optionLabel} placeholder={values.length ? `${values.length} selected · add another` : placeholder}
        onChange={value => { if (!value) onChange([]); else if (!values.includes(value) && values.length < maxSelected) onChange([...values, value]) }} maxLength={100}/>
      {values.length > 0 && <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Selected ${label}`}>
        {values.map(value => <FilterChip key={value} removeLabel={`Remove ${label} ${value}`} onRemove={() => onChange(values.filter(item => item !== value))}>{optionLabel(value)}</FilterChip>)}
      </div>}
    </div>
  )
}
