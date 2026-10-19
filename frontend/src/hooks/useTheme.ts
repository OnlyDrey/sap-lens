import { useEffect, useState, useCallback } from 'react'

export function useTheme() {
  const [isDark, setIsDark] = useState<boolean>(() => {
    const saved = localStorage.getItem('sap-viz-theme')
    if (saved !== null) return saved === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    const root = document.documentElement
    const theme = isDark ? 'dark' : 'light'
    root.setAttribute('data-theme', theme)
    // Also keep .dark class in sync for any remaining Tailwind dark: variants
    root.classList.toggle('dark', isDark)
    localStorage.setItem('sap-viz-theme', theme)
  }, [isDark])

  // Sync with OS preference changes (when no saved preference)
  useEffect(() => {
    if (localStorage.getItem('sap-viz-theme') !== null) return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setIsDark(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const toggle = useCallback(() => setIsDark(d => !d), [])
  return { isDark, toggle }
}