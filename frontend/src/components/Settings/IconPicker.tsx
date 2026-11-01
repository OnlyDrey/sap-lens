import { useState } from 'react'
import { Check } from 'lucide-react'
import { icons } from '@/components/Modules/ModuleRegistry'
import {
  catalogIcon,
  iconNames,
  iconLabel
} from '@/components/Modules/IconCatalog'
import { labels } from './iconLabels'
const control = 'settings-control'
export default function IconPicker({
  value,
  onChange,
  moduleId
}: {
  value: string
  onChange: (value: string) => void
  moduleId: string
}) {
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(48)
  const aliases: Record<string, string> = {
    DollarSign: 'finance money payment',
    Users: 'people employees hr',
    Shield: 'security authorization',
    Database: 'data storage',
    Truck: 'transport logistics',
    Building2: 'organization company',
    Layers: 'layers'
  }
  const matches = [...new Set([...Object.keys(icons), ...iconNames])].filter(
    (k) =>
      `${labels[k as keyof typeof labels] || ''} ${iconLabel(k)} ${aliases[k] || ''}`
        .toLowerCase()
        .includes(search.toLowerCase())
  )
  const keys = matches.slice(0, limit)
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium">
        Find an icon
        <input
          className={`${control} mt-1`}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setLimit(48)
          }}
          placeholder="Search finance, people, data…"
        />
      </label>
      <div
        className="icon-catalog-grid"
        role="group"
        aria-label={`${moduleId} icon choices`}
      >
        {keys.map((key, index) => {
          const Icon = icons[key as keyof typeof icons] || catalogIcon(key)
          return (
            <button
              key={key}
              type="button"
              aria-label={labels[key as keyof typeof labels] || iconLabel(key)}
              aria-pressed={value === key}
              onKeyDown={(e) => {
                const columns = getComputedStyle(
                  e.currentTarget.parentElement!
                ).gridTemplateColumns.split(' ').length
                let next: number
                if (e.key === 'ArrowRight') next = index + 1
                else if (e.key === 'ArrowLeft') next = index - 1
                else if (e.key === 'ArrowDown') next = index + columns
                else if (e.key === 'ArrowUp') next = index - columns
                else if (e.key === 'Home') next = 0
                else if (e.key === 'End') next = keys.length - 1
                else return
                e.preventDefault()
                const group = e.currentTarget.parentElement
                group?.querySelectorAll('button')[Math.max(0, Math.min(keys.length - 1, next))]?.focus()
              }}
              onClick={() => onChange(key)}
              className={`icon-choice ${value === key ? 'selected' : ''}`}
            >
              <Icon size={20} aria-hidden="true" />
              <span>
                {labels[key as keyof typeof labels] || iconLabel(key)}
              </span>
              {value === key && (
                <Check size={12} className="absolute top-1 right-1" />
              )}
            </button>
          )
        })}
      </div>
      <p role="status" className="text-xs text-[var(--muted)]">
        {matches.length} icons · Showing {keys.length}
      </p>
      {keys.length < matches.length && (
        <button
          className="settings-secondary-button"
          onClick={() => setLimit(limit + 48)}
        >
          Show more icons
        </button>
      )}
      {!keys.length && (
        <p className="text-sm text-[var(--muted)]">
          No icons match. Try another name.
        </p>
      )}
    </div>
  )
}
