import { useEffect, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { defaultThemeColors, themeTokens } from '@/lib/theme'
import {
  fetchConfiguration,
  type ConfigurationResponse
} from '@/api/configuration'

export function useTheme() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration
  })
  const [systemDark, setSystemDark] = useState(
    () => matchMedia('(prefers-color-scheme: dark)').matches
  )
  const theme = data?.settings.theme || 'dark'
  const isDark = theme === 'dark' || (theme === 'system' && systemDark)
  useEffect(() => {
    const root = document.documentElement
    const palette = (data?.settings.theme_colors || defaultThemeColors)[
      isDark ? 'dark' : 'light'
    ]
    Object.entries(themeTokens(palette)).forEach(([key, value]) =>
      root.style.setProperty(key, value)
    )
    root.setAttribute('data-theme', isDark ? 'dark' : 'light')
    root.classList.toggle('dark', isDark)
    try {
      localStorage.setItem('sap-viz-theme', isDark ? 'dark' : 'light')
    } catch {
      /* optional pre-render hint */
    }
  }, [isDark, data?.settings.theme_colors])
  useEffect(() => {
    const query = matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    query.addEventListener('change', handler)
    return () => query.removeEventListener('change', handler)
  }, [])
  const toggle = useCallback(async () => {
    const result = await apiRequest<ConfigurationResponse>(
      '/api/configuration/theme',
      'POST',
      { theme: isDark ? 'light' : 'dark' }
    )
    qc.setQueryData(['configuration'], result)
  }, [isDark, qc])
  return { isDark, toggle }
}
