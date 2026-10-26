import {Dialog} from '@/components/Shared/Dialog'
import {Button} from '@/components/Shared/Button'
import { SearchInput } from '@/components/Shared/Controls'
import { controlClass } from '@/components/Shared/Controls'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { StatusPill } from '@/components/Shared/StatusPill'
import { ColorControl } from './Controls'
import { isHex } from '@/lib/theme'
import { catalogIcon, iconLabel } from '@/components/Modules/CatalogIcon'
import { useState, lazy, Suspense } from 'react'
import { ChevronDown, RotateCcw } from 'lucide-react'
import { icons } from '@/components/Modules/ModuleRegistry'
import type { ModuleOverride, RegistryEntry } from '@/api/configuration'

import { labels } from './iconLabels'
type PickerProps = {
  value: string
  onChange: (value: string) => void
  moduleId: string
}
const IconPicker = lazy(() =>
  import('./IconPicker').catch(() => ({
    default: (_props: PickerProps) => (
      <p role="alert" className="text-sm text-[var(--error)]">
        Icon catalog could not be loaded. Your saved icon is unchanged. Reopen
        the application to retry.
      </p>
    )
  }))
)
const control = controlClass

export function ModuleEditor({
  modules,
  overrides,
  savedOverrides,
  onChange,
  search,
  onSearch
}: {
  modules: RegistryEntry[]
  savedOverrides: Record<string, ModuleOverride>
  overrides: Record<string, ModuleOverride>
  onChange: (value: Record<string, ModuleOverride>) => void
  search: string
  onSearch: (value: string) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [local,setLocal]=useState<ModuleOverride>({enabled:true})
  const [reset,setReset]=useState(false)
  const [initial,setInitial]=useState('')
  const cancel=()=>{if(JSON.stringify(local)!==initial && !window.confirm('Discard module changes?'))return;setExpanded(null)}
  const rows = modules.filter((m) =>
    `${m.id} ${m.name} ${m.aliases.join(' ')}`
      .toLowerCase()
      .includes(search.toLowerCase())
  )
  return (
    <div className="space-y-4">
      <label className="block text-sm font-medium">
        Find SAP module or area
        <SearchInput value={search} onChange={event=>onSearch(event.target.value)}/>

      </label>
      <p className="text-xs text-[var(--muted)]">
        {rows.length} areas · Open an area to customize its appearance. Disabled
        areas remain in your dataset.
      </p>
      <div className="divide-y divide-[var(--border)]">
        {rows.map((m) => {
          const override = expanded===m.id?local:overrides[m.id] || { enabled: true }
          const iconKey = (override.icon || m.default_icon || m.icon) as keyof typeof icons
          const Icon = icons[iconKey] || catalogIcon(iconKey)
          const defaultColor = m.default_color || m.color
          const defaultName = m.default_name || m.name
          const rawColor = override.color ?? defaultColor
          const color = isHex(rawColor) ? rawColor : defaultColor
          const edit = (patch: Partial<ModuleOverride>) =>
            (setReset(false),setLocal({ ...override, ...patch }))
          return (
            <div key={m.id}>
              <button
                className="module-list-row"
                aria-label={`Edit ${m.id} — ${override.display_name || defaultName}`}
                aria-expanded={expanded === m.id}
                onClick={() => {const value={...(overrides[m.id]||{enabled:m.enabled??true})};setLocal(value);setInitial(JSON.stringify(value));setReset(false);setExpanded(m.id)}}
              >
                <ModuleIcon
                  Icon={Icon}
                  color={color}
                  size="large"
                  disabled={!override.enabled}
                />
                <span className="min-w-0 flex-1 text-left">
                  <span className="font-semibold text-sm">
                    {m.id}{' '}
                    <span className="font-normal text-[var(--text2)] ml-2">
                      {override.display_name || defaultName}
                    </span>
                  </span>
                  <span className="block text-xs text-[var(--muted)] mt-1">
                    {m.category.replace(/-/g, ' ')}
                    {m.parent ? ` · Parent: ${m.parent}` : ''}
                  </span>
                </span>
                <StatusPill
                  enabled={savedOverrides[m.id]?.enabled ?? m.enabled ?? true}
                />
                <ChevronDown
                  size={16}
                  className={expanded === m.id ? 'rotate-180' : ''}
                />
              </button>
              {expanded === m.id && (
                <Dialog title={`Configure ${m.id} — ${defaultName}`} onClose={cancel} footer={<><Button onClick={cancel}>Cancel module changes</Button><Button variant="primary" disabled={!isHex(rawColor)} onClick={()=>{const next={...overrides};if(reset)delete next[m.id];else next[m.id]=local;onChange(next);setExpanded(null)}}>Apply module changes</Button></>}><p className="ui-description">Updates the Settings draft. Apply settings to persist; Cancel settings discards the parent draft.</p><div
                  className="module-editor space-y-4"
                  aria-label={`${m.id} appearance editor`}
                >
                  <div className="flex items-center gap-2 text-sm">
                    <ModuleIcon Icon={Icon} color={color} size="large" disabled={!override.enabled}/> Preview <StatusPill enabled={override.enabled} />
                  </div>
                  <div className="grid md:grid-cols-2 gap-4">
                    <label className="text-sm font-medium">
                      Display name
                      <input
                        aria-label={`${m.id} display name`}
                        className={`${control} mt-1`}
                        placeholder={defaultName}
                        value={override.display_name || ''}
                        onChange={(e) =>
                          edit({ display_name: e.target.value || null })
                        }
                      />
                    </label>
                  </div>
                  <label className="settings-filter-row">
                    <span>
                      <span className="block text-sm font-semibold">Show in module filters</span>
                      <span className="block text-xs text-[var(--text2)] mt-1" id={`module-filter-help-${m.id}`}>
                        Allow this area to appear as a filter when browsing SAP roles. Its roles remain in the dataset.
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      aria-label={`Show ${m.id} in module filters`}
                      aria-describedby={`module-filter-help-${m.id}`}
                      checked={override.enabled}
                      onChange={(e) => edit({ enabled: e.target.checked })}
                    />
                  </label>
                  <ColorControl
                    label={`${m.id} hexadecimal color`}
                    value={rawColor}
                    onChange={(color) => edit({ color })}
                    onReset={() => edit({ color: null })}
                  />
                  <div>
                    <p className="text-sm font-medium mb-3 flex gap-2 items-center">
                      <Icon size={18} /> Selected icon:{' '}
                      {labels[iconKey] || iconLabel(iconKey)}
                    </p>
                    <Suspense
                      fallback={<p role="status">Loading icon catalog…</p>}
                    >
                      <IconPicker
                        value={iconKey}
                        onChange={(icon) => edit({ icon })}
                        moduleId={m.id}
                      />
                    </Suspense>
                  </div>
                  <button
                    className="text-sm text-[var(--accent2)] flex gap-2 items-center py-2"
                    onClick={() => {
                      setLocal({enabled:true});setReset(true)
                    }}
                  >
                    <RotateCcw size={15} /> Reset {m.id} to default
                  </button>
                </div></Dialog>
              )}
            </div>
          )
        })}
        {!rows.length && (
          <p className="py-6 text-sm text-[var(--muted)]">
            No areas match your search.
          </p>
        )}
      </div>
    </div>
  )
}
