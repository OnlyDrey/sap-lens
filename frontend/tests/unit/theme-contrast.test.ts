import test from 'node:test'
import assert from 'node:assert/strict'
import { contrast, onColor, themePresets, themeTokens, paletteErrors } from '../../src/lib/theme.ts'

// Moved from ux.spec.ts. Same thresholds: WCAG 4.5:1 for text, 3:1 for borders.
test('theme tokens keep primary controls readable across grayscale accents and presets', () => {
  for (let value = 0; value <= 255; value++) {
    const channel = value.toString(16).padStart(2, '0'); const color = '#' + channel.repeat(3)
    assert.ok(contrast(color, onColor(color)) >= 4.5, color)
  }
  for (const preset of themePresets) {
    assert.deepEqual(paletteErrors(preset.colors), [])
    const tokens = themeTokens(preset.colors)
    assert.ok(contrast(tokens['--text'], tokens['--surface2']) >= 4.5, `${preset.name} text on surface2`)
    assert.ok(contrast(tokens['--text'], tokens['--hover']) >= 4.5, `${preset.name} text on hover`)
    assert.ok(contrast(tokens['--border'], tokens['--surface']) >= 3, `${preset.name} border on surface`)
  }
})
