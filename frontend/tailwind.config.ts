import type { Config } from 'tailwindcss'
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-ui)'],
        mono: ['var(--font-code)'],
      },
    },
  },
  plugins: [],
}
export default config