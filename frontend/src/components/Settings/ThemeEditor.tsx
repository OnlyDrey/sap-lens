import { useState, type CSSProperties } from 'react'
import { Building2, Layers, Palette, RotateCcw, Shield } from 'lucide-react'
import type { Configuration, ThemePalette } from '@/api/configuration'
import {
  defaultThemeColors,
  themePresets,
  themeTokens,
  paletteErrors,
  contrast,
  onColor,
  isHex
} from '@/lib/theme'

const labels: Record<keyof ThemePalette, string> = {
  primary: 'Primary color',
  accent: 'Accent color',
  background: 'Application background',
  surface: 'Surface / card background',
  text: 'Primary text color'
}
const control =
  'w-full min-w-0 rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-3 py-2 text-sm focus:ring-2 focus:ring-[var(--focus)] focus:outline-none'
export function ThemeEditor({
  draft,
  onChange
}: {
  draft: Configuration
  onChange: (patch: Partial<Configuration>) => void
}) {
  const [editing, setEditing] = useState<'dark' | 'light'>(
    draft.theme === 'light' ? 'light' : 'dark'
  )
  const [presetName, setPresetName] = useState('')
  const [nameError, setNameError] = useState('')
  const colors = draft.theme_colors || defaultThemeColors
  const palette = colors[editing]
  const errors = paletteErrors(palette)
  const update = (patch: Partial<ThemePalette>) =>
    onChange({
      theme_colors: { ...colors, [editing]: { ...palette, ...patch } }
    })
  const savePreset = () => {
    const name = presetName.trim()
    if (
      !name ||
      [...themePresets, ...colors.custom_presets].some(
        (p) => p.name.toLowerCase() === name.toLowerCase()
      )
    ) {
      setNameError('Enter a unique preset name.')
      return
    }
    if (colors.custom_presets.length >= 20) {
      setNameError('You can keep up to 20 custom presets.')
      return
    }
    onChange({
      theme_colors: {
        ...colors,
        custom_presets: [
          ...colors.custom_presets,
          { name, mode: editing, colors: { ...palette } }
        ]
      }
    })
    setNameError('')
    setPresetName('')
  }
  return (
    <div className="space-y-6">
      <div className="grid md:grid-cols-2 gap-5">
        <label className="text-sm font-medium">
          Theme
          <select
            className={`${control} mt-1`}
            value={draft.theme}
            onChange={(e) => {
              const mode = e.target.value as Configuration['theme']
              onChange({ theme: mode })
              if (mode !== 'system') setEditing(mode)
            }}
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">System — follow Windows appearance</option>
          </select>
        </label>
        <label className="text-sm font-medium">
          Edit colors for
          <select
            className={`${control} mt-1`}
            value={editing}
            onChange={(e) => setEditing(e.target.value as typeof editing)}
          >
            <option value="dark">Dark mode</option>
            <option value="light">Light mode</option>
          </select>
        </label>
      </div>
      <div>
        <h2 className="settings-subheading mb-3">Theme presets</h2>
        <div className="flex flex-wrap gap-2">
          {[...themePresets, ...colors.custom_presets].map((p) => (
            <button
              key={p.name}
              className="border border-[var(--border)] rounded-lg px-3 py-2 text-xs flex gap-2 items-center hover:bg-[var(--hover)]"
              onClick={() => {
                onChange({
                  theme: p.mode,
                  theme_colors: { ...colors, [p.mode]: { ...p.colors } }
                })
                setEditing(p.mode)
              }}
            >
              <span
                className="h-3 w-3 rounded-full border"
                style={{ background: p.colors.accent }}
              />
              {p.name}
            </button>
          ))}
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-5">
        {(Object.keys(labels) as (keyof ThemePalette)[]).map((key) => (
          <div key={key} className="space-y-2">
            <label htmlFor={`theme-${key}`} className="text-sm font-medium">
              {labels[key]}
            </label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                aria-label={`${labels[key]} visual selection`}
                className="h-10 w-12 shrink-0 bg-transparent cursor-pointer"
                value={isHex(palette[key]) ? palette[key] : '#000000'}
                onChange={(e) => update({ [key]: e.target.value })}
              />
              <input
                id={`theme-${key}`}
                className={`${control} font-mono`}
                value={palette[key]}
                maxLength={7}
                aria-invalid={!isHex(palette[key])}
                aria-describedby={
                  !isHex(palette[key]) ? `theme-${key}-error` : undefined
                }
                onChange={(e) => update({ [key]: e.target.value })}
              />
              <button
                aria-label={`Reset ${labels[key]}`}
                className="p-2"
                onClick={() =>
                  update({ [key]: defaultThemeColors[editing][key] })
                }
              >
                <RotateCcw size={15} />
              </button>
            </div>
            {!isHex(palette[key]) && (
              <p
                id={`theme-${key}-error`}
                className="text-xs text-[var(--error)]"
              >
                Enter a six-digit HEX value.
              </p>
            )}
          </div>
        ))}
      </div>
      <div aria-live="polite">
        {errors.length ? (
          errors.map((error) => (
            <p key={error} className="text-sm text-[var(--error)] mb-2">
              {error}
            </p>
          ))
        ) : (
          <p className="text-xs text-[var(--success)]">
            WCAG AA text contrast passes · background{' '}
            {contrast(palette.text, palette.background).toFixed(1)}:1 · cards{' '}
            {contrast(palette.text, palette.surface).toFixed(1)}:1
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm flex-1 min-w-40">
          Custom preset name
          <input
            className={`${control} mt-1`}
            value={presetName}
            maxLength={60}
            onChange={(e) => setPresetName(e.target.value)}
          />
        </label>
        <button
          disabled={Boolean(errors.length)}
          className="border border-[var(--border)] rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          onClick={savePreset}
        >
          Save custom preset
        </button>
      </div>
      {nameError && (
        <p role="alert" className="text-sm text-[var(--error)]">
          {nameError}
        </p>
      )}
      {colors.custom_presets.length > 0 && (
        <details className="settings-advanced">
          <summary>Manage custom presets</summary>
          {colors.custom_presets.map((p) => (
            <div key={p.name} className="flex justify-between text-sm">
              <span>{p.name}</span>
              <button
                onClick={() =>
                  onChange({
                    theme_colors: {
                      ...colors,
                      custom_presets: colors.custom_presets.filter(
                        (c) => c.name !== p.name
                      )
                    }
                  })
                }
              >
                Remove {p.name}
              </button>
            </div>
          ))}
        </details>
      )}
      <div>
        <h2 className="settings-subheading mb-3">Live preview</h2>
        <p className="text-xs text-[var(--muted)] mb-3">
          Preview only. Save applies these colors; Cancel discards your edits.
          Button labels and focus colors adapt for contrast.
        </p>
        <div
          aria-label="Theme live preview"
          className="rounded-xl overflow-hidden border border-[var(--border)]"
          style={
            {
              ...themeTokens(palette),
              backgroundColor: palette.background,
              color: palette.text
            } as CSSProperties
          }
        >
          <div
            className="flex gap-3 items-center p-4"
            style={{
              backgroundColor: palette.primary,
              color: onColor(palette.primary)
            }}
          >
            <img
              src="/sap-lens.png"
              alt=""
              className="w-9 h-9 object-contain"
            />
            <div>
              <b>Example Inc.</b>
              <p className="text-xs">SAP S/4HANA · DEMO 100</p>
            </div>
          </div>
          <div className="flex min-h-48">
            <div
              className="w-32 shrink-0 p-3 text-xs space-y-2"
              style={{ backgroundColor: palette.surface }}
            >
              <div
                className="flex items-center gap-2 p-2 rounded"
                style={{ backgroundColor: 'var(--hover)' }}
              >
                <Layers size={15} /> Roles
              </div>
              <div className="flex items-center gap-2 p-2">
                <Palette size={15} /> Settings
              </div>
            </div>
            <div className="p-4 flex-1 min-w-0">
              <div
                className="rounded-xl p-4"
                style={{ backgroundColor: palette.surface }}
              >
                <p className="font-semibold flex gap-2 items-center">
                  <Building2 size={17} /> Synthetic finance role
                </p>
                <p className="text-xs mt-2">DEMO:READ · 12 transactions</p>
                <button
                  type="button"
                  className="mt-4 rounded-lg px-3 py-2 text-xs font-semibold"
                  style={{
                    backgroundColor: palette.accent,
                    color: onColor(palette.accent)
                  }}
                >
                  View role
                </button>
              </div>
              <p className="text-xs mt-3 flex gap-2 items-center">
                <Shield size={14} /> Data stays on this computer
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
