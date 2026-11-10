/**
 * Theme and viewport matrices for browser tests, chosen by what a test actually asserts. Imported instead of writing nested
 * `for (theme) for (width)` loops, so the expansion of every test is explicit and reviewable (docs/development/TESTING.md).
 *
 * - Theme-sensitive checks (colors, contrast, focus appearance, borders): keep an explicit `for (const theme of THEMES)` loop.
 * - Theme-independent layout checks (geometry, overflow, wrapping, behavior at a width): `layoutMatrix(widths)` runs every width in the
 *   default theme and dark once, at a representative desktop width, so dark rendering of the screen stays exercised.
 * - Theme-independent behavior without a width dimension: `DEFAULT_THEME_ONLY`.
 */
export type Theme = 'light' | 'dark'
export interface Variant { theme: Theme; width: number }

export const THEMES: readonly Theme[] = ['light', 'dark']
export const DEFAULT_THEME_ONLY: readonly Theme[] = ['light']

/** Every width in light, plus dark at 1280 px (or the widest listed width when 1280 is not listed). */
export function layoutMatrix(widths: readonly number[]): Variant[] {
  const dark = widths.includes(1280) ? 1280 : Math.max(...widths)
  return [...widths.map(width => ({ theme: 'light' as const, width })), { theme: 'dark', width: dark }]
}

/** Playwright tags (filter with `--grep @visual` etc.). Categories are documented in docs/development/TESTING.md. */
/** `@regression` marks a test that REGRESSION must run although its spec is not in test-map.json profiles.regression_browser_specs.
 *  `@integration` marks an API-level browser-server integration test that complements a backend test; it runs in TARGETED and FULL only. */
export const TAGS = { visual: '@visual', a11y: '@a11y', workflow: '@workflow', component: '@component', smoke: '@smoke', regression: '@regression', integration: '@integration' } as const
