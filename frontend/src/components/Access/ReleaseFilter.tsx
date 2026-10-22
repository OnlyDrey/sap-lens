import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { accessQuery } from '@/api/access'
import { Combobox } from '@/components/Shared/Combobox'
import { Filter } from './Shared'
type Options = { items: string[]; total: number; has_more: boolean; selected_available: boolean }
export function ReleaseFilter({ field, label, value, onChange, context }: { field: string; label: string; value: string; onChange: (value: string) => void; context: Record<string,string> }) {
  const [search, setSearch] = useState(''), [term, setTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setTerm(search), 180); return () => clearTimeout(timer) }, [search])
  const options = useQuery({ queryKey: ['release-options', field, context, term, value],
    queryFn: () => accessQuery<Options>('release-options', { ...context, field, search:term, selected:value }), gcTime:60_000 })
  return <Filter label={label}>
    <Combobox label={label} value={value} options={options.data?.items || []} onChange={onChange} onSearch={setSearch}
      maxLength={field === 'document_type' ? 20 : ['group', 'release_group', 'strategy'].includes(field) ? 100 : 512} placeholder="All · type to search" allowCustom={field !== 'document_type'} loading={options.isFetching} hasMore={options.data?.has_more}/>
    {options.isError && <span role="status" className="text-xs text-[var(--warning)]">Options unavailable. Existing filter retained.</span>}
    {!options.isFetching && options.data && !options.data.selected_available && <span role="status" className="text-xs text-[var(--warning)]">No available value matches this filter in the current context. Clear it or select All.</span>}
  </Filter>
}
