import { onColor } from '@/lib/theme'
import { useState } from 'react'
import { ChevronDown, Search, RotateCcw, Check } from 'lucide-react'
import { icons } from '@/components/Modules/ModuleRegistry'
import type { ModuleOverride, RegistryEntry } from '@/api/configuration'

const labels: Record<keyof typeof icons, string> = {
  DollarSign: 'Finance',
  BarChart2: 'Analytics',
  Package: 'Materials',
  Wrench: 'Maintenance',
  Users: 'People',
  TrendingUp: 'Sales',
  Cog: 'Production',
  FolderKanban: 'Projects',
  CheckCircle: 'Quality',
  Server: 'Infrastructure',
  Warehouse: 'Warehouse',
  Layers: 'Layers',
  Shield: 'Security',
  Database: 'Data',
  Truck: 'Transport',
  Building2: 'Organization',
  Globe: 'Global',
  Code: 'Development',
  FileText: 'Documents',
  Leaf: 'Environment',
  Hash: 'General'
}
const control =
  'w-full min-w-0 rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-3 py-2 text-sm focus:ring-2 focus:ring-[var(--focus)] focus:outline-none'

function IconPicker({
  value,
  onChange,
  moduleId
}: {
  value: string
  onChange: (value: string) => void
  moduleId: string
}) {
  const [search, setSearch] = useState('')
  const keys = (Object.keys(icons) as (keyof typeof icons)[]).filter((k) =>
    `${labels[k]} ${k}`.toLowerCase().includes(search.toLowerCase())
  )
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium">
        Find an icon
        <input
          className={`${control} mt-1`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search finance, people, data…"
        />
      </label>
      <div
        className="grid grid-cols-3 lg:grid-cols-5 gap-2"
        role="group"
        aria-label={`${moduleId} icon choices`}
      >
        {keys.map((key, index) => {
          const Icon = icons[key]
          return (
            <button
              key={key}
              type="button"
              aria-label={labels[key]}
              aria-pressed={value === key}
              onKeyDown={(e) => {
                const columns = getComputedStyle(
                  e.currentTarget.parentElement!
                ).gridTemplateColumns.split(' ').length
                let next = index
                if (e.key === 'ArrowRight') next = index + 1
                else if (e.key === 'ArrowLeft') next = index - 1
                else if (e.key === 'ArrowDown') next = index + columns
                else if (e.key === 'ArrowUp') next = index - columns
                else if (e.key === 'Home') next = 0
                else if (e.key === 'End') next = keys.length - 1
                else return
                e.preventDefault()
                const group = e.currentTarget.parentElement
                group
                  ?.querySelectorAll('button')
                  [Math.max(0, Math.min(keys.length - 1, next))]?.focus()
              }}
              onClick={() => onChange(key)}
              className={`icon-choice ${value === key ? 'selected' : ''}`}
            >
              <Icon size={20} aria-hidden="true" />
              <span>{labels[key]}</span>
              {value === key && (
                <Check size={12} className="absolute top-1 right-1" />
              )}
            </button>
          )
        })}
      </div>
      {!keys.length && (
        <p className="text-sm text-[var(--muted)]">
          No icons match. Try another name.
        </p>
      )}
    </div>
  )
}

export function ModuleEditor({
  modules,
  overrides,
  onChange,
  search,
  onSearch
}: {
  modules: RegistryEntry[]
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
          const iconKey = (override.icon || m.icon) as keyof typeof icons
          const Icon = icons[iconKey] || icons.Hash
          const color = override.color || m.color
          const edit = (patch: Partial<ModuleOverride>) =>
            onChange({ ...overrides, [m.id]: { ...override, ...patch } })
          return (
            <div key={m.id}>
              <button
                className="module-list-row"
                aria-label={`Edit ${m.id} — ${override.display_name || m.name}`}
                aria-expanded={expanded === m.id}
                onClick={() => setExpanded(expanded === m.id ? null : m.id)}
              >
                <span
                  className="rounded-lg p-2 text-current shrink-0"
                  style={{ backgroundColor: color, color: onColor(color) }}
                >
                  <Icon size={19} />
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="font-semibold text-sm">
                    {m.id}{' '}
                    <span className="font-normal text-[var(--text2)] ml-2">
                      {override.display_name || m.name}
                    </span>
                  </span>
                  <span className="block text-xs text-[var(--muted)] mt-1">
                    {m.category.replace(/-/g, ' ')}
                    {m.parent ? ` · Parent: ${m.parent}` : ''}
                  </span>
                </span>
                <span
                  className={`text-xs ${override.enabled ? 'text-[var(--success)]' : 'text-[var(--muted)]'}`}
                >
                  {override.enabled ? 'Enabled' : 'Disabled'}
                </span>
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
                  <div className="grid md:grid-cols-2 gap-4">
                    <label className="text-sm font-medium">
                      Display name
                      <input
                        aria-label={`${m.id} display name`}
                        className={`${control} mt-1`}
                        placeholder={m.name}
                        value={override.display_name || ''}
                        onChange={(e) =>
                          edit({ display_name: e.target.value || null })
                        }
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={override.enabled}
                        onChange={(e) => edit({ enabled: e.target.checked })}
                      />{' '}
                      Enabled in module filters
                    </label>
                  </div>
                  <div>
                    <p className="text-sm font-medium mb-2">Color</p>
                    <div className="flex flex-wrap gap-3 items-center">
                      <input
                        type="color"
                        aria-label={`${m.id} color`}
                        className="h-10 w-12 cursor-pointer bg-transparent"
                        value={color}
                        onChange={(e) => edit({ color: e.target.value })}
                      />
                      <label className="text-xs">
                        Hexadecimal
                        <input
                          aria-label={`${m.id} hexadecimal color`}
                          className={`${control} max-w-36`}
                          pattern="#[0-9a-fA-F]{6}"
                          value={color}
                          onChange={(e) => edit({ color: e.target.value })}
                        />
                      </label>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium mb-3 flex gap-2 items-center">
                      <Icon size={18} /> Selected icon:{' '}
                      {labels[iconKey] || 'General'}
                    </p>
                    <IconPicker
                      value={iconKey}
                      onChange={(icon) => edit({ icon })}
                      moduleId={m.id}
                    />
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
