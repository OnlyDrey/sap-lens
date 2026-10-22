import type {
  ThemeColors,
  ThemePalette,
  ThemePreset
} from '@/api/configuration'
export const defaultDark: ThemePalette = {
  primary: '#1a003b',
  accent: '#7c85d4',
  background: '#0d0d1a',
  surface: '#111827',
  text: '#f1f5f9'
}
export const defaultLight: ThemePalette = {
  primary: '#182c53',
  accent: '#515793',
  background: '#f0f2f7',
  surface: '#ffffff',
  text: '#182c53'
}
export const themePresets: ThemePreset[] = [
  { name: 'SAP Lens Default', mode: 'dark', colors: defaultDark },
  {
    name: 'Midnight Blue',
    mode: 'dark',
    colors: {
      primary: '#101e3d',
      accent: '#71b7ff',
      background: '#08111f',
      surface: '#122036',
      text: '#eef5ff'
    }
  },
  {
    name: 'Corporate Blue',
    mode: 'dark',
    colors: {
      primary: '#063b68',
      accent: '#64b5f6',
      background: '#0b1728',
      surface: '#142940',
      text: '#f1f7ff'
    }
  },
  {
    name: 'Neutral Dark',
    mode: 'dark',
    colors: {
      primary: '#262626',
      accent: '#b4abff',
      background: '#121212',
      surface: '#242424',
      text: '#f5f5f5'
    }
  },
  { name: 'Light', mode: 'light', colors: defaultLight }
]
export const defaultThemeColors: ThemeColors = {
  dark: defaultDark,
  light: defaultLight,
  custom_presets: []
}
export const isHex = (value: string) => /^#[0-9a-fA-F]{6}$/.test(value)
export function contrast(a: string, b: string) {
  const luminance = (value: string) => {
    const channels = [1, 3, 5]
      .map((i) => parseInt(value.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
  }
  if (!isHex(a) || !isHex(b)) return 0
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + 0.05) / (values[1] + 0.05)
}
export const onColor = (color: string) =>
  contrast('#ffffff', color) >= contrast('#000000', color)
    ? '#ffffff'
    : '#000000'
export const paletteErrors = (p: ThemePalette) => {
  if (Object.values(p).some((v) => !isHex(v)))
    return ['Use six-digit HEX colors, for example #1a003b.']
  return (['background', 'surface'] as const)
    .filter((key) => contrast(p.text, p[key]) < 4.5)
    .map(
      (key) =>
        `Primary text against ${key === 'surface' ? 'card background' : 'application background'} needs at least 4.5:1 contrast (currently ${contrast(p.text, p[key]).toFixed(2)}:1).`
    )
}
function mix(first: string, second: string, amount: number) {
  return (
    '#' +
    [1, 3, 5]
      .map((i) =>
        Math.round(
          parseInt(first.slice(i, i + 2), 16) * amount +
            parseInt(second.slice(i, i + 2), 16) * (1 - amount)
        )
          .toString(16)
          .padStart(2, '0')
      )
      .join('')
  )
}
export function readableIconColor(color: string, background: string) {
  if (contrast(color, background) >= 3) return color
  const target = onColor(background)
  // Adjust luminance along the chosen hue before falling back to a neutral.
  // This affects rendering only; the user's stored color remains unchanged.
  for (let step = 1; step <= 10; step++) {
    const candidate = mix(target, color, step / 10)
    if (contrast(candidate, background) >= 3) return candidate
  }
  return target
}
export function themeTokens(p: ThemePalette): Record<string, string> {
  const safe = Object.values(p).every(isHex) ? p : defaultDark
  const focus =
    Math.min(
      contrast(safe.accent, safe.surface),
      contrast(safe.accent, safe.background)
    ) >= 4.5
      ? safe.accent
      : safe.text
  const semantic = (candidates: string[]) =>
    candidates.find(
      (color) =>
        Math.min(
          contrast(color, safe.surface),
          contrast(color, safe.background)
        ) >= 4.5
    ) || safe.text
  const success = semantic(['#17623c', '#6fe0a0'])
  const readableSurface = (candidate: string) =>
    contrast(safe.text, candidate) >= 4.5 ? candidate : safe.surface
  const border =
    [0.3, 0.4, 0.5, 0.6, 0.7, 1]
      .map((amount) => mix(safe.text, safe.surface, amount))
      .find((color) => contrast(color, safe.surface) >= 3) || safe.text
  return {
    '--on-success': onColor(success),
    '--success': success,
    '--error': semantic(['#b42318', '#ffb4a9']),
    '--warning': semantic(['#805000', '#ffd078']),
    '--info': semantic(['#1858a4', '#9ac7ff']),
    '--error-bg': safe.surface,
    '--info-bg': safe.surface,
    '--primary': safe.primary,
    '--on-primary': onColor(safe.primary),
    '--accent': safe.accent,
    '--on-accent': onColor(safe.accent),
    '--on-accent2': onColor(focus),
    '--accent2': focus,
    '--focus': focus,
    '--bg': safe.background,
    '--surface': safe.surface,
    '--surface2': readableSurface(mix(safe.text, safe.surface, 0.05)),
    '--text': safe.text,
    '--text2': safe.text,
    '--muted': safe.text,
    '--border': border,
    '--hover': readableSurface(mix(safe.accent, safe.surface, 0.15))
  }
}
