import type { Config } from 'tailwindcss'
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ep: '#1A003B', eo: '#FA6414', ea: '#EEA300',
        eb: '#515793', en: '#182C53', epet: '#527594', ealm: '#BDD7A5',
      },
      fontFamily: {
        sans: ['Montserrat', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
export default config