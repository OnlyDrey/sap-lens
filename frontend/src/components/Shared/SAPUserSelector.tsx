import type { UserRow } from '@/api/access'
import { Combobox } from './Combobox'
import { FormField } from './Controls'
/** Pure presentation: the caller supplies local/demo or authenticated server options. */
export function SAPUserSelector({
  label,
  value,
  options,
  onChange,
  onSearch,
  loading = false,
  hasMore = false,
}: {
  label: string
  value: string
  options: UserRow[]
  onChange: (s: string) => void
  onSearch?: (s: string) => void
  loading?: boolean
  hasMore?: boolean
}) {
  const describe = (key: string) => {
    const user = options.find((u) => u.username === key)
    return user
      ? `${user.username} · ${[user.first_name, user.last_name].filter(Boolean).join(' ') || 'Name unavailable'} · ${user.email || 'Email unavailable'}`
      : key
  }
  return (
    <FormField label={label}>
      <Combobox
        label={label}
        value={value}
        options={options.map((u) => u.username)}
        optionLabel={describe}
        onSearch={onSearch}
        serverFiltered={!!onSearch}
        allowCustom={false}
        clearLabel="Choose user"
        loading={loading}
        hasMore={hasMore}
        onChange={onChange}
      />
    </FormField>
  )
}
