import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { StatusPill } from '@/components/Shared/StatusPill'
import { ColorControl } from './Controls'
import { isHex } from '@/lib/theme'
import { catalogIcon, iconLabel } from '@/components/Modules/CatalogIcon'
import { useState, lazy, Suspense } from 'react'
import { ChevronDown, Search, RotateCcw } from 'lucide-react'
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
const control =
  'w-full min-w-0 rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-3 py-2 text-sm focus:ring-2 focus:ring-[var(--focus)] focus:outline-none'

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
  const rows = modules.filter((m) =>
    `${m.id} ${m.name} ${m.aliases.join(' ')}`
      .toLowerCase()
      .includes(search.toLowerCase())
  )
  return (
    <div className="space-y-4">
      <label className="block text-sm font-medium">
        Find SAP module or area
        <div className="relative mt-1">
          <Search
            size={17}
            className="absolute left-3 top-3 text-[var(--muted)]"
          />
          <input
            className={`${control} pl-10`}
            value={search}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
      </label>
      <p className="text-xs text-[var(--muted)]">
        {rows.length} areas · Open an area to customize its appearance. Disabled
        areas remain in your dataset.
      </p>
      <div className="divide-y divide-[var(--border)]">
        {rows.map((m) => {
          const override = overrides[m.id] || { enabled: true }
          const iconKey = (override.icon || m.default_icon || m.icon) as keyof typeof icons
          const Icon = icons[iconKey] || catalogIcon(iconKey)
          const defaultColor = m.default_color || m.color
          const defaultName = m.default_name || m.name
          const rawColor = override.color ?? defaultColor
          const color = isHex(rawColor) ? rawColor : defaultColor
          const edit = (patch: Partial<ModuleOverride>) =>
            onChange({ ...overrides, [m.id]: { ...override, ...patch } })
          return (
            <div key={m.id}>
              <button
                className="module-list-row"
                aria-label={`Edit ${m.id} — ${override.display_name || defaultName}`}
                aria-expanded={expanded === m.id}
                onClick={() => setExpanded(expanded === m.id ? null : m.id)}
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
                <div
                  className="module-editor space-y-5"
                  aria-label={`${m.id} appearance editor`}
                >
                  <div className="flex items-center gap-2 text-sm">
                    Preview <StatusPill enabled={override.enabled} />
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
                      const next = { ...overrides }
                      delete next[m.id]
                      onChange(next)
                    }}
                  >
                    <RotateCcw size={15} /> Reset {m.id} to default
                  </button>
                </div>
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
