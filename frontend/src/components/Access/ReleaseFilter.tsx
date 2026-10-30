import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { accessQuery } from '@/api/access'
import { Combobox } from '@/components/Shared/Combobox'
import { MultiSelectFilter } from '@/components/Shared/MultiSelectFilter'
import { Filter } from './Shared'
type Options = { items: string[]; total: number; has_more: boolean; selected_available: boolean }
export function ReleaseFilter({ field, label, value, onChange, context, placeholder = 'All · type to search' }: { field: string; label: string; value: string; placeholder?: string; onChange: (value: string) => void; context: Record<string, string | string[]> }) {
  const [search, setSearch] = useState(''), [term, setTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setTerm(search), 180); return () => clearTimeout(timer) }, [search])
  const options = useQuery({ queryKey: ['release-options', field, context, term, value],
    queryFn: () => accessQuery<Options>('release-options', { ...context, field, search:term, selected:value }), gcTime:60_000 })
  return <Filter label={label}>
    <Combobox label={label} value={value} options={options.data?.items || []} onChange={onChange} onSearch={setSearch}
      maxLength={field === 'document_type' ? 20 : ['group', 'release_group', 'strategy'].includes(field) ? 100 : 512} placeholder={placeholder} allowCustom={field !== 'document_type'} loading={options.isFetching} hasMore={options.data?.has_more}/>
    {options.isError && <span role="status" className="text-xs text-[var(--warning)]">Options unavailable. Existing filter retained.</span>}
    {!options.isFetching && options.data && !options.data.selected_available && <span role="status" className="text-xs text-[var(--warning)]">No available value matches this filter in the current context. Clear it or select All.</span>}
  </Filter>
}

/** Multi-select over the same hierarchical option source; selected values never restrict their own options. */
export function ReleaseMultiFilter({ field, label, values, onChange, context, optionLabel }: { field: 'group' | 'release_area' | 'release_group' | 'strategy'; label: string; values: string[]; onChange: (values: string[]) => void; context: Record<string, string | string[]>; optionLabel?: (value: string) => string }) {
  const [search, setSearch] = useState(''), [term, setTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setTerm(search), 180); return () => clearTimeout(timer) }, [search])
  const options = useQuery({ queryKey: ['release-options', field, context, term], queryFn: () => accessQuery<Options>('release-options', { ...context, field, search: term }), gcTime: 60_000 })
  // Complete option lists only: a truncated list cannot prove that a retained choice is missing.
  const unavailable = options.data && !options.isFetching && !options.data.has_more && !term ? values.filter(value => !options.data!.items.includes(value)) : []
  return <Filter label={label}>
    <MultiSelectFilter label={label} values={values} options={options.data?.items || []} onChange={onChange} onSearch={setSearch} loading={options.isFetching} hasMore={options.data?.has_more} optionLabel={optionLabel} scope="within the other active release filters"/>
    {options.isError && <span role="status" className="text-xs text-[var(--warning)]">Options unavailable. Existing filter retained.</span>}
    {unavailable.length > 0 && <span role="status" className="text-xs text-[var(--warning)]">No available value matches {unavailable.join(', ')} in the current context. Remove it or change the other filters.</span>}
  </Filter>
}
