import { useQuery } from '@tanstack/react-query'
import { fetchOrganizationOptions, organizationKey } from '@/api/functionalGroups'
import { MultiSelectFilter } from './MultiSelectFilter'

/** Functional Group and Manager filters for user-level views. Selection is sent to the server (OR within a filter, AND with every other filter)
 *  so paginated results and totals stay correct. Options show the number of SAP users. */
export function OrganizationFilter({ kind, values, onChange }: { kind: 'functional_group' | 'manager'; values: string[]; onChange: (values: string[]) => void }) {
  const options = useQuery({ queryKey: organizationKey, queryFn: fetchOrganizationOptions, staleTime: 15_000 })
  const items = (kind === 'manager' ? options.data?.managers : options.data?.functional_groups) ?? []
  const label = kind === 'manager' ? 'Manager' : 'Functional Group'
  return (
    <MultiSelectFilter label={label} values={values} options={items.map(item => item.value)} onChange={onChange}
      optionLabel={value => { const item = items.find(entry => entry.value === value); return item ? `${item.label} (${item.count})` : value }}
      placeholder={kind === 'manager' ? 'All managers' : 'All Functional Groups'} />
  )
}

/** Display label for a stored filter value (for removable chips). Falls back to the raw value while options load. */
export function useOrganizationLabel() {
  const options = useQuery({ queryKey: organizationKey, queryFn: fetchOrganizationOptions, staleTime: 15_000 })
  return (kind: 'functional_group' | 'manager', value: string) => {
    const items = (kind === 'manager' ? options.data?.managers : options.data?.functional_groups) ?? []
    return items.find(item => item.value === value)?.label ?? value
  }
}
