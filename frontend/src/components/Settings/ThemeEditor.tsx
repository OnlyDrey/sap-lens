import { controlClass } from '@/components/Shared/Controls'
import { SettingsSelect, ColorControl } from './Controls'
import { useState, type CSSProperties } from 'react'
import { Building2, Layers, Palette, Shield, Save } from 'lucide-react'
import type { Configuration, ThemePalette } from '@/api/configuration'
import {
  defaultThemeColors,
  themePresets,
  themeTokens,
  paletteErrors,
  contrast,
  onColor
} from '@/lib/theme'

const labels: Record<keyof ThemePalette, string> = {
  primary: 'Primary color',
  accent: 'Accent color',
  secondary: 'Secondary color',
  background: 'Application background',
  surface: 'Surface / card background',
  text: 'Primary text color'
}
const control = controlClass
export function ThemeEditor({
  draft,
  onChange, logoSrc
}: {
  draft: Configuration
  logoSrc?: string
  onChange: (patch: Partial<Configuration>) => void
}) {
  const [editing, setEditing] = useState<'dark' | 'light'>(
    draft.theme === 'light' ? 'light' : 'dark'
  )
  const colorKeys=Object.keys(labels) as (keyof ThemePalette)[]
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
    <div className="space-y-4">
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
              src={logoSrc || "/sap-lens.png"}
              alt="Header logo preview"
              onError={event=>{if(!event.currentTarget.src.endsWith('/sap-lens.png'))event.currentTarget.src='/sap-lens.png'}}
              className="h-12 w-auto max-w-24 shrink-0 object-contain sm:max-w-40"
            />
            <div className="min-w-0">
              <b className="block break-words text-base font-semibold">{draft.organization.name || 'SAP Lens'}</b>
              <p className="text-xs">{draft.organization.platform === 'Other / Custom' ? draft.organization.custom_platform : draft.organization.platform} · {draft.organization.system_id} {draft.organization.client}</p><p className="text-xs">{draft.organization.description}</p>
            </div>
          </div>
          <div className="flex min-h-32 flex-col sm:flex-row">
            <div
              className="flex flex-wrap gap-2 p-3 text-xs sm:block sm:w-32 sm:shrink-0 sm:space-y-2"
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
                  className="mt-4 mr-2 rounded-lg px-3 py-2 text-xs font-semibold"
                  style={{
                    backgroundColor: palette.accent,
                    color: onColor(palette.accent)
                  }}
                >
                  View role
                </button>
                <button type="button" className="ui-button mt-4">
                  Secondary action
                </button>
              </div>
              <p className="text-xs mt-3 flex gap-2 items-center">
                <Shield size={14} /> Data stays on this computer
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <label className="text-sm font-medium">
          Theme
          <SettingsSelect
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
          </SettingsSelect>
        </label>
        <label className="text-sm font-medium">
          Edit colors for
          <SettingsSelect
            className={`${control} mt-1`}
            value={editing}
            onChange={(e) => setEditing(e.target.value as typeof editing)}
          >
            <option value="dark">Dark mode</option>
            <option value="light">Light mode</option>
          </SettingsSelect>
        </label>
      </div>
      <div>
        <h2 className="settings-subheading mb-3">Theme presets</h2>
        <div className="flex flex-wrap gap-2">
          {[...themePresets, ...colors.custom_presets].map((p) => (
            <button
              key={p.name}
              aria-pressed={
                draft.theme === p.mode &&
                JSON.stringify(colors[p.mode]) === JSON.stringify(p.colors)
              }
              className="theme-preset"
              onClick={() => {
                onChange({
                  theme: p.mode,
                  theme_colors: { ...colors, [p.mode]: { ...p.colors } }
                })
                setEditing(p.mode)
              }}
            >
              <span className="theme-palette" aria-hidden="true">
                {[p.colors.background, p.colors.primary, p.colors.accent, p.colors.secondary].map(
                  (color, i) => (
                    <i key={i} style={{ background: color }} />
                  )
                )}
              </span>
              {p.name}
            </button>
          ))}
        </div>
      </div>
      <section aria-label="Theme color settings" className="theme-color-section min-w-0 rounded-card border border-line p-3">
        <div className="theme-color-grid" role="group" aria-label="Theme colors">
          {colorKeys.map((key) => (
            <ColorControl
              key={key}
              label={labels[key]}
              value={palette[key]}
              onChange={(value) => update({ [key]: value })}
              onReset={() => update({ [key]: defaultThemeColors[editing][key] })}
            />
          ))}
        </div>
      </section>
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
      <div className="settings-card space-y-3">
        <h3 className="font-semibold text-sm">Save a reusable preset</h3>
        <p className="text-xs text-[var(--muted)]">
          Name this palette to reuse it later. Choose Save custom preset to add
          it to your draft, then Apply settings to keep it. Cancel discards
          unsaved presets.
        </p>
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
            disabled={Boolean(errors.length) || !presetName.trim()}
            className="border border-[var(--border)] rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            onClick={savePreset}
          >
            <Save size={16} aria-hidden="true" /> Save custom preset
          </button>
        </div>
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
    </div>
  )
}
