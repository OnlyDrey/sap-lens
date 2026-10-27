import type { Config } from 'tailwindcss'
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--bg)', surface: 'var(--surface)', elevated: 'var(--surface2)',
        content: 'var(--text)', secondary: 'var(--text2)', muted: 'var(--muted)',
        line: 'var(--border)', action: 'var(--accent2)', hover: 'var(--hover)', focus: 'var(--focus)',
      },
      borderRadius: { control: 'var(--radius-control)', card: 'var(--radius-card)' },
      minHeight: { control: 'var(--control-height)' },
      fontFamily: {
        sans: ['var(--font-ui)'],
        mono: ['var(--font-code)'],
      },
    },
  },
  plugins: [],
}
export default config